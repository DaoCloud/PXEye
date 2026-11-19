#!/usr/bin/env bash
# Frozen Helm intent, resource ownership, ordered phases and bounded health checks.

phase_arguments() {
    local root=$1 phase=$2 value
    "$JQ" -e '
        def relative: type == "string" and length > 0 and (test("(^/|(^|/)\\.\\.?(/|$)|[\\\\\\t\\r\\n])") | not);
        type == "object" and (.chart | relative) and
        (.values | type == "array" and length > 0 and all(.[]; relative))
    ' <<< "$phase" >/dev/null || die 'Invalid frozen Helm Chart or values paths'
    PHASE_ID=$("$JQ" -r '.id' <<< "$phase")
    PHASE_RELEASE=$("$JQ" -r '.release' <<< "$phase")
    PHASE_TIMEOUT=$("$JQ" -r '.timeout_seconds // 900' <<< "$phase")
    [[ "$PHASE_ID" =~ ^[a-z][a-z0-9-]*$ && "$PHASE_RELEASE" =~ ^[a-z][a-z0-9-]*$ ]] || die 'Invalid frozen Helm phase identity'
    [[ "$PHASE_TIMEOUT" =~ ^[1-9][0-9]*$ ]] || die 'Invalid Helm phase timeout'
    PHASE_CHART="$root/$("$JQ" -r '.chart' <<< "$phase")"
    [[ -f "$PHASE_CHART" && ! -L "$PHASE_CHART" ]] || die 'Frozen Helm Chart is missing or unsafe'
    PHASE_VALUES=()
    while IFS= read -r value; do
        [[ -f "$root/$value" && ! -L "$root/$value" ]] || die 'Frozen Helm values are missing or unsafe'
        PHASE_VALUES+=(-f "$root/$value")
    done < <("$JQ" -r '.values[]' <<< "$phase")
}

render_phase() {
    local root=$1 phase=$2 label=$3
    phase_arguments "$root" "$phase"
    hrun "$label" template "$PHASE_RELEASE" "$PHASE_CHART" -n "$NAMESPACE" "${PHASE_VALUES[@]}" || die "Cannot render frozen Helm phase $PHASE_ID"
    RENDERED=$RESULT
}

check_ownership() {
    local root=$1 phase=$2 objects obj kind name namespace cluster exists=0 actual hooks crd
    render_phase "$root" "$phase" "$("$JQ" -r '.id' <<< "$phase")-ownership-render"
    objects="$RENDERED.json"
    yaml_documents "$RENDERED" > "$objects" || die 'Cannot parse rendered resources for ownership checks'
    if namespace_exists; then exists=1; fi
    while IFS= read -r obj; do
        kind=$("$JQ" -r '.kind // empty' <<< "$obj")
        name=$("$JQ" -r '.metadata.name // empty' <<< "$obj")
        [[ "$kind" != Namespace && -n "$name" ]] || continue
        namespace=$("$JQ" -r '.metadata.namespace // empty' <<< "$obj")
        cluster=0
        case "$kind" in
            ClusterRole|ClusterRoleBinding|CustomResourceDefinition|ClusterIssuer|MutatingWebhookConfiguration|ValidatingWebhookConfiguration) cluster=1 ;;
        esac
        [[ "$cluster" == 1 || -z "$namespace" || "$namespace" == "$NAMESPACE" ]] || die 'Chart targets another namespace'
        [[ "$cluster" == 1 || "$exists" == 1 ]] || continue
        crd=
        case "$kind" in
            Certificate) crd=certificates.cert-manager.io ;;
            Issuer) crd=issuers.cert-manager.io ;;
            ClusterIssuer) crd=clusterissuers.cert-manager.io ;;
        esac
        # A fresh recipe includes resources for later phases before this run
        # installs cert-manager. An explicitly absent CRD has no instances to
        # inspect; after registration normal ownership checks apply.
        if [[ -n "$crd" && -f $DEPLOY/private/cert-manager-inventory.json ]] &&
            "$JQ" -e '.cert_manager_mode == "install"' "$STATE" >/dev/null &&
            ! state_has installed-cert-manager &&
            "$JQ" -e --arg crd "$crd" '.crds[$crd].present == false' "$DEPLOY/private/cert-manager-inventory.json" >/dev/null; then
            printf 'AWAIT_CERT_MANAGER_REGISTRATION %s/%s; %s is absent\n' "$kind" "$name" "$crd"
            continue
        fi
        if [[ "$cluster" == 1 ]]; then
            kctl "$PHASE_ID-owner-$kind-$name" get "$kind" "$name" --ignore-not-found -o json || die "Cannot inspect $kind/$name ownership"
        else
            kctl "$PHASE_ID-owner-$kind-$name" get "$kind" "$name" --ignore-not-found -o json -n "$NAMESPACE" || die "Cannot inspect $kind/$name ownership"
        fi
        [[ -s "$RESULT" ]] || continue
        actual=$RESULT
        if "$JQ" -e '.metadata.annotations["helm.sh/hook"] != null' <<< "$obj" >/dev/null; then
            "$JQ" -e --arg release "$PHASE_RELEASE" '(.metadata.annotations["meta.helm.sh/release-name"] // $release) == $release' \
                "$actual" >/dev/null || die "Hook is owned by another release: $kind/$name"
            hrun "$PHASE_ID-existing-hooks" get hooks "$PHASE_RELEASE" -n "$NAMESPACE" || die 'Cannot establish existing Helm hook ownership'
            hooks="$RESULT.json"
            yaml_documents "$RESULT" > "$hooks" || die 'Cannot read existing Helm hooks'
            "$JQ" -e --arg kind "$kind" --arg name "$name" 'any(.[]; .kind == $kind and .metadata.name == $name)' \
                "$hooks" >/dev/null || die "Existing hook is absent from the selected Helm release: $kind/$name"
        else
            "$JQ" -e --arg release "$PHASE_RELEASE" --arg ns "$NAMESPACE" \
                '.metadata.annotations["meta.helm.sh/release-name"] == $release and .metadata.annotations["meta.helm.sh/release-namespace"] == $ns' \
                "$actual" >/dev/null || die "Existing object belongs to another owner: $kind/$name"
        fi
    done < <("$JQ" -c '.[]' "$objects")
}

