#!/usr/bin/env bash
# Install an existing PXEye/NICo offline delivery. Linux/Bash only; no Python.
set -Eeuo pipefail
umask 077

KIT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)
BIN_DIR="$KIT_DIR/../bin"
for _tool in jq yq caddy; do
    if [[ ! -x $BIN_DIR/$_tool ]]; then
        printf 'Missing bundled tool: %s. Use an exported onsite-tools kit.\n' "$_tool" >&2
        exit 1
    fi
done
JQ="$BIN_DIR/jq"; YQ="$BIN_DIR/yq"; CADDY="$BIN_DIR/caddy"
source "$KIT_DIR/lib/common.sh"
source "$KIT_DIR/lib/relocation.sh"
source "$KIT_DIR/lib/registry.sh"
source "$KIT_DIR/lib/cluster.sh"
source "$KIT_DIR/lib/recipe.sh"
source "$KIT_DIR/lib/helm.sh"

usage() {
    cat <<'HELP'
Usage: install.sh --archive /absolute/path/bundle.tar.gz [--mode kind|k8s]

Install PXEye/NICo into an existing cluster without host Python.
  --archive PATH  Absolute offline archive path (required)
  --mode MODE     kind (default), or k8s using the current kubeconfig context
  -h, --help      Show this help

If Registry discovery is ambiguous, set NICO_REGISTRY_URL=http(s)://host[:port].
Rerun the same command after fixing a failure to resume this installation.
HELP
}

