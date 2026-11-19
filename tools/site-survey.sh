#!/usr/bin/env bash
# Field survey entry point. Every call is self-contained, so it can be run from a fresh
# shell (as AI assistants do). Run from the repository root.
#
#   tools/site-survey.sh cli <nico-admin-cli read command...>    read-only CLI (tools/core-cli.py)
#   tools/site-survey.sh survey <list|describe|message|call|ids> ...   gRPC reads (tools/core-survey.py)
#   tools/site-survey.sh capture                                  verbatim capture (tools/core-capture.py)
#   tools/site-survey.sh check                                    connection, version and access
#
# Add `--save <name>` as the first argument to also write the output to
# $SURVEY_DIR/<name> (cli/ and survey/ outputs go under those subdirectories).
#
# Configuration, through the environment:
#   SURVEY_NAMESPACE   namespace of the read-only observer instance        (required)
#   SURVEY_DEPLOYMENT  its Deployment name                                  (required)
#   SURVEY_CONTEXT     kubectl context                                      (optional)
#   SURVEY_SSH         command that reaches a host where kubectl works,
#                      e.g. "ssh -p 2022 root@<node>"; empty runs kubectl here (optional)
#   SURVEY_DIR         survey directory outside the repository, for --save and capture
set -euo pipefail

here=$(cd "$(dirname "$0")" && pwd)
: "${SURVEY_NAMESPACE:?set SURVEY_NAMESPACE to the observer namespace}"
: "${SURVEY_DEPLOYMENT:?set SURVEY_DEPLOYMENT to the observer Deployment}"

save=""
if [[ "${1:-}" == "--save" ]]; then
  save=${2:?--save needs a file name}
  shift 2
fi
mode=${1:?usage: site-survey.sh [--save name] cli|survey|capture|check ...}
shift

remote() {
  # Run one command in the observer container, feeding a local tool on standard input.
  local tool=$1
  shift
  local kubectl=(kubectl)
  [[ -n "${SURVEY_CONTEXT:-}" ]] && kubectl+=(--context "$SURVEY_CONTEXT")
  local command=("${kubectl[@]}" -n "$SURVEY_NAMESPACE" exec -i "deploy/$SURVEY_DEPLOYMENT" -c pxeye -- python3 - "$@")
  if [[ -n "${SURVEY_SSH:-}" ]]; then
    # shellcheck disable=SC2086 # SURVEY_SSH is a command line by design
    $SURVEY_SSH "$(printf '%q ' "${command[@]}")" < "$here/$tool"
  else
    "${command[@]}" < "$here/$tool"
  fi
}

keep() {
  # Run a command; print its output and, with --save, keep a copy. A failed command
  # leaves no file behind, so an empty or partial output is never mistaken for a result.
  local subdirectory=$1
  shift
  local tmp status=0
  tmp=$(mktemp)
  "$@" > "$tmp" || status=$?
  cat "$tmp"
  if [[ $status -eq 0 && -n "$save" ]]; then
    : "${SURVEY_DIR:?set SURVEY_DIR to keep outputs}"
    mkdir -p "$(dirname "$SURVEY_DIR/$subdirectory/$save")"
    chmod 600 "$tmp"
    mv "$tmp" "$SURVEY_DIR/$subdirectory/$save"
  else
    rm -f "$tmp"
  fi
  return $status
}

case "$mode" in
  cli) keep cli remote core-cli.py "$@" ;;
  survey) keep survey remote core-survey.py "$@" ;;
  capture)
    : "${SURVEY_DIR:?set SURVEY_DIR to keep the capture}"
    mkdir -p "$SURVEY_DIR"
    name="$SURVEY_DIR/capture-$(date +%Y%m%d-%H%M%S).json"
    status=0
    (umask 077 && remote core-capture.py > "$name") || status=$?
    if [[ $status -eq 2 ]]; then
      mv "$name" "${name%.json}-incomplete.json"
      echo "capture stopped midway; kept ${name%.json}-incomplete.json" >&2
    elif [[ $status -ne 0 ]]; then
      rm -f "$name"
      echo "capture failed (exit $status); nothing kept" >&2
    else
      echo "capture: $name" >&2
    fi
    exit $status
    ;;
  check)
    remote core-cli.py version
    for kind in machines switches power-shelves; do
      echo "$kind: $(remote core-survey.py ids "$kind" | grep -c . || true)"
    done
    ;;
  *)
    echo "unknown mode: $mode (cli, survey, capture, check)" >&2
    exit 2
    ;;
esac
