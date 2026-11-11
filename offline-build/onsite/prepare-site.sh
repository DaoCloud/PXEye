#!/usr/bin/env bash
# Source this helper to retain the selected context/namespace in the current shell.
_pxeye_prepare_site() {
  local script_dir activation result
  script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)" || return
  activation="$(mktemp)" || return
  if python3 "$script_dir/onsite.py" prepare-site "$@" --activation-file "$activation"; then
    if source "$activation"; then
      result=0
    else
      result=$?
    fi
  else
    result=$?
  fi
  rm -f -- "$activation"
  return "$result"
}
_pxeye_prepare_site "$@"
