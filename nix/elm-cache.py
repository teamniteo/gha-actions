"""Seed a private ELM_HOME from an immutable snapshot, then publish after setup."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile


def restore(state):
    state.unlink(missing_ok=True)
    root = Path(os.environ["GITHUB_WORKSPACE"])
    names = subprocess.check_output(
        ["git", "ls-files", "-z", "--", "elm.json", "**/elm.json"], cwd=root,
    ).split(b"\0")
    files = sorted(set(names) - {b""})
    if not files:
        print("Elm cache skipped: no tracked elm.json", flush=True)
        return
    # ELM_HOME keeps each compiler version under its own directory, so the
    # Nix pins that choose the compiler stay out of the key: a weekly nixpkgs
    # bump must not send every job back to downloading every package.
    scope = hashlib.sha256(Path(__file__).read_bytes())
    for name in ("GITHUB_REPOSITORY", "RUNNER_OS", "RUNNER_ARCH"):
        scope.update(os.environ.get(name, "").encode() + b"\0")
    digest = hashlib.sha256()
    for name in files:
        digest.update(name + b"\0")
        digest.update(hashlib.sha256((root / os.fsdecode(name)).read_bytes()).digest())
    cache = Path(os.environ["HOST_CACHE_DIR"]) / "elm"
    cache.mkdir(exist_ok=True)
    prefix = f"snapshot-{scope.hexdigest()[:16]}-"
    entry = cache / f"{prefix}{digest.hexdigest()}"
    # Extra packages are harmless, so the newest snapshot of this repository
    # leaves only the packages it lacks to download.
    source = entry if entry.is_dir() else max(
        cache.glob(f"{prefix}*"), key=lambda path: path.stat().st_mtime, default=None,
    )
    home = Path(os.environ["ELM_HOME"])
    if source:
        try:
            shutil.copytree(source, home, dirs_exist_ok=True)
        except OSError:
            # Never leave a partially restored package tree for Elm to consume.
            shutil.rmtree(home)
            home.mkdir()
            raise
    if source == entry:
        print(f"Elm cache hit: {entry.name}", flush=True)
        return
    state.write_text(json.dumps({
        "home": str(home), "entry": str(entry), "source": source and str(source),
    }))
    if source:
        print(f"Elm cache miss: {entry.name}, restored {source.name}", flush=True)
    else:
        print(f"Elm cache miss: {entry.name}", flush=True)


def save(state):
    if not state.is_file():
        print("Elm cache save skipped: no snapshot miss to publish", flush=True)
        return
    saved = json.loads(state.read_text())
    home, entry = Path(saved["home"]), Path(saved["entry"])
    # A dist hit may have skipped Elm entirely. A snapshot without this job's
    # packages would hit on every later run and never be published again.
    def compiled(tree):
        return {path.relative_to(tree) for path in tree.glob("*/packages/*/*/*/artifacts.dat")}
    restored = compiled(Path(saved["source"])) if saved["source"] else set()
    if not compiled(home) - restored:
        print("Elm cache save skipped: no newly compiled packages", flush=True)
        return
    if entry.is_dir():
        print(f"Elm cache already published by another runner: {entry.name}", flush=True)
        state.unlink()
        return
    with tempfile.TemporaryDirectory(prefix=".snapshot-", dir=entry.parent) as temporary:
        staging = Path(temporary) / "elm"
        shutil.copytree(home, staging)
        for path in staging.rglob("*"):
            path.chmod(0o755 if path.is_dir() else 0o644)
        staging.chmod(0o755)
        # copytree carries the restored snapshot's mtime, and the fallback
        # picks by mtime.
        os.utime(staging)
        try:
            staging.rename(entry)
        except OSError:
            if not entry.is_dir():
                raise
            print(f"Elm cache already published by another runner: {entry.name}", flush=True)
        else:
            print(f"Elm cache saved: {entry.name}", flush=True)
    state.unlink()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=("restore", "save"))
    parser.add_argument("state", type=Path)
    args = parser.parse_args()
    try:
        {"restore": restore, "save": save}[args.operation](args.state)
    except (OSError, ValueError, KeyError, subprocess.CalledProcessError) as error:
        print(f"Elm cache {args.operation} skipped: {error}", flush=True)


if __name__ == "__main__":
    main()
