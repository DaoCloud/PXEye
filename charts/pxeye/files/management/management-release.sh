#!/usr/bin/env bash
set -euo pipefail

usage() {
    printf 'Usage: %s template|upgrade rest|siteagent|temporal|keycloak RELOCATED-PARENT.tgz [--catalog CATALOG.json] [-f PARENT-VALUES.yaml ...] [--native-values CHILD-VALUES.yaml ...]\n' "${0##*/}" >&2
    exit 2
}
(( $# >= 3 )) || usage
action=$1 component=$2 parent=$3
shift 3
case "$action" in template|upgrade) ;; *) usage ;; esac
case "$component" in rest|siteagent|temporal|keycloak) ;; *) usage ;; esac
[[ -f $parent && ! -L $parent ]] || { printf 'Missing or unsafe parent Chart archive\n' >&2; exit 1; }
HELM=${HELM:-helm} YQ=${YQ:-yq} JQ=${JQ:-jq}
here=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)
lib=${PXEYE_ONSITE_LIB:-$here/onsite/lib}
if [[ ! -d $lib && -z ${PXEYE_ONSITE_LIB:-} ]]; then lib=$here/../../../../offline-build/onsite/lib; fi
[[ -r $lib/common.sh ]] || { printf 'Use the shipped tools directory or set PXEYE_ONSITE_LIB to its trusted onsite/lib\n' >&2; exit 1; }
for module in common cluster placement recipe; do source "$lib/$module.sh"; done
JOURNAL_READY=false NODE_NAME=''
umask 077
WORK=$(mktemp -d)
trap 'rm -rf -- "$WORK"' EXIT
catalog=$(dirname -- "$parent")/../../catalog.json
inputs=(); native_inputs=()
while (( $# )); do
    [[ $# -ge 2 && -f $2 ]] || usage
    case "$1" in --catalog) catalog=$2 ;; -f) inputs+=("$2") ;; --native-values) native_inputs+=("$2") ;; *) usage ;; esac
    shift 2
done