check_health() {
    local root=$1 phase=$2 obj kind name objects
    render_phase "$root" "$phase" "$("$JQ" -r '.id' <<< "$phase")-health-render"
    objects="$RENDERED.json"
    yaml_documents "$RENDERED" > "$objects" || die 'Cannot parse rendered health checks'
    while IFS= read -r obj; do
        kind=$("$JQ" -r '.kind // empty' <<< "$obj")
        name=$("$JQ" -r '.metadata.name // empty' <<< "$obj")
        case "$kind" in
            Deployment|StatefulSet|DaemonSet)
                COMMAND_TIMEOUT=$((PHASE_TIMEOUT + 60)) kctl "$PHASE_ID-ready-$name" -n "$NAMESPACE" rollout status "${kind,,}/$name" --timeout "${PHASE_TIMEOUT}s" || die "Workload failed readiness: $kind/$name" ;;
            Certificate)
                COMMAND_TIMEOUT=$((PHASE_TIMEOUT + 60)) kctl "$PHASE_ID-cert-$name" -n "$NAMESPACE" wait --for=condition=Ready "certificate/$name" --timeout "${PHASE_TIMEOUT}s" || die "Certificate is not Ready: $name" ;;
        esac
    done < <("$JQ" -c '.[] | select(.metadata.annotations["helm.sh/hook"] == null)' "$objects")
}

install_intent() {
    local root=$1 phase=$2 value values='{}' digest chart
    phase_arguments "$root" "$phase"
    chart=$("$JQ" -r '.chart' <<< "$phase")
    while IFS= read -r value; do
        digest=$(sha "$root/$value")
        values=$("$JQ" -cn --argjson values "$values" --arg value "$value" --arg digest "$digest" '$values + {($value):$digest}')
    done < <("$JQ" -r '.values[]' <<< "$phase")
    "$JQ" -cn --arg release "$("$JQ" -r '.release' <<< "$phase")" --arg chart "$(sha "$root/$chart")" --argjson values "$values" \
        '{release:$release, chart_sha256:$chart, values:$values}'
}

