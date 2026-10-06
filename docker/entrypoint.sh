#!/bin/sh
# Prepare the state volume, then start both services. Keys are created the first time and kept after that.
set -e
mkdir -p /state/data /state/signing_keys
touch /state/audit.log /state/issuer_audit.jsonl
[ -e /state/env ] || : > /state/env
chmod 600 /state/env 2>/dev/null || true
exec python run_all.py --host 0.0.0.0