[[ -f $catalog ]] || die 'Missing onsite catalog; use the relocated Chart from the import directory or supply --catalog'
cp -- "$catalog" "$WORK/catalog.json"
catalog=$WORK/catalog.json
cp -- "$parent" "$WORK/parent.tgz"
REGISTRY=$("$JQ" -er --arg sha "$(sha "$WORK/parent.tgz")" '
    select(.kind=="pxeye-nico-onsite" and .ready==true) | .registry as $registry |
    select(($registry|type)=="string" and ($registry|length)>0 and ($registry|contains("/")|not)) |
    select(([.charts[]|select(.id=="pxeye")]|map(.sha256))==[$sha]) |
    select((.images|length)>0 and all(.images[]; (.image|startswith($registry+"/")) and (.digest|test("^sha256:[0-9a-f]{64}$")))) | $registry
' "$catalog") || die 'Parent checksum, registry or image inventory does not match the ready onsite catalog'
safe_extract "$WORK/parent.tgz" "$WORK/tree" 268435456
root=$WORK/tree/pxeye
[[ -f $root/Chart.yaml && -f $root/values.yaml ]] || die 'Expected a PXEye parent Chart'
IFS=$'\t' read -r name version < <("$YQ" -o=json '.' "$root/Chart.yaml" | "$JQ" -er --arg key "$component" '
    select(.name=="pxeye") | [.dependencies[]|select((.alias//.name)==$key and .condition==("components."+$key+".enabled"))] |
    select(length==1) | .[0] | select((.name | test("^[a-z0-9]+(-[a-z0-9]+)*$")) and
        (.version | test("^[0-9]+\\.[0-9]+\\.[0-9]+([-+][0-9A-Za-z.+-]+)?$"))) | [.name,.version] | @tsv') || die 'Missing or ambiguous native dependency in Chart.yaml'
shopt -s nullglob
candidates=("$root/charts/$name"-[0-9]*.tgz)
if [[ -d $root/charts/$name ]]; then candidates+=("$root/charts/$name"); fi
(( ${#candidates[@]} == 1 )) || die "Missing or ambiguous vendored child: $name"
child=${candidates[0]}
[[ -d $child || $child == "$root/charts/$name-$version.tgz" ]] || die 'Vendored dependency filename/version mismatch'
"$HELM" show chart "$child" | "$YQ" -o=json '.' | "$JQ" -e --arg name "$name" --arg version "$version" \
    '.name==$name and (.version|tostring)==$version' >/dev/null || die 'Vendored child Chart identity differs from parent dependency'

merge_files() {
    if (( $# == 0 )); then printf '{}\n'; return; fi
    "$YQ" eval-all -o=json '. as $item ireduce ({}; . * $item)' "$@" | "$JQ" -es 'select(length==1 and (.[0]|type)=="object") | .[0]'
}
merge_files "$root/values.yaml" > "$WORK/defaults.json"
merge_files ${inputs[@]+"${inputs[@]}"} > "$WORK/site.json"
merge_files ${native_inputs[@]+"${native_inputs[@]}"} > "$WORK/native.json"
IFS=$'\t' read -r release namespace < <("$JQ" -er --arg key "$component" --slurpfile site "$WORK/site.json" '
    (. * $site[0]).managementReleases[$key] | [.name,.namespace] |
    select(all(.[]; type=="string" and test("^[a-z0-9]([-a-z0-9]*[a-z0-9])?$")) and
           (.[0]|length)<=53 and (.[1]|length)<=63) | @tsv' "$WORK/defaults.json") || die 'Invalid management release or namespace'

verb=install
printf '{}\n' > "$WORK/prior.json"
if [[ $action == upgrade ]]; then
    count=$("$HELM" list --all --namespace "$namespace" --filter "^${release}$" -o json |
        "$JQ" -er --arg release "$release" --arg ns "$namespace" 'select(type=="array" and length<=1 and all(.[]; .name==$release and .namespace==$ns)) | length') || die 'Cannot establish release ownership'
    if [[ $count == 1 ]]; then
        "$HELM" get metadata "$release" --namespace "$namespace" -o json | "$JQ" -e --arg release "$release" --arg ns "$namespace" --arg chart "$name" \
            '.name==$release and .namespace==$ns and .chart==$chart and .status=="deployed"' >/dev/null ||
            die "Existing $namespace/$release is not a deployed native $name release; refusing adoption or migration"
        "$HELM" get values "$release" --namespace "$namespace" -o json | "$JQ" -e '. // {} | select(type=="object")' > "$WORK/prior.json" || die 'Cannot read native release values'
        verb=upgrade
    fi
fi

"$JQ" -e --arg key "$component" 'select((.[$key]|type)=="object") | .[$key] * {global:((.[$key].global // {}) * (.global // {}))}' \
    "$WORK/defaults.json" > "$WORK/pins.json" || die 'Cannot project packaged child values'
"$JQ" -n --arg key "$component" --slurpfile base "$WORK/defaults.json" --slurpfile old "$WORK/prior.json" \
    --slurpfile site "$WORK/site.json" --slurpfile native "$WORK/native.json" '
    ($base[0][$key] * $old[0] * ($site[0][$key] // {})) |
    .global = ((.global // {}) * ($base[0].global // {}) * ($site[0].global // {})) |
    . * $native[0] |
    if $key=="rest" then del(.["nico-rest-db"].waitForPostgres.repository, .["nico-rest-db"].waitForPostgres.tag)
    elif $key=="siteagent" then del(.bootstrap.repository, .bootstrap.tag) else . end
' > "$WORK/merged.json"
image_defaults "$WORK/pins.json" "$WORK/merged.json" "$WORK/values.json"
render=(template "$release" "$child" --namespace "$namespace" --include-crds -f "$WORK/values.json")
if [[ $verb == upgrade ]]; then render+=(--is-upgrade); fi
"$HELM" "${render[@]}" > "$WORK/rendered.yaml"
yaml_documents "$WORK/rendered.yaml" | "$JQ" -e --arg ns "$namespace" '
    any(.[]; .kind=="Deployment" or .kind=="StatefulSet") and all(.[]; (.metadata.namespace // $ns)==$ns and
        (if .kind=="RoleBinding" or .kind=="ClusterRoleBinding" then
             all(.subjects[]?; .kind!="ServiceAccount" or (.namespace // $ns)==$ns) else true end))
' >/dev/null || die 'Native Chart rendered no service workload or targeted an unexpected namespace'
check_images "$WORK/rendered.yaml" "$catalog"
if [[ $action == template ]]; then cat "$WORK/rendered.yaml"; exit 0; fi
args=("$verb" "$release" "$child" --namespace "$namespace" --wait -f "$WORK/values.json")
if [[ $verb == upgrade ]]; then args+=(--reset-values); fi
"$HELM" "${args[@]}"
