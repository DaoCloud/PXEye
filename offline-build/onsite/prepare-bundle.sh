#!/usr/bin/env bash
# Run with bash; activation is deliberately a separate source command.
if [[ "${BASH_SOURCE[0]}" != "$0" ]]; then
  printf '%s\n' 'Run: bash /path/to/tools/prepare-bundle.sh; then source the generated environment.sh' >&2
  return 1
fi
set -euo pipefail
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
if [[ -f "$SCRIPT_DIR/onsite/prepare_bundle.py" ]]; then
  exec python3 "$SCRIPT_DIR/onsite/prepare_bundle.py" "$@"
fi
# Source checkout entry; exported kits place this wrapper in tools/.
exec python3 "$SCRIPT_DIR/prepare_bundle.py" "$@"