snapshot_phase() {
    local phase=$1 release=$2 directory="$DEPLOY/private/before-$1" helm_exit=0
    [[ ! -e "$directory/complete.json" ]] || die 'A completed baseline snapshot already exists; inspect it before replacing it'
    mkdir -p "$directory"
    chmod 700 "$directory"
    if namespace_exists; then
        kctl "$phase-pvc-before" -n "$NAMESPACE" get pvc -o json || die 'Cannot snapshot existing PVCs'
        cp "$RESULT" "$directory/pvcs.json"
    else
        printf '{"items":[]}\n' > "$directory/pvcs.json"
    fi
    if hrun "$phase-helm-before" get all "$release" -n "$NAMESPACE"; then
        helm_exit=0
    else
        helm_exit=$?
        grep -qi 'release: not found' "${RESULT%.stdout}.stderr" || die 'Cannot capture Helm release state; inspect before install'
    fi
    cp "$RESULT" "$directory/helm.txt"
    "$JQ" -n --argjson status "$helm_exit" '{metadata_only:true, helm_exit_code:$status}' > "$directory/complete.json.tmp"
    mv "$directory/complete.json.tmp" "$directory/complete.json"
    chmod 600 "$directory/"*
}

check_pvcs() {
    local phase=$1 before="$DEPLOY/private/before-$1/pvcs.json"
    [[ -f "$before" ]] || die "Missing original PVC baseline for $phase"
    kctl "$phase-pvc-after" -n "$NAMESPACE" get pvc -o json || die 'Cannot inspect PVCs after installation'
    "$JQ" -e --slurpfile previous "$before" '.items as $current |
        all($previous[0].items[]; . as $old | any($current[];
            .metadata.name == $old.metadata.name and .metadata.uid == $old.metadata.uid and
            (.spec.volumeName // null) == ($old.spec.volumeName // null)))' "$RESULT" >/dev/null || die 'Existing PVC identity/binding changed; stop and inspect'
}

release_values_match() {
    local root=$1 phase=$2 current value wanted="$DEPLOY/private/verify-values.yaml"
    phase_arguments "$root" "$phase"
    hrun "$PHASE_ID-resume-values" get values "$PHASE_RELEASE" -n "$NAMESPACE" -o json || die 'Cannot read deployed Helm values'
    current=$RESULT
    printf '{}\n' > "$wanted" || die 'Cannot prepare frozen Helm values'
    while IFS= read -r value; do
        merge_yaml "$wanted" "$root/$value" "$wanted.tmp" || die 'Cannot merge frozen Helm values'
        mv "$wanted.tmp" "$wanted" || die 'Cannot save frozen Helm values'
    done < <("$JQ" -r '.values[]' <<< "$phase")
    "$YQ" -o=json '.' "$wanted" > "$wanted.json" || die 'Cannot read frozen Helm values'
    "$JQ" -e -s '(.[0] // {}) == .[1]' "$current" "$wanted.json" >/dev/null
}

verify_release_intent() {
    local root=$1 phase=$2 metadata releases
    release_values_match "$root" "$phase" || die 'Deployed Helm values differ from frozen intent'
    hrun "$PHASE_ID-resume-chart" show chart "$PHASE_CHART" || die 'Cannot read frozen Chart metadata'
    metadata="$RESULT.json"
    "$YQ" -o=json '.' "$RESULT" > "$metadata" || die 'Cannot parse frozen Chart metadata'
    hrun "$PHASE_ID-resume-releases" list --all -n "$NAMESPACE" -o json || die 'Cannot inspect deployed Chart identity'
    releases=$RESULT
    "$JQ" -e --arg release "$PHASE_RELEASE" --slurpfile chart "$metadata" \
        '[.[] | select(.name == $release)] as $matches | ($matches|length) == 1 and
        $matches[0].chart == ($chart[0].name + "-" + ($chart[0].version|tostring))' "$releases" >/dev/null || die 'Deployed Chart differs from frozen intent'
}

verify_deployed() {
    verify_release_intent "$1" "$2"
    check_health "$1" "$2"
}

verify_completed_predecessor() {
    local root=$1 key=$2 release=$3 previous previous_key intent
    # A manual rollback can restore the preceding completed phase after an
    # interrupted upgrade. Accept only this run's exact frozen predecessor;
    # never adopt an arbitrary deployed release or mark the new phase complete.
    previous=$("$JQ" -ce --arg key "$key" --arg release "$release" '
        .phases as $phases | ($phases | map(.id) | index($key)) as $index |
        [$phases[:$index][] | select(.release == $release)] | last |
        if . == null then error("No preceding phase for this release") else . end
    ' "$root/deployment.json") || die 'Deployed release does not match an earlier phase of this installation'
    previous_key=$("$JQ" -r '.id' <<< "$previous")
    state_has "installed-$previous_key" || die 'Preceding Helm phase was not completed by this installation'
    [[ -f $DEPLOY/private/before-$previous_key/complete.json ]] || die 'Missing original snapshot for the completed predecessor'
    intent=$(install_intent "$root" "$previous")
    "$JQ" -e --arg key "$previous_key" --argjson intent "$intent" '.install_intents[$key] == $intent' "$STATE" >/dev/null ||
        die 'Completed predecessor intent differs from the frozen recipe'
    check_ownership "$root" "$previous"
    check_pvcs "$previous_key"
    verify_deployed "$root" "$previous"
    printf 'RESUME_AFTER_ROLLBACK %s; verified completed predecessor %s\n' "$key" "$previous_key"
}

verify_later_failed_phase() {
    local root=$1 key=$2 release=$3 latest latest_key intent
    # Ordered phases upgrade the same parent release. A later failed upgrade
    # must not make us replay or downgrade an earlier completed phase.
    latest=$("$JQ" -ce --arg key "$key" --arg release "$release" --slurpfile state "$STATE" '
        [.phases[] | select(.release == $release)] as $phases |
        [$phases[] | select($state[0].install_intents[.id] != null)] | last as $latest |
        ($phases | map(.id)) as $ids |
        ($ids | index($key)) as $completed |
        ($ids | index($latest.id)) as $started |
        if $latest != null and ($completed | type) == "number" and ($started | type) == "number" and
            $started > $completed and $state[0].steps["installed-" + $latest.id] == null
        then $latest else error("No later unfinished phase explains this failed release") end
    ' "$root/deployment.json") || die 'Failed parent release does not match a later phase recorded by this installation'
    latest_key=$("$JQ" -r '.id' <<< "$latest")
    [[ -f $DEPLOY/private/before-$latest_key/complete.json ]] || die 'Missing original snapshot for the later failed phase'
    intent=$(install_intent "$root" "$latest")
    "$JQ" -e --arg key "$latest_key" --argjson intent "$intent" '.install_intents[$key] == $intent' "$STATE" >/dev/null ||
        die 'Later failed phase intent differs from the frozen recipe'
    check_ownership "$root" "$latest"
    check_pvcs "$latest_key"
    verify_release_intent "$root" "$latest"
    printf 'PRESERVE_COMPLETED_PHASE %s; parent release matches later failed phase %s\n' "$key" "$latest_key"
}

recover_cert_manager_install() {
    local root="$DEPLOY/recipe" phase intent release status
    # This path runs during preflight, before namespace resource checks. It
    # must establish this run's completed Helm intent without re-entering
    # preflight or treating a newly appeared shared controller as ours.
    "$JQ" -e '.install_intents["cert-manager"] | type == "object"' "$STATE" >/dev/null ||
        die 'cert-manager appeared after this run chose to install it; no recorded install intent permits recovery'
    [[ -f "$DEPLOY/private/before-cert-manager/complete.json" ]] || die 'Missing original cert-manager installation snapshot; stop before recovery'
    validate_recipe
    phase=$("$JQ" -ce '[.phases[] | select(.id == "cert-manager")] |
        if length == 1 then .[0] else error("Missing or duplicate cert-manager phase") end' "$root/deployment.json") ||
        die 'Cannot recover cert-manager without its frozen installation phase'
    release=$("$JQ" -r '.release' <<< "$phase")
    [[ "$release" == "$RELEASE" ]] || die 'Frozen cert-manager phase belongs to another Helm release'
    intent=$(install_intent "$root" "$phase")
    "$JQ" -e --argjson intent "$intent" '.install_intents["cert-manager"] == $intent' "$STATE" >/dev/null ||
        die 'cert-manager installation intent differs from the frozen recipe; stop rather than adopting it'
    hrun cert-manager-recovery-status status "$release" -n "$NAMESPACE" -o json || die 'Cannot establish the interrupted cert-manager Helm release'
    status=$("$JQ" -r '.info.status' "$RESULT")
    [[ "$status" == deployed || "$status" == failed ]] || die 'Interrupted cert-manager Helm release is pending or requires operator review'
    check_ownership "$root" "$phase"
    check_pvcs cert-manager
    verify_release_intent "$root" "$phase"
    if [[ "$status" == failed ]]; then
        # A failed Helm operation can leave healthy CRDs and unready Pods.
        # Permit only this run's unchanged intent through preflight so the
        # normal ordered phase retries it; do not mark it installed.
        printf 'RETRY_OWN_FAILED_CERT_MANAGER; frozen intent and ownership verified\n'
        return
    fi
    check_health "$root" "$phase"
    state_mark installed-cert-manager "$("$JQ" -cn --arg release "$release" --arg at "$(date -u +%FT%TZ)" '{release:$release,at:$at,recovered:true}')"
    printf 'RECOVERED_INSTALLED cert-manager\n'
}

install_phase() {
    local key=$1 root="$DEPLOY/recipe" phase status intent before release previous
    cluster_preflight
    validate_recipe
    phase=$("$JQ" -c --arg key "$key" '[.phases[] | select(.id == $key)] | if length == 1 then .[0] else error("Unknown or duplicate phase") end' \
        "$root/deployment.json") || die "Unknown frozen Helm phase: $key"
    phase_arguments "$root" "$phase"
    release=$PHASE_RELEASE
    if state_has "installed-$key"; then
        hrun "$key-status" status "$release" -n "$NAMESPACE" -o json || die "Previously completed Helm phase is unavailable: $key"
        status=$("$JQ" -r '.info.status' "$RESULT")
        case "$status" in
            deployed) ;;
            failed) verify_later_failed_phase "$root" "$key" "$release" ;;
            *) die "Completed phase parent release is pending or requires operator review: $key ($status)" ;;
        esac
        check_pvcs "$key"
        check_health "$root" "$phase"
        printf 'ALREADY_INSTALLED %s\n' "$key"
        return
    fi
    previous=$("$JQ" -c --arg key "$key" '[.phases[] | .id] | .[0:index($key)]' "$root/deployment.json")
    "$JQ" -e --argjson previous "$previous" '.steps as $steps | all($previous[]; $steps["installed-" + .] != null)' \
        "$STATE" >/dev/null || die 'Run previous frozen Helm phases first'
    check_ownership "$root" "$phase"
    intent=$(install_intent "$root" "$phase")
    before="$DEPLOY/private/before-$key/complete.json"
    if [[ -f "$before" ]]; then
        check_pvcs "$key"
        if hrun "$key-resume-status" status "$release" -n "$NAMESPACE" -o json; then
            status=$("$JQ" -r '.info.status' "$RESULT")
        else
            grep -qi 'release: not found' "${RESULT%.stdout}.stderr" || die 'Cannot establish Helm state; stop before retry'
            status=not-found
        fi
        case "$status" in
            deployed)
                "$JQ" -e --arg key "$key" --argjson wanted "$intent" '.install_intents[$key] == $wanted' "$STATE" >/dev/null || die 'No matching install intent; inspect deployed release before continuing'
                if release_values_match "$root" "$phase"; then
                    verify_deployed "$root" "$phase"
                    state_mark "installed-$key" "$("$JQ" -cn --arg release "$release" --arg at "$(date -u +%FT%TZ)" '{release:$release, at:$at, recovered:true}')"
                    printf 'RECOVERED_INSTALLED %s\n' "$key"
                    return
                fi
                verify_completed_predecessor "$root" "$key" "$release" ;;
            failed|not-found) printf 'RESUME_FAILED_PHASE %s %s\n' "$key" "$status" ;;
            *) die "Helm is pending or requires operator review: $status" ;;
        esac
    else
        snapshot_phase "$key" "$release"
    fi
    jq_atomic "$STATE" '.install_intents[$key] = $intent' --arg key "$key" --argjson intent "$intent"
    phase_arguments "$root" "$phase"
    COMMAND_TIMEOUT=$((PHASE_TIMEOUT + 60)) hrun "$key-install" upgrade --install "$release" "$PHASE_CHART" -n "$NAMESPACE" --create-namespace \
        --wait --wait-for-jobs --timeout "${PHASE_TIMEOUT}s" "${PHASE_VALUES[@]}" || die "Helm phase failed: $key; inspect logs before resuming"
    check_pvcs "$key"
    check_health "$root" "$phase"
    state_mark "installed-$key" "$("$JQ" -cn --arg release "$release" --arg at "$(date -u +%FT%TZ)" '{release:$release, at:$at}')"
    printf 'HELM_PHASE_COMPLETE %s\n' "$key"
}

