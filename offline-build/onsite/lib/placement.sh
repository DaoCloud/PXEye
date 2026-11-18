#!/usr/bin/env bash
# Optional placement for the entire delivery, including Helm hook Jobs.

resolve_node_placement() {
    [[ -n $NODE_NAME ]] || return 0
    kctl selected-node get node "$NODE_NAME" -o json || die 'Cannot read the selected installation node'
    "$JQ" -e '.spec.unschedulable != true and .status.nodeInfo.architecture == "amd64" and
        any(.status.conditions[]; .type == "Ready" and .status == "True") and
        (.metadata.labels["kubernetes.io/hostname"] | type == "string" and length > 0)' "$RESULT" >/dev/null ||
        die 'Select a schedulable, Ready amd64 node with a hostname label'
    NODE_SELECTOR=$("$JQ" -c '{"kubernetes.io/hostname":.metadata.labels["kubernetes.io/hostname"]}' "$RESULT")
    printf 'INSTALL_NODE %s selector=%s\n' "$NODE_NAME" "$NODE_SELECTOR"
}

placement_values() {
    local input=$1 output=$2
    "$JQ" --argjson selector "$NODE_SELECTOR" '
        walk(if type == "object" and has("nodeSelector") then
            .nodeSelector = ((.nodeSelector // {}) + $selector)
        else . end) | .global.pxeyeNodeSelector = $selector
    ' "$input" > "$output" || die 'Cannot freeze node selection in Chart values'
}

place_chart_tree() {
    local root=$1 scratch=$2 archive child temporary file patched
    mkdir -p "$scratch"
    if [[ -f $root/values.yaml ]]; then
        "$YQ" -o=json '.' "$root/values.yaml" > "$scratch/defaults.json"
        placement_values "$scratch/defaults.json" "$scratch/placed.json"
        "$YQ" -P -p=json -o=yaml '.' "$scratch/placed.json" > "$root/values.yaml"
    fi
    # Dependencies may be directories or packaged charts. Preserve their format.
    if [[ -d $root/charts ]]; then
        while IFS= read -r -d '' archive; do
            temporary=$(mktemp -d "$scratch/dependency.XXXXXX")
            safe_extract "$archive" "$temporary/tree" 268435456
            local roots=()
            while IFS= read -r -d '' child; do roots+=("$child"); done < <(find "$temporary/tree" -mindepth 2 -maxdepth 2 -name Chart.yaml -type f -print0)
            ((${#roots[@]} == 1)) || die 'Cannot determine dependency Chart root for node placement'
            child=$(dirname "${roots[0]}")
            place_chart_tree "$child" "$temporary/nested"
            pack_chart "$child" "$temporary/chart.tgz"
            mv "$temporary/chart.tgz" "$archive"
            rm -rf -- "$temporary"
        done < <(find "$root/charts" -maxdepth 1 -type f -name '*.tgz' -print0)
        while IFS= read -r -d '' child; do
            place_chart_tree "$(dirname "$child")" "$scratch/directory-$(basename "$(dirname "$child")")"
        done < <(find "$root/charts" -mindepth 2 -maxdepth 2 -type f -name Chart.yaml -print0)
    fi
    [[ -d $root/templates ]] || return 0
    while IFS= read -r -d '' file; do
        # Native selector settings are supplied through placement_values.
        # Older templates without that setting receive the same global selector.
        if grep -Eq '^[[:space:]]*nodeSelector:' "$file"; then continue; fi
        patched=$(mktemp "$scratch/template.XXXXXX")
        awk '
            /^---[[:space:]]*$/ {kind=""}
            /^kind:[[:space:]]*/ {kind=$2; gsub(/"/, "", kind)}
            {
                print
                indent=-1
                if (kind=="Pod" && /^spec:[[:space:]]*$/) indent=2
                if (kind ~ /^(Deployment|StatefulSet|DaemonSet|ReplicaSet|ReplicationController|Job)$/ && /^    spec:[[:space:]]*$/) indent=6
                if (kind=="CronJob" && /^        spec:[[:space:]]*$/) indent=10
                if (indent>=0) {
                    printf "%*s{{- with $.Values.global.pxeyeNodeSelector }}\n", indent, ""
                    printf "%*snodeSelector: {{ toJson . }}\n", indent, ""
                    printf "%*s{{- end }}\n", indent, ""
                }
            }
        ' "$file" > "$patched" || die 'Cannot derive Chart node placement'
        cat "$patched" > "$file"
        rm -f "$patched"
    done < <(find "$root/templates" -type f \( -name '*.yaml' -o -name '*.yml' \) -print0)
}

check_node_placement() {
    [[ -n $NODE_NAME ]] || return 0
    local rejected
    # helm template includes hooks; validate them before Helm can create anything.
    # A template layout we cannot derive must fail closed here.
    rejected=$(yaml_documents "$1" | "$JQ" -c --argjson selector "$NODE_SELECTOR" '
        [.[] as $resource | $resource | .. | objects |
         select((.containers | type) == "array") |
         (.nodeSelector // {}) as $actual |
         select(any($selector | to_entries[]; . as $wanted | $actual[$wanted.key] != $wanted.value)) |
         {kind:$resource.kind,name:$resource.metadata.name,nodeSelector:.nodeSelector}]
    ') || die 'Cannot validate workload node selection'
    [[ $rejected == '[]' ]] || die "Workloads are not restricted to the selected node: $rejected"
}
