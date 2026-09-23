# The image fly-deploy builds: the runtime Python, the relocatable uv venv
# the action makes, and the app's files under /app.
{
  pkgs,
  python,
  venv,
  app,
  cmd,
  name,
  files ? { },
}:
pkgs.dockerTools.streamLayeredImage {
  inherit name;
  contents = [
    pkgs.bash
    pkgs.cacert
    pkgs.coreutils
    pkgs.dockerTools.fakeNss
    python
  ];
  # Copies out of the store keep its read-only mode, which would refuse the
  # extra files and any __pycache__ later; executables keep their bits.
  # https://github.com/teamniteo/ops/issues/2943
  extraCommands = ''
    mkdir -m 1777 tmp
    mkdir app
    cp -r ${app}/. app/
    cp -r ${venv} app/.venv
    chmod -R u+w app
    ${pkgs.lib.concatStrings (pkgs.lib.mapAttrsToList (dest: src: "cp -r ${src} app/${dest}\n") files)}
  '';
  config = {
    Cmd = cmd;
    Env = [
      "PATH=/app/.venv/bin:/bin"
      "SSL_CERT_FILE=/etc/ssl/certs/ca-bundle.crt"
    ];
    WorkingDir = "/app";
  };
}
