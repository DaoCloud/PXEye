#!/usr/bin/env bash
# Uses CONFIG/BUNDLE/WORK from environment.sh and explicit CONTEXT/NICO_NAMESPACE.
if [[ "${BASH_SOURCE[0]}" != "$0" ]]; then
  printf '%s\n' 'Run this helper with bash, do not source it.' >&2
  return 1
fi
set -euo pipefail
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
exec python3 "$SCRIPT_DIR/onsite.py" prepare-site "$@"