ARCHIVE= MODE=kind
while (($#)); do
    case $1 in
        --archive) (($# >= 2)) || die '--archive needs a path'; ARCHIVE=$2; shift 2 ;;
        --mode) (($# >= 2)) || die '--mode needs kind or k8s'; MODE=$2; shift 2 ;;
        -h|--help) usage; exit 0 ;;
        *) die "Unknown parameter: $1" ;;
    esac
done
[[ -n $ARCHIVE ]] || { usage >&2; exit 2; }
[[ $MODE == kind || $MODE == k8s ]] || die '--mode must be kind or k8s'
[[ $(uname -s) == Linux && $(uname -m) == x86_64 ]] || die 'Use a Linux amd64 fireseed host'
((BASH_VERSINFO[0] >= 4)) || die 'Bash 4+ is required'
for _tool in kubectl curl tar gzip flock sha256sum timeout find sort cmp stat awk sync readlink df; do
    command -v "$_tool" >/dev/null || die "Missing host command: $_tool"
done
tar --version | head -1 | grep -q 'GNU tar' || die 'GNU tar is required'
[[ $ARCHIVE == /* && -f $ARCHIVE && ! -L $ARCHIVE ]] || die 'Use an absolute archive path to a regular file'
ARCHIVE=$(readlink -f -- "$ARCHIVE")
_name=$(basename -- "$ARCHIVE")
_stem=$_name
for _suffix in .tar.gz .tar.xz .tar.bz2 .tgz .tar; do
    if [[ $_stem == *"$_suffix" ]]; then _stem=${_stem%"$_suffix"}; break; fi
done
[[ -n $_stem && $_stem != . && $_stem != .. ]] || die 'Unsafe archive filename'
TARGET="$(dirname -- "$ARCHIVE")/$_stem"
WORK="${TARGET}.onsite"
DEPLOY="$WORK/deployment"
CONFIG="$WORK/install-config.json"
PROGRESS="$WORK/progress.json"
STATE="$DEPLOY/state.json"
NAMESPACE=nico-system; RELEASE=nico
[[ ! -L $TARGET && ! -L $WORK ]] || die 'Extraction or work directory is a symlink'
for _path in "$DEPLOY" "$DEPLOY/private" "$CONFIG" "$STATE" "$PROGRESS"; do
    [[ ! -L $_path ]] || die "Installation state path is a symlink: $_path"
done
mkdir -p "$WORK"
exec 9>"$WORK/.run.lock"
flock -n 9 || die 'Another installation is using this archive'

select_context() {
    local contexts current kinds count
    contexts=$(kubectl config get-contexts -o name) || die 'Cannot read local kubeconfig contexts'
    current=$(kubectl config current-context) || die 'Cannot read the current kubeconfig context'
    if [[ $MODE == k8s ]]; then
        [[ -n $current ]] && printf '%s\n' "$contexts" | grep -Fxq -- "$current" || die 'Select a valid current Kubernetes context with kubectl config use-context'
        CONTEXT=$current
    else
        kinds=$(printf '%s\n' "$contexts" | awk '/^kind-/')
        if [[ -n $current ]] && printf '%s\n' "$kinds" | grep -Fxq -- "$current"; then
            CONTEXT=$current
        else
            count=$(printf '%s\n' "$kinds" | awk 'NF{n++} END{print n+0}')
            [[ $count == 1 ]] || die 'Expected exactly one Kind context; select the intended Kind context before running'
            CONTEXT=$kinds
        fi
    fi
}
select_context
ARCHIVE_ID=$("$JQ" -nc --arg name "$_name" --argjson bytes "$(stat -c %s -- "$ARCHIVE")" \
    --arg modified "$(stat -c %y -- "$ARCHIVE")" '{name:$name,bytes:$bytes,modified:$modified}')
_implementation=$({ find "$KIT_DIR" -type f -name '*.sh' -print0; find "$BIN_DIR" -maxdepth 1 -type f -print0; } | \
    LC_ALL=C sort -z | xargs -0 sha256sum | sed "s|$KIT_DIR/||g; s|$BIN_DIR/|bin/|g" | sha256sum | awk '{print $1}')
IDENTITY=$("$JQ" -nc --argjson archive "$ARCHIVE_ID" --arg mode "$MODE" --arg context "$CONTEXT" --arg implementation "$_implementation" \
    '{installer:"pxeye-onsite-shell-v1",archive:$archive,cluster_mode:$mode,context:$context,implementation:$implementation}')
if [[ -f $PROGRESS ]]; then
    "$JQ" -e --argjson identity "$IDENTITY" '(.identity|del(.implementation))==($identity|del(.implementation))' "$PROGRESS" >/dev/null || \
        die 'Archive, installer format, mode or context changed; resume the original target or use a different archive name. Python-run progress is not adopted.'
    # Tool fixes may resume the same format. Inputs, cluster and frozen Helm
    # intent stay immutable; record each implementation used for this run.
    _previous=$("$JQ" -r '.implementation_history[-1].sha256 // .identity.implementation // empty' "$PROGRESS")
    if [[ $_previous != "$_implementation" ]]; then
        jq_atomic "$PROGRESS" '.implementation_history=((.implementation_history // [{sha256:.identity.implementation,observed_at:.updated_at}]) + [{sha256:$implementation,observed_at:$at}])' \
            --arg implementation "$_implementation" --arg at "$(now)"
        IMPLEMENTATION_UPDATED=true
    fi
else
    jq_atomic "$PROGRESS" '{schema_version:1,identity:$identity,implementation_history:[{sha256:$identity.implementation,observed_at:$at}],status:"pending",stages:{}}' \
        --argjson identity "$IDENTITY" --arg at "$(now)"
fi
JOURNAL_READY=true
trap 'onsite_failure $? $LINENO' ERR
trap 'onsite_failure 130 $LINENO' INT
trap 'onsite_failure 143 $LINENO' TERM
trap 'registry_bridge_stop' EXIT
exec > >(tee -a "$WORK/run.log") 2>&1
printf 'INSTALL_TARGET mode=%s context=%s\n' "$MODE" "$CONTEXT"
if [[ ${IMPLEMENTATION_UPDATED:-false} == true ]]; then
    printf 'INSTALLER_UPDATED; source fingerprint recorded; frozen inputs and Helm intent will be rechecked\n'
fi

unpack_delivery() {
    local temporary free descriptor roots saved
    if [[ -e $TARGET ]]; then
        [[ -f $TARGET/unpack-result.json ]] || die 'Extraction directory exists without a completion marker'
        "$JQ" -e --argjson archive "$ARCHIVE_ID" '.archive==$archive' "$TARGET/unpack-result.json" >/dev/null || die 'Extraction belongs to different archive metadata'
        saved=$("$JQ" -r '.root' "$TARGET/unpack-result.json")
        [[ $saved != */* && -n $saved && $saved != . && $saved != .. ]] || die 'Invalid completed bundle root'
        BUNDLE="$TARGET/$saved"
        printf 'REUSE_EXTRACTION %s\n' "$BUNDLE"
    else
        temporary=$(mktemp -d "$(dirname -- "$TARGET")/.${_stem}.unpacking.XXXXXX")
        free=$(df -Pk -- "$temporary" | awk 'NR==2 {printf "%.0f", $4*1024-1073741824}')
        ((free > $(stat -c %s -- "$ARCHIVE"))) || die 'Insufficient space to unpack'
        safe_extract "$ARCHIVE" "$temporary" "$free"
        roots=$(find "$temporary" -mindepth 1 -maxdepth 1 -printf '%f\n')
        [[ $(printf '%s\n' "$roots" | wc -l) == 1 ]] || die 'Expected exactly one archive root'
        BUNDLE="$temporary/$roots"
        [[ -f $BUNDLE/bundle.json ]] || die 'Expected one bundle descriptor'
        "$JQ" -e '.kind=="pxeye-nico-helm"' "$BUNDLE/bundle.json" >/dev/null || die 'Use a Helm/relok8s delivery'
        verify_bundle
        jq_atomic "$temporary/unpack-result.json" '{archive:$archive,root:$root}' --argjson archive "$ARCHIVE_ID" --arg root "$roots"
        mv -- "$temporary" "$TARGET"
        BUNDLE="$TARGET/$roots"
        # Moving the extraction changes ctime; refresh only its verified stamps.
        jq_atomic "$WORK/input-verification.json" '.stats_sha256=$stats' --arg stats "$(find "$BUNDLE" -type f -printf '%P %s %T@ %C@ %i\0' | LC_ALL=C sort -z | sha256sum | awk '{print $1}')"
        printf 'UNPACK_COMPLETE %s\n' "$BUNDLE"
    fi
    HELM="$BUNDLE/tools/helm"; RELOK="$BUNDLE/tools/relok8s"
    [[ -x $HELM && -x $RELOK ]] || die 'Bundle Helm/relok8s are missing or not executable'
}

resolve_site() {
    local fingerprint lock_id
    mkdir -p "$DEPLOY/private"
    if [[ -f $CONFIG ]]; then
        "$JQ" -e --arg mode "$MODE" --arg context "$CONTEXT" --arg bundle "$BUNDLE" --arg directory "$DEPLOY" \
            '.schema_version==3 and .cluster_mode==$mode and .context==$context and .namespace=="nico-system" and .bundle==$bundle and .work_directory==$directory' "$CONFIG" >/dev/null || die 'Generated configuration targets another installation'
        REGISTRY_URL=$("$JQ" -r '.registry.url' "$CONFIG")
        REGISTRY=${REGISTRY_URL#*://}
        printf 'REUSE_INSTALL_CONFIG %s\n' "$CONFIG"
    else
        detect_registry
        jq_atomic "$CONFIG" '{schema_version:3,cluster_mode:$mode,context:$context,namespace:"nico-system",site_name:"PXEye",bundle:$bundle,work_directory:$directory,registry:{url:$registry,repository_prefix:"nico-offline",ca_file:null,skip_tls_verify:true,docker_config_directory:null,discovery:$discovery}}' \
            --arg mode "$MODE" --arg context "$CONTEXT" --arg bundle "$BUNDLE" --arg directory "$DEPLOY" --arg registry "$REGISTRY_URL" \
            --argjson discovery "$(cat "$WORK/registry-discovery.json")"
        printf 'INSTALL_CONFIG_RESOLVED %s\n' "$CONFIG"
    fi
    SCOPE="nico-offline/bundle-$(sha "$BUNDLE/manifests/file-inventory.json" | cut -c1-20)"
    fingerprint=$("$JQ" -cS . "$CONFIG" | sha256sum | awk '{print $1}')
    if [[ -f $STATE ]]; then
        "$JQ" -e --arg fingerprint "$fingerprint" --arg inventory "$(sha "$BUNDLE/manifests/file-inventory.json")" \
            '.config_sha256==$fingerprint and .bundle_inventory_sha256==$inventory' "$STATE" >/dev/null || die 'Generated config or bundle changed'
    else
        jq_atomic "$STATE" '{config_sha256:$fingerprint,bundle_inventory_sha256:$inventory,steps:{}}' \
            --arg fingerprint "$fingerprint" --arg inventory "$(sha "$BUNDLE/manifests/file-inventory.json")"
    fi
    lock_id=$(printf '%s' "$CONTEXT/$NAMESPACE/$RELEASE" | sha256sum | cut -c1-24)
    exec 8>"${TMPDIR:-/tmp}/pxeye-onsite-$lock_id.lock"
    flock -n 8 || die 'Another installation is using this cluster/namespace/release'
    {
        printf '# Generated inspection helper; not installer input.\n'
        printf 'export CONTEXT=%q\n' "$CONTEXT"
        printf 'export NICO_NAMESPACE=%q\n' "$NAMESPACE"
        printf 'export NICO_RELEASE=%q\n' "$RELEASE"
        printf 'export PXEYE_RELEASE=%q\n' "$NAMESPACE-pxeye"
        printf 'export BUNDLE=%q\n' "$BUNDLE"
        printf 'export WORK=%q\n' "$DEPLOY"
        printf 'export REGISTRY_URL=%q\n' "$REGISTRY_URL"
    } > "$WORK/environment.sh"
    printf 'ENVIRONMENT_READY %s\n' "$WORK/environment.sh"
}

print_access() {
    printf 'PXEYE_ACCESS: run on the fireseed host and keep the terminal open:\n'
    printf '%q ' kubectl --context "$CONTEXT" -n "$NAMESPACE" port-forward --address 0.0.0.0 "service/$NAMESPACE-pxeye" 31808:80
    printf '\nPXEYE_LOCAL_URL: http://127.0.0.1:31808/\n'
    if [[ -n ${SSH_CONNECTION:-} ]]; then
        local client client_port host host_port
        read -r client client_port host host_port <<< "$SSH_CONNECTION"
        if [[ $host =~ ^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+$ && $host != 127.* && $host != 0.0.0.0 ]]; then
            printf 'PXEYE_BROWSER_URL: http://%s:31808/\n' "$host"
        fi
    fi
    printf 'PXEYE_LOGIN: retrieve the generated password in your terminal:\n'
    printf '%q ' kubectl --context "$CONTEXT" -n "$NAMESPACE" get secret "$NAMESPACE-pxeye" -o 'jsonpath={.data.bootstrap-password}'
    printf '| base64 -d\n'
}

onsite_main() {
    stage 01-unpack 'Unpack delivery and verify its embedded inventory' unpack_delivery
    stage 02-site 'Resolve the Registry and fixed installation identity' resolve_site
    stage 03-preflight 'Check bundle, target cluster and tools' cluster_preflight
    stage 04-import 'Import images and publish Helm OCI Charts' import_bundle
    stage 05-recipe 'Freeze and validate the installation recipe' prepare_recipe
    stage 06-pxeye 'Install or verify PXEye' bootstrap_pxeye
    while IFS= read -r _phase; do
        stage "07-install-$_phase" "Install or verify $_phase" install_phase "$_phase"
    done < <("$JQ" -r '.phases[].id' "$DEPLOY/recipe/deployment.json")
    stage 08-pxeye-core "Verify PXEye's in-cluster Core connection" check_pxeye_core
    jq_atomic "$PROGRESS" '.status="completed" | .current_stage=null | del(.error) | .updated_at=$at' --arg at "$(now)"
    printf 'ONSITE_COMPLETE %s ; Helm readiness passed; physical provisioning remains disabled until site boot settings are configured\n' "$WORK"
    print_access
}

if [[ ${BASH_SOURCE[0]} == "$0" ]]; then onsite_main; fi
