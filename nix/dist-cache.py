"""Restore before shell setup; save successful outputs using the original key.

All configured paths are relative to the checkout root. Nix definitions and
pins must be included in inputs so toolchain changes invalidate the cache.
"""

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile


def relative_path(value):
    path = Path(value)
    if path.is_absolute() or ".." in path.parts or path == Path("."):
        raise ValueError(f"Expected a relative child path: {value}")
    return path


def cache_key(config, root):
    inputs = [str(relative_path(path)) for path in config["inputs"]]
    environment = {name: os.environ.get(name) for name in config.get("environment", [])}
    digest = hashlib.sha256(Path(__file__).read_bytes())
    for value in (config, environment, os.environ.get("GITHUB_REPOSITORY"),
                  os.environ.get("RUNNER_OS"), os.environ.get("RUNNER_ARCH")):
        digest.update(json.dumps(value, sort_keys=True).encode() + b"\0")
    names = subprocess.check_output(
        ["git", "ls-files", "-z", "--cached", "--others", "--exclude-standard",
         "--", *inputs], cwd=root,
    ).split(b"\0")
    for name in sorted(set(names) - {b""}):
        path = root / os.fsdecode(name)
        if path.is_file():
            digest.update(name + b"\0")
            digest.update(hashlib.sha256(path.read_bytes()).digest())
    if config.get("git_dates"):
        if subprocess.check_output(
            ["git", "rev-parse", "--is-shallow-repository"], cwd=root,
        ).strip() == b"true":
            raise ValueError("Git dates require full history")
        dated_files = subprocess.check_output(
            ["git", "ls-files", "-z", "--cached", "--others", "--exclude-standard",
             "--", *config["git_dates"]], cwd=root,
        ).split(b"\0")
        for name in sorted(set(dated_files) - {b""}):
            date = subprocess.check_output(
                ["git", "log", "-1", "--format=%cs", "--", os.fsdecode(name)], cwd=root,
            ).strip()
            digest.update(name + b"\0" + date + b"\0")
    return digest.hexdigest()


def remove(path):
    if path.is_symlink() or path.is_file():
        path.unlink()
    elif path.exists():
        shutil.rmtree(path)


def copy(source, destination):
    destination.parent.mkdir(parents=True, exist_ok=True)
    if source.is_dir():
        shutil.copytree(source, destination)
    else:
        shutil.copy2(source, destination)


def prepare_cache(root):
    cache = root / "dist"
    # Do not create the host root: a missing mount must use a normal build.
    try:
        cache.mkdir(mode=0o1777)
    except FileExistsError:
        if cache.is_symlink() or not cache.is_dir():
            raise ValueError("Cache path is not a directory")
    else:
        cache.chmod(0o1777)  # Override the runner's restrictive umask.
    return cache


def restore(state):
    state.unlink(missing_ok=True)
    root = Path(os.environ["GITHUB_WORKSPACE"])
    config_path = root / ".github/dist-cache.json"
    cache_root = os.environ.get("HOST_CACHE_DIR")
    if not cache_root:
        print("Dist cache skipped: HOST_CACHE_DIR is not set", flush=True)
        return
    if os.environ.get("DIST_CACHE_ENABLED") == "0":
        print("Dist cache skipped: disabled by DIST_CACHE_ENABLED=0", flush=True)
        return
    if not config_path.is_file():
        print("Dist cache skipped: .github/dist-cache.json is absent", flush=True)
        return
    if os.environ.get("GITHUB_EVENT_NAME") == "pull_request":
        event = json.loads(Path(os.environ["GITHUB_EVENT_PATH"]).read_text())
        # Checkout normally points at a merge commit; inspect the actual PR head.
        message = subprocess.check_output(
            ["git", "-C", str(root), "log", "-1", "--format=%B",
             event["pull_request"]["head"]["sha"]],
            text=True,
        )
        if "[ci full]" in message:
            print("Dist cache skipped: forced by [ci full] in the latest PR commit", flush=True)
            return
    config = json.loads(config_path.read_text())
    outputs = [str(relative_path(path)) for path in config["outputs"]]
    symlinks = {str(relative_path(link)): str(relative_path(target))
                for link, target in config.get("symlinks", {}).items()}
    if not outputs or not config["inputs"]:
        raise ValueError("Inputs and outputs must not be empty")
    cache = prepare_cache(Path(cache_root))
    entry = cache / f"entry-{cache_key(config, root)}"
    if all((entry / path).exists() for path in outputs):
        try:
            for output in outputs:
                remove(root / output)
                copy(entry / output, root / output)
            for link, target in symlinks.items():
                if not (root / target).exists():
                    raise ValueError(f"Missing symlink target: {target}")
                remove(root / link)
                (root / link).parent.mkdir(parents=True, exist_ok=True)
                (root / link).symlink_to(root / target)
        except (OSError, ValueError):
            # A partial restore must not leave a link that skips the build.
            for link in symlinks:
                if (root / link).is_symlink():
                    (root / link).unlink()
            raise
        print(f"Dist cache hit: {entry.name}", flush=True)
        return
    state.write_text(json.dumps({"root": str(root), "entry": str(entry), "outputs": outputs}))
    print(f"Dist cache miss: {entry.name}", flush=True)


def save(state):
    if not state.is_file():
        print("Dist cache save skipped: no cache miss to publish", flush=True)
        return
    saved = json.loads(state.read_text())
    root, entry = Path(saved["root"]), Path(saved["entry"])
    # Atomic publication lets concurrent jobs keep the first complete build.
    with tempfile.TemporaryDirectory(prefix=".entry-", dir=entry.parent) as temporary:
        staging = Path(temporary) / "build"
        for output in saved["outputs"]:
            copy(root / output, staging / output)
        # Runner slots have different mapped UIDs; published outputs are readable.
        for path in staging.rglob("*"):
            executable = path.is_dir() or bool(path.stat().st_mode & 0o111)
            path.chmod(0o755 if executable else 0o644)
        staging.chmod(0o755)
        try:
            staging.rename(entry)
        except OSError:
            # Sticky directories can report EPERM when another slot won the race.
            if not all((entry / output).exists() for output in saved["outputs"]):
                raise
            print(f"Dist cache already published by another runner: {entry.name}", flush=True)
        else:
            print(f"Dist cache saved: {entry.name}", flush=True)
    state.unlink()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=("restore", "save"))
    parser.add_argument("state", type=Path)
    args = parser.parse_args()
    try:
        {"restore": restore, "save": save}[args.operation](args.state)
    except (OSError, ValueError, KeyError, TypeError, subprocess.CalledProcessError) as error:
        print(f"Dist cache {args.operation} skipped: {error}", flush=True)


if __name__ == "__main__":
    main()