check_pxeye_node_port() {
    local release=$1
    kctl pxeye-nodeport-check get services -A -o json || die 'Cannot inspect NodePort allocations'
    "$JQ" -e --arg ns "$NAMESPACE" --arg release "$release" 'all(.items[];
        (.metadata.namespace == $ns and .metadata.name == $release) or all(.spec.ports[]?; .nodePort != 31808))' "$RESULT" >/dev/null || die 'PXEye NodePort 31808 is already used by another Service; resolve the conflict before retrying'
    printf 'PXEYE_NODEPORT_UNALLOCATED_IN_CLUSTER 31808\n'
}

bootstrap_pxeye() {
    local directory="$DEPLOY/bootstrap" chart record phase values release="$NAMESPACE-pxeye" intent status
    cluster_preflight
    "$JQ" -e '.ready == true' "$DEPLOY/catalog.json" >/dev/null || die 'Import bundle first'
    record=$("$JQ" -c '[.charts[] | select(.id == "pxeye")] | if length == 1 then .[0] else error("Missing PXEye Chart") end' "$DEPLOY/catalog.json") || die 'Import bundle first'
    mkdir -p "$directory"
    pull_chart "$record" "$directory"
    chart=$PULLED_CHART
    if [[ -n $NODE_NAME ]]; then
        if [[ -f $directory/chart.tgz ]]; then
            "$JQ" -e --arg source "$(sha "$chart")" --arg derived "$(sha "$directory/chart.tgz")" --argjson selector "$NODE_SELECTOR" \
                '.source==$source and .derived==$derived and .node_selector==$selector' "$directory/placement.json" >/dev/null || die 'Frozen PXEye placement Chart changed'
        else
            derive_recipe_chart "$chart" "$directory/chart.tgz" "$directory/derived"
            jq_atomic "$directory/placement.json" '{source:$source,derived:$derived,node_selector:$selector}' \
                --arg source "$(sha "$chart")" --arg derived "$(sha "$directory/chart.tgz")" --argjson selector "$NODE_SELECTOR"
        fi
        chart=$directory/chart.tgz
    fi
    [[ "$chart" == "$DEPLOY/"* ]] || die 'Bootstrap Chart must remain inside this deployment directory'
    values="$directory/values.yaml"
    "$JQ" -n --arg release "$RELEASE" --arg ns "$NAMESPACE" --arg site "$("$JQ" -r '.site_name' "$CONFIG")" --argjson fresh "${NEW_SITE:-false}" --arg input "${SITE_CREDENTIALS_SECRET:-}" '{
        siteCredentials:{newSite:$fresh,existingSecret:$input},
        nico:{enabled:true, allowClusterResources:true}, service:{type:"NodePort",nodePort:31808},
        components:{pxeye:{enabled:true},certManager:{enabled:false},platform:{enabled:false},vaultBootstrap:{enabled:false},core:{enabled:false},materials:{enabled:false}},
        siteBootstrap:{enabled:true,siteName:$site,coreUrl:("https://"+$release+"-nico-api."+$ns+".svc.cluster.local:1079"),namespace:$ns,
          clientSecret:($release+"-nico-admin-client"),clientCertKey:"tls.crt",clientPrivateKey:"tls.key",caSecret:($release+"-nico-site-ca"),
          caKey:"tls.crt",siteInitializerSecret:($release+"-nico-site-initializer-client"),
          pxeInternalUrl:("http://"+$release+"-nico-pxe."+$ns+".svc:8080")}}
    ' | "$YQ" -P '.' > "$values.tmp" || die 'Cannot generate deterministic PXEye bootstrap values'
    if [[ -n $NODE_NAME ]]; then
        "$YQ" -o=json '.' "$values.tmp" > "$directory/values.json"
        placement_values "$directory/values.json" "$directory/placed.json"
        "$YQ" -P -p=json -o=yaml '.' "$directory/placed.json" > "$values.tmp"
    fi
    mv "$values.tmp" "$values"
    chmod 600 "$values"
    [[ "$release" != "$RELEASE" ]] || die 'PXEye and Core parent releases must differ'
    check_pxeye_node_port "$release"
    phase=$("$JQ" -cn --arg release "$release" --arg chart "${chart#"$DEPLOY/"}" --arg values "${values#"$DEPLOY/"}" \
        '{id:"pxeye",release:$release,chart:$chart,values:[$values]}')
    render_phase "$DEPLOY" "$phase" pxeye-render
    check_images "$RENDERED" "$DEPLOY/catalog.json"
    check_ownership "$DEPLOY" "$phase"
    if state_has bootstrapped-pxeye; then
        hrun pxeye-status status "$release" -n "$NAMESPACE" -o json || die 'PXEye release is unavailable'
        "$JQ" -e '.info.status == "deployed"' "$RESULT" >/dev/null || die 'PXEye release is no longer deployed'
        check_health "$DEPLOY" "$phase"
        printf 'ALREADY_INSTALLED pxeye\n'
        return
    fi
    intent=$(install_intent "$DEPLOY" "$phase")
    if hrun pxeye-resume-status status "$release" -n "$NAMESPACE" -o json; then
        status=$("$JQ" -r '.info.status' "$RESULT")
        [[ "$status" == deployed || "$status" == failed ]] || die 'PXEye Helm operation is pending; inspect before retry'
        if [[ "$status" == deployed ]] && "$JQ" -e --argjson intent "$intent" '.pxeye_install_intent == $intent' "$STATE" >/dev/null; then
            verify_deployed "$DEPLOY" "$phase"
            state_mark bootstrapped-pxeye "$("$JQ" -cn --arg release "$release" --arg at "$(date -u +%FT%TZ)" '{release:$release,at:$at,recovered:true}')"
            printf 'RECOVERED_INSTALLED pxeye\n'
            return
        fi
    else
        grep -qi 'release: not found' "${RESULT%.stdout}.stderr" || die 'Cannot establish PXEye release state'
    fi
    jq_atomic "$STATE" '.pxeye_install_intent = $intent' --argjson intent "$intent"
    COMMAND_TIMEOUT=960 hrun pxeye-bootstrap upgrade --install "$release" "$chart" -n "$NAMESPACE" --create-namespace --wait --timeout 900s -f "$values" || die 'PXEye bootstrap failed; inspect Helm state before resuming'
    state_mark bootstrapped-pxeye "$("$JQ" -cn --arg release "$release" --arg at "$(date -u +%FT%TZ)" '{release:$release,at:$at}')"
    printf 'PXEYE_HELM_READY; existing non-Helm PXEye is never automatically adopted\n'
}

