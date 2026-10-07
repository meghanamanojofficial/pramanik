#!/bin/sh
# Prepare the state volume, then start both services. Keys are created the first time and kept after that.
#
# Hosting platforms (Render, Docker volumes ...) usually mount the disk owned by root. So this starts as root, hands the
# state folder to the unprivileged "pramanik" user, and then runs the app as that user, never as root.
set -e
if [ "$(id -u)" = "0" ]; then
  mkdir -p /state/data /state/signing_keys
  chown -R 10001:10001 /state
  exec setpriv --reuid=10001 --regid=10001 --clear-groups "$0" "$@"
fi
mkdir -p /state/data /state/signing_keys
touch /state/audit.log /state/issuer_audit.jsonl
[ -e /state/env ] || : > /state/env
chmod 600 /state/env 2>/dev/null || true
exec python run_all.py --host 0.0.0.0
