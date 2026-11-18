#!/usr/bin/env bash
set -euo pipefail

usage() {
    printf 'Usage: %s template|upgrade rest|siteagent|temporal|keycloak RELOCATED-PARENT.tgz [-f SITE-VALUES.yaml ...]\n' "${0##*/}" >&2
    exit 2
}
(( $# >= 3 )) || usage
action=$1 component=$2 parent=$3
shift 3
case "$action" in template|upgrade) ;; *) usage ;; esac
case "$component" in rest|siteagent|temporal|keycloak) ;; *) usage ;; esac
[[ -f $parent ]] || { printf 'Parent Chart archive not found\n' >&2; exit 1; }
helm_bin=${HELM:-helm} yq_bin=${YQ:-yq} jq_bin=${JQ:-jq}
umask 077
work=$(mktemp -d)
trap 'rm -rf -- "$work"' EXIT
"$helm_bin" show values "$parent" > "$work/defaults.yaml"
inputs=("$work/defaults.yaml")
overrides=()
while (( $# )); do
    [[ $# -ge 2 && $1 == -f && -f $2 ]] || usage
    inputs+=("$2"); overrides+=(-f "$2"); shift 2
done
"$yq_bin" eval-all -o=json '. as $item ireduce ({}; . * $item)' "${inputs[@]}" |
    "$jq_bin" -e --arg key "$component" '
        .managementReleases[$key] as $target |
        {name:$target.name, namespace:$target.namespace, components:(.components | with_entries(.value = {enabled:(.key==$key)}))} |
        select((.components[$key].enabled == true) and
               (.name | type == "string" and length <= 53 and test("^[a-z0-9]([-a-z0-9]*[a-z0-9])?$")) and
               (.namespace | type == "string" and length <= 63 and test("^[a-z0-9]([-a-z0-9]*[a-z0-9])?$")))
    ' > "$work/target.json" || { printf 'Invalid management release or namespace configuration\n' >&2; exit 1; }
release=$("$jq_bin" -r .name "$work/target.json")
namespace=$("$jq_bin" -r .namespace "$work/target.json")
"$jq_bin" '{components}' "$work/target.json" > "$work/only.json"
args=("$action")
if [[ $action == upgrade ]]; then
    owner=$("$helm_bin" list --all --namespace "$namespace" --filter "^${release}$" -o json |
        "$jq_bin" -er --arg name "$release" '[.[] | select(.name==$name) | .chart] |
            if length==0 then "absent" elif length==1 and (.[0] | test("^pxeye-[0-9]")) then "parent" else "other" end')
    if [[ $owner == other ]]; then
        printf 'Existing release %s/%s uses a different Chart; refusing automatic adoption\n' "$namespace" "$release" >&2; exit 1
    elif [[ $owner == parent ]]; then
        "$helm_bin" get values "$release" --namespace "$namespace" -o json |
            "$jq_bin" -e --arg key "$component" '[.components | to_entries[] | select(.value.enabled == true) | .key] == [$key]' >/dev/null ||
            { printf 'Existing release is not dedicated to %s; refusing upgrade\n' "$component" >&2; exit 1; }
    fi
    args+=(--install --wait)
else
    args+=(--include-crds)
fi
"$helm_bin" "${args[@]}" "$release" "$parent" --namespace "$namespace" ${overrides[@]+"${overrides[@]}"} -f "$work/only.json"