check_pxeye_core() {
    local release="$NAMESPACE-pxeye" deadline=$((SECONDS + 300))
    local program='import json, sys; from urllib.request import urlopen; state = json.load(urlopen("http://127.0.0.1:8080/healthz", timeout=5)); sys.exit(0 if state.get("core", {}).get("ready") else 1)'
    while ((SECONDS < deadline)); do
        # Python runs inside the existing PXEye image; the fireseed host does
        # not need a Python interpreter or any Python packages.
        if run pxeye-core-connection timeout 30s kubectl --context "$CONTEXT" -n "$NAMESPACE" exec "deployment/$release" -- python3 -c "$program"; then
            if [[ ${NEW_SITE:-false} == true ]]; then
                printf 'SITE_CREDENTIALS_NEW_SITE; generating missing BMC, Host UEFI and DPU UEFI defaults; existing values are preserved\n'
                run pxeye-site-defaults timeout 60s kubectl --context "$CONTEXT" -n "$NAMESPACE" exec "deployment/$release" -- python3 -c 'from pxeye.services.site_credentials import initialize_new_site; raise SystemExit(0 if initialize_new_site() else 1)' || die 'Core connected but new-site credentials could not be initialized safely. Existing values are preserved; inspect PXEye and Core logs before retrying.'
                printf 'SITE_CREDENTIALS_READY\n'
            elif [[ -n ${SITE_CREDENTIALS_SECRET:-} ]]; then
                run pxeye-site-defaults timeout 60s kubectl --context "$CONTEXT" -n "$NAMESPACE" exec "deployment/$release" -- python3 -c 'from pxeye.services.site_credentials import verify_installed; raise SystemExit(0 if verify_installed() else 1)' || die 'Core connected but site credentials are not ready. Check Site settings, then resume; existing values are preserved.'
                printf 'SITE_CREDENTIALS_READY\n'
            fi
            state_mark pxeye-core-connected "$("$JQ" -cn --arg release "$release" --arg at "$(date -u +%FT%TZ)" '{release:$release,at:$at}')"
            printf 'PXEYE_CORE_CONNECTED\n'
            return
        fi
        sleep 5
    done
    die "PXEye did not complete its in-cluster Core connection within five minutes; see $DEPLOY/private/pxeye-core-connection.stderr"
}
