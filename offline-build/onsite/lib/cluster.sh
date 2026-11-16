#!/usr/bin/env bash
# Cluster discovery and ownership checks for the one-command onsite installer.

yaml_documents() {
    "$YQ" eval-all -o=json -I=0 '.' "$1" | "$JQ" -s 'map(select(type == "object"))'
}

namespace_exists() {
    kctl namespace get namespace "$NAMESPACE" --ignore-not-found -o name || die 'Cannot inspect the installation namespace'
    [[ -s "$RESULT" ]]
}

cert_manager_inventory() {
    local name record crds='{}' deployments
    for name in certificates.cert-manager.io issuers.cert-manager.io clusterissuers.cert-manager.io; do
        kctl "cert-manager-crd-$name" get crd "$name" --ignore-not-found -o json || die 'Cannot inspect cert-manager CRDs'
        if [[ -s "$RESULT" ]]; then
            record=$("$JQ" -c '{present:true, healthy:([.status.conditions[]? | select((.type == "Established" or .type == "NamesAccepted") and .status == "True") | .type] | unique | length == 2)}' "$RESULT")
        else
            record='{"present":false,"healthy":false}'
        fi
        crds=$("$JQ" -cn --argjson rows "$crds" --arg name "$name" --argjson row "$record" '$rows + {($name):$row}')
    done
    kctl cert-manager-deployments get deployments -A -o json || die 'Cannot inspect cert-manager deployments'
    deployments=$RESULT
    "$JQ" --argjson crds "$crds" '
        def healthy:
            (.spec.replicas // 1) as $desired |
            .status.observedGeneration == .metadata.generation and $desired >= 1 and
            (.status.readyReplicas // 0) >= $desired and (.status.availableReplicas // 0) >= $desired;
        .items as $items |
        {crds:$crds, components:(reduce ["cert-manager-controller", "cert-manager-webhook", "cert-manager-cainjector"][] as $component ({};
            [$items[] | select(([.metadata.name] + [.spec.template.spec.containers[]?.image] | join(" ") | contains($component)))] as $found |
            .[$component] = {present:($found|length > 0), healthy:any($found[]; healthy), deployments:[$found[] |
                {namespace:.metadata.namespace, name:.metadata.name, desired:(.spec.replicas // 1),
                 ready:(.status.readyReplicas // 0), available:(.status.availableReplicas // 0),
                 current:(.status.observedGeneration == .metadata.generation)}]}))}
    ' "$deployments" > "$DEPLOY/private/cert-manager-inventory.json" || die 'Cannot interpret cert-manager inventory'
}

resolve_cert_manager_mode() {
    local detected saved inventory="$DEPLOY/private/cert-manager-inventory.json"
    cert_manager_inventory
    if "$JQ" -e 'all((.crds + .components)[]; .present == false)' "$inventory" >/dev/null; then
        detected=install
    elif "$JQ" -e 'all((.crds + .components)[]; .healthy == true)' "$inventory" >/dev/null; then
        detected=reuse
    else
        detected=partial
    fi
    saved=$("$JQ" -r '.cert_manager_mode // empty' "$STATE")
    if [[ -n "$saved" ]]; then
        case "$saved" in
            reuse) [[ "$detected" == reuse ]] || die 'Previously reused cert-manager is no longer healthy; stop and inspect it' ;;
            install)
                if state_has installed-cert-manager; then
                    [[ "$detected" == reuse ]] || die 'Previously installed cert-manager is missing or unhealthy; stop and inspect it'
                elif [[ "$detected" != install ]]; then
                    recover_cert_manager_install
                fi ;;
            *) die 'Invalid saved cert-manager decision' ;;
        esac
        CERT_MANAGER_MODE=$saved
        printf 'REUSE_CERT_MANAGER_DECISION %s\n' "$saved"
    else
        [[ "$detected" != partial ]] || die "cert-manager is partially installed or unhealthy; resolve it before installation (see $inventory)"
        CERT_MANAGER_MODE=$detected
        jq_atomic "$STATE" '.cert_manager_mode = $mode' --arg mode "$detected"
        if [[ "$detected" == reuse ]]; then
            printf 'REUSE_SHARED_CERT_MANAGER\n'
        else
            printf 'INSTALL_BUNDLED_CERT_MANAGER\n'
        fi
    fi
}

check_namespace_resources() {
    local releases=$1 rows="$DEPLOY/private/namespace-resources.json" hooks="$DEPLOY/private/namespace-hooks.json"
    local release hooks_result unexpected
    if ! namespace_exists; then return; fi
    kctl namespace-resource-layout -n "$NAMESPACE" get \
        services,configmaps,secrets,persistentvolumeclaims,serviceaccounts,roles,rolebindings,deployments,statefulsets,daemonsets,jobs,cronjobs,networkpolicies,poddisruptionbudgets \
        -o json || die 'Cannot inspect existing namespace resources'
    "$JQ" '.items // []' "$RESULT" > "$rows"
    if [[ "$CERT_MANAGER_MODE" == reuse ]] || state_has installed-cert-manager; then
        kctl namespace-cert-manager-layout -n "$NAMESPACE" get certificates,certificaterequests,issuers -o json || die 'Cannot inspect cert-manager namespace resources'
        "$JQ" -s '.[0] + (.[1].items // [])' "$rows" "$RESULT" > "$rows.tmp" && mv "$rows.tmp" "$rows" || die 'Cannot combine namespace inventory'
    fi
    printf '[]\n' > "$hooks"
    # Hook resources do not always have Helm release annotations. Establish
    # their identity from the release record before accepting them.
    if "$JQ" -e 'any(.[]; .metadata.annotations["helm.sh/hook"] != null)' "$rows" >/dev/null; then
        while IFS= read -r release; do
            if hrun "namespace-hooks-$release" get hooks "$release" -n "$NAMESPACE"; then
                hooks_result=$RESULT
                yaml_documents "$hooks_result" > "$hooks_result.json" || die 'Cannot read recorded Helm hooks'
                "$JQ" -s '.[0] + .[1]' "$hooks" "$hooks_result.json" > "$hooks.tmp" && mv "$hooks.tmp" "$hooks" || die 'Cannot combine recorded Helm hooks'
            else
                grep -qi 'release: not found' "${RESULT%.stdout}.stderr" || die "Cannot establish Helm hook ownership for $release"
            fi
        done < <("$JQ" -r '.[]' <<< "$releases")
    fi
    unexpected=$("$JQ" -c --arg ns "$NAMESPACE" --argjson releases "$releases" \
        --slurpfile hooks "$hooks" --slurpfile state "$STATE" '
        . as $rows |
        def belongs($r):
            (($r.metadata.annotations["meta.helm.sh/release-name"] // "") as $release |
             ($releases | index($release)) != null and $r.metadata.annotations["meta.helm.sh/release-namespace"] == $ns)
            or ($r.kind == "Secret" and $r.type == "helm.sh/release.v1" and $r.metadata.labels.owner == "helm" and
                (($r.metadata.labels.name // "") as $release | ($releases | index($release)) != null));
        def system($r):
            ($r.kind == "ServiceAccount" and $r.metadata.name == "default") or
            ($r.kind == "ConfigMap" and $r.metadata.name == "kube-root-ca.crt") or
            ($r.kind == "Secret" and $r.type == "kubernetes.io/service-account-token" and
             $r.metadata.annotations["kubernetes.io/service-account.name"] == "default");
        def flag($args; $name):
            first(range(0; $args|length) as $i |
                if ($args[$i] | startswith($name + "=")) then $args[$i][($name|length)+1:]
                elif $args[$i] == $name then $args[$i+1] // empty else empty end) // null;
        def secret($name): $rows[] | select(.kind == "Secret" and .metadata.name == $name);
        (reduce $rows[] as $r ({}; if belongs($r) then .[$r.metadata.uid] = true else . end)) as $base |
        (reduce $rows[] as $r ($base;
            if $r.metadata.annotations["helm.sh/hook"] != null and any($hooks[0][];
                .metadata.annotations["helm.sh/hook"] != null and .kind == $r.kind and .metadata.name == $r.metadata.name and
                (.metadata.namespace // $ns) == ($r.metadata.namespace // $ns))
            then .[$r.metadata.uid] = true else . end)) as $owned_hooks |
        (reduce $rows[] as $r ($owned_hooks;
            if .[$r.metadata.uid] != true then .
            elif $r.kind == "Certificate" then
                reduce [secret($r.spec.secretName) | select(.metadata.annotations["cert-manager.io/certificate-name"] == $r.metadata.name)][] as $s (.; .[$s.metadata.uid] = true)
            elif $r.kind == "Deployment" then
                reduce $r.spec.template.spec.containers[]? as $c (.;
                    flag(($c.args // []); "--dynamic-serving-ca-secret-name") as $ca |
                    flag(($c.args // []); "--dynamic-serving-ca-secret-namespace") as $ca_ns |
                    (if $ca_ns == "$(POD_NAMESPACE)" and any($c.env[]?; .name == "POD_NAMESPACE" and .valueFrom.fieldRef.fieldPath == "metadata.namespace")
                     then $r.metadata.namespace else $ca_ns end) as $actual_ns |
                    reduce [secret($ca) | select($actual_ns == $ns and .metadata.labels["app.kubernetes.io/managed-by"] == "cert-manager" and
                        .metadata.annotations["cert-manager.io/allow-direct-injection"] == "true")][] as $s (.; .[$s.metadata.uid] = true))
            elif $r.kind == "Job" and $state[0].install_intents.vault != null then
                reduce $r.spec.template.spec.containers[]? as $c (.;
                    if (($c.command // [] | join(" ")) | contains("pxeye-bootstrap-vault")) then
                        (first($c.env[]? | select(.name == "NICO_PREFIX") | .value) // null) as $prefix |
                        if ($prefix|type) == "string" and ($prefix|test("^[a-z][a-z0-9-]{0,47}[a-z0-9]$|^[a-z]$")) then
                            reduce [secret($prefix + "-nico-vault-recovery"), secret($prefix + "-nico-vault-token"), secret($prefix + "-ssh-host-key") |
                                select(.type == "Opaque" and .metadata.labels["app.kubernetes.io/instance"] == ($prefix + "-vault-bootstrap"))][] as $s (.; .[$s.metadata.uid] = true)
                        else . end
                    else . end)
            else . end)) as $owned |
        def extend($known): reduce $rows[] as $r ($known;
            if any($r.metadata.ownerReferences[]?; . as $parent |
                $known[$parent.uid] == true and any($rows[]; .metadata.uid == $parent.uid and .kind == $parent.kind and .metadata.name == $parent.name))
            then .[$r.metadata.uid] = true else . end);
        def closure: . as $before | extend(.) | if . == $before then . else closure end;
        ($owned | closure) as $all_owned |
        [$rows[] | select((system(.) or $all_owned[.metadata.uid] == true) | not) | .kind + "/" + .metadata.name] | sort
    ' "$rows") || die 'Cannot establish namespace resource ownership'
    [[ "$unexpected" == '[]' ]] || die "Fresh installation refuses residual resources in $NAMESPACE: $unexpected"
    printf 'NAMESPACE_LAYOUT_OK %s\n' "$NAMESPACE"
}

cluster_preflight() {
    local endpoint previous allowed unexpected
    verify_bundle
    "$JQ" -e '.architecture == "linux/amd64" and .kind == "pxeye-nico-helm" and .initial_provisioning_network_state == "unconfigured"' \
        "$BUNDLE/bundle.json" >/dev/null || die 'Use a current amd64 Helm/relok8s control-plane-only delivery'
    kctl nodes get nodes -o json || die 'Cannot inspect target cluster nodes'
    "$JQ" -e 'any(.items[]; .status.nodeInfo.architecture == "amd64" and any(.status.conditions[]?; .type == "Ready" and .status == "True"))' \
        "$RESULT" >/dev/null || die 'An amd64 Ready node is required'
    kctl cluster-endpoint config view --minify -o 'jsonpath={.clusters[0].cluster.server}' || die 'Cannot resolve the target API server'
    endpoint=$(cat "$RESULT")
    [[ -n "$endpoint" ]] || die 'The target context has no API server'
    previous=$("$JQ" -r '.cluster_endpoint // empty' "$STATE")
    [[ -z "$previous" || "$previous" == "$endpoint" ]] || die 'Context now points at another API server'
    jq_atomic "$STATE" '.cluster_endpoint = $endpoint' --arg endpoint "$endpoint"
    hrun helm-version version --short || die 'Bundled Helm is unavailable'
    run relok8s-version "$RELOK" version || die 'Bundled relok8s is unavailable'
    probe_registry "$REGISTRY_URL"
    hrun namespace-release-layout list --all -n "$NAMESPACE" -o json || die 'Cannot inspect target namespace Helm releases'
    allowed=$("$JQ" -c --arg release "$RELEASE" '[.steps["bootstrapped-pxeye"].release, .pxeye_install_intent.release,
        (if ((.install_intents // {} | length) > 0 or any((.steps // {} | keys)[]; startswith("installed-"))) then $release else null end)] |
        map(select(type == "string")) | unique' "$STATE")
    unexpected=$("$JQ" -c --argjson allowed "$allowed" '[.[] | .name as $name | select(($allowed | index($name)) == null) | .name] | sort' "$RESULT")
    [[ "$unexpected" == '[]' ]] || die "Fresh installation requires an empty $NAMESPACE namespace or only releases created by this run: $unexpected"
    resolve_cert_manager_mode
    check_namespace_resources "$allowed"
    printf 'PREFLIGHT_OK %s %s\n' "$CONTEXT" "$NAMESPACE"
}
