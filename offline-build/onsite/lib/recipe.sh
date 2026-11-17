#!/usr/bin/env bash
# Frozen Helm recipes; sourced by install.sh after common and cluster helpers.

recipe_chart_alias_map() {
    local chart=$1 output=$2 member
    member=$(tar -tf "$chart" | awk 'split($0,p,"/")==2 && p[2]=="Chart.yaml" {print}')
    [[ -n $member && $member != *$'\n'* ]] || die 'Expected one root Chart metadata file'
    tar -xOf "$chart" -- "$member" > "$output.yaml" || die 'Cannot read recipe Chart metadata'
    "$YQ" -p yaml -o json '.' "$output.yaml" > "$output.metadata" || die 'Cannot parse recipe Chart metadata'
    "$JQ" '
      def dns: type=="string" and test("^[a-z0-9]([a-z0-9-]*[a-z0-9])?$") and length<=63;
      . as $chart | (reduce ((.dependencies // [])[] | select(.name=="cert-manager")) as $dependency ({};
        ($dependency.alias // $dependency.name) as $alias
        | if $alias|dns then . else
            ($alias|ascii_downcase) as $normalized
            | if ($normalized|dns|not) then error("cert-manager alias cannot form a DNS name")
              elif any($chart.dependencies[]; (.alias // .name)==$normalized) then error("cert-manager alias normalization collides")
              else .[$alias]=$normalized end
          end)) as $aliases
      | [($chart.dependencies // [])[] | (.alias // .name) as $alias | ($aliases[$alias] // $alias)] as $names
      | if ($names|length)!=($names|unique|length) then error("Derived dependency aliases collide") else $aliases end
    ' "$output.metadata" > "$output" || die 'Cannot derive cert-manager DNS naming policy'
}

derive_recipe_chart() {
    local source=$1 destination=$2 scratch=$3 root path
    mkdir -p "$scratch"
    recipe_chart_alias_map "$source" "$scratch/aliases.json"
    if [[ $("$JQ" 'length' "$scratch/aliases.json") == 0 ]]; then cp "$source" "$destination"; return; fi
    safe_extract "$source" "$scratch/tree" 268435456
    local roots=()
    while IFS= read -r -d '' path; do roots+=("$path"); done < <(find "$scratch/tree" -mindepth 2 -maxdepth 2 -type f -name Chart.yaml -print0)
    ((${#roots[@]} == 1)) || die 'Recipe Chart root is ambiguous'
    root=$(dirname "${roots[0]}")
    # Helm aliases become the child .Chart.Name, including container names
    # that standard nameOverride/fullnameOverride values cannot affect.
    "$JQ" --slurpfile aliases "$scratch/aliases.json" '
      .dependencies |= map(. as $dependency | ($dependency.alias // $dependency.name) as $alias
        | if $aliases[0][$alias] then .alias=$aliases[0][$alias] else . end
        | if (.condition|type)=="string" then
            .condition |= (split(",") | map(reduce ($aliases[0]|to_entries[]) as $item (.;
              if .==$item.key or startswith($item.key+".") then $item.value+ltrimstr($item.key) else . end)) | join(","))
          else . end)
    ' "$scratch/aliases.json.metadata" > "$scratch/chart.json" || die 'Cannot derive DNS-safe dependency aliases'
    "$YQ" -P -p json -o yaml '.' "$scratch/chart.json" > "$root/Chart.yaml"
    "$YQ" -p yaml -o json '.' "$root/values.yaml" > "$scratch/values.json"
    "$JQ" --slurpfile aliases "$scratch/aliases.json" '
      reduce ($aliases[0]|to_entries[]) as $item (.;
        if has($item.key) then
          if has($item.value) then error("Both original and normalized dependency values exist")
          else .[$item.value]=.[$item.key] | del(.[$item.key]) end
        else . end)
    ' "$scratch/values.json" > "$scratch/normalized-values.json" || die 'Cannot move dependency values to DNS-safe alias'
    "$YQ" -P -p json -o yaml '.' "$scratch/normalized-values.json" > "$root/values.yaml"
    pack_chart "$root" "$destination"
    printf 'RECIPE_CHART_NAMES_NORMALIZED %s\n' "$("$JQ" -c . "$scratch/aliases.json")"
}

validate_install_plan_structure() {
    "$JQ" -e '
        def id: if type == "string" then test("^[a-z]([a-z0-9-]{0,47}[a-z0-9])?$") else false end;
        (.phases | type) == "array" and (.phases | length) > 0 and
        ([.phases[].id] | unique | length) == (.phases | length) and
        all(.phases[];
            type == "object" and (.id | id) and (.chart_id | id) and
            ((has("values_inline") | not) or (.values_inline | type) == "object"))
    ' "$1" > /dev/null || die "Installation plan must contain nonempty, uniquely named valid phases and Chart ids"
}

validate_recipe_structure() {
    "$JQ" -e --arg release "$RELEASE" '
        def id: if type == "string" then test("^[a-z]([a-z0-9-]{0,47}[a-z0-9])?$") else false end;
        def path:
            if type != "string" then false else
                length > 0 and (startswith("/") | not) and (contains("\\") | not) and
                (explode | all(.[]; . >= 32 and . != 127)) and
                (split("/") | all(.[]; . != "" and . != "." and . != ".."))
            end;
        def digest: if type == "string" then test("^[0-9a-f]{64}$") else false end;
        . as $manifest |
        .schema_version == 1 and (.files | type) == "object" and
        all(.files | to_entries[]; (.key | path) and (.value | digest)) and
        (.phases | type) == "array" and (.phases | length) > 0 and
        ([.phases[].id] | unique | length) == (.phases | length) and
        all(.phases[];
            type == "object" and (.id | id) and .release == $release and
            (.chart | path) and ($manifest.files[.chart] | digest) and
            (.values | type) == "array" and (.values | length) > 0 and
            all(.values[]; path and ($manifest.files[.] | digest)))
    ' "$1" > /dev/null || die "Invalid frozen recipe phases, paths or referenced file inventory"
}

check_images() {
    local rendered=$1 catalog=${2:-$DEPLOY/catalog.json} rejected
    rejected=$(yaml_documents "$rendered" | "$JQ" -r --slurpfile catalog "$catalog" '
        . as $documents |
        [ $catalog[0].images[] |
          .image as $image | ($image | split("@")[0]) as $tagged |
          ($tagged | sub(":[^/:]+$"; "")) as $repository |
          $image, ($repository + "@" + .digest), ($tagged + "@" + .digest)
        ] | unique as $allowed |
        $documents |
        [.. | objects | to_entries[] |
         select((.key == "containers" or .key == "initContainers" or .key == "ephemeralContainers") and (.value | type) == "array") |
         .value[] | .image | select(. as $image | $allowed | index($image) | not)] |
        unique | .[] | tostring
    ') || die "Cannot validate rendered image references"
    [[ -z $rejected ]] || die "Rendered image is outside imported lock: $rejected"
}

imported_defaults() {
    local input=$1 catalog=$2 output=$3
    "$JQ" --slurpfile rows "$BUNDLE/manifests/images-lock.json" --slurpfile catalog "$catalog" '
        ($catalog[0].images | map({key:.source,value:.}) | from_entries) as $transferred |
        (reduce $rows[0][] as $row ({};
          ($transferred[$row.source // $row.build_reference] // error("Missing transferred image: " + $row.build_reference)) as $target |
          .[$row.build_reference] = $target)) as $locked |
        def relocated:
          if type == "object" then
            with_entries(.value |= relocated) |
            (if (.repository | type) == "string" then $locked[.repository + ":" + (.tag | tostring)] else null end) as $target |
            if $target then
              ($target.image | split("@")[0]) as $tagged |
              .repository = ($tagged | sub(":[^/:]+$"; "")) |
              .tag = ($tagged | capture(":(?<tag>[^/:]+)$").tag) |
              .digest = $target.digest |
              if has("registry") then .registry = "" else . end
            else . end
          elif type == "array" then map(relocated)
          elif type == "string" and $locked[.] then
            $locked[.] | (.image | sub(":[^/:]+$"; "")) + "@" + .digest
          else . end;
        relocated
    ' "$input" > "$output" || die "Cannot resolve relocated image defaults"
}

image_defaults() {
    local defaults=$1 values=$2 output=$3
    "$JQ" --slurpfile defaults "$defaults" --arg registry "$REGISTRY/" '
        def images($d; $v):
          (if ($d | type) == "object" and ($d | length) > 0 and ($v | type) == "array" and
              ($d | keys | all(.[]; test("^[0-9]+$")))
           then ($v | to_entries | map({key:(.key|tostring),value:.value}) | from_entries) else $v end) as $value |
          if ($d | type) == "object" and ($value | type) == "object" then
            (if ($d.repository | type) == "string" and ($d.repository | startswith($registry))
             then ($value | del(.repository,.tag,.digest,.registry)) + ($d | with_entries(select(.key == "repository" or .key == "tag" or .key == "digest" or .key == "registry")))
             else $value end) as $base |
            reduce ($d | keys[]) as $key ($base; .[$key] = images($d[$key]; (if has($key) then .[$key] else $d[$key] end)))
          elif ($d | type) == "string" and ($d | startswith($registry)) then $d
          else $value end;
        images($defaults[0]; .)
    ' "$values" > "$output" || die "Cannot freeze relocated image defaults"
}

recipe_values() {
    local defaults_yaml=$1 phase=$2 catalog=$3 output=$4 scratch=$5
    local aliases=${6:-}
    local site mode phase_id
    site=$("$JQ" -r '.site_name' "$CONFIG")
    mode=$("$JQ" -r '.cert_manager_mode' "$STATE")
    phase_id=$("$JQ" -r '.id' <<< "$phase")
    "$YQ" -p yaml -o json '.' "$defaults_yaml" > "$scratch/defaults.json" || die "Cannot read Chart defaults"
    imported_defaults "$scratch/defaults.json" "$catalog" "$scratch/imported.json"
    image_defaults "$scratch/imported.json" "$scratch/imported.json" "$scratch/images.json"
    if [[ -z $aliases ]]; then aliases=$scratch/aliases.json; printf '{}\n' > "$aliases"; fi
    "$JQ" --slurpfile aliases "$aliases" --arg site "$site" --arg namespace "$NAMESPACE" --arg release "$RELEASE" --argjson phase "$phase" '
        (reduce ($aliases[0]|to_entries[]) as $item (($phase.values_inline // {});
          if has($item.key) then
            if has($item.value) then error("Phase defines both original and normalized dependency aliases")
            else .[$item.value]=.[$item.key] | del(.[$item.key]) end
          else . end)) as $inline |
        if $phase.id == "core" then
          .nicoCore["nico-api"].siteConfig.nicoApiSiteConfig |= gsub("\"@\\{site_name\\}\""; ($site | tojson))
        else . end |
        walk(if type == "string" then
          gsub("@\\{release_prefix\\}"; $release) | gsub("@\\{namespace\\}"; $namespace) | gsub("@\\{site_name\\}"; $site)
        else . end) * $inline
    ' "$scratch/images.json" > "$scratch/substituted.json" || die "Cannot derive phase values: $phase_id"
    if [[ $mode == reuse ]]; then
        "$JQ" '
            if (has("components") and (.components | type) != "object") or
               ((.components // {}) | has("certManager")) and (.components.certManager | type) != "object"
            then error("Parent Chart components.certManager must contain an object")
            else .components.certManager.enabled = false end
        ' "$scratch/substituted.json" > "$scratch/reuse.json" || die "Invalid parent Chart components"
        mv "$scratch/reuse.json" "$scratch/substituted.json"
    fi
    if [[ $phase_id == core ]]; then
        "$JQ" --arg site "$site" '
            .nicoCore["nico-api"].siteConfig.nicoApiSiteConfig |= sub("(?m)^sitename\\s*=.*$"; "sitename = " + ($site | tojson))
        ' "$scratch/substituted.json" > "$scratch/core.json" || die "Cannot set Core site name"
        "$JQ" -er '.nicoCore["nico-api"].siteConfig.nicoApiSiteConfig | select(type == "string")' "$scratch/core.json" > "$scratch/site.toml" || die "Missing Core site configuration"
        "$YQ" -p toml -o json '.' "$scratch/site.toml" > "$scratch/site.json" || die "Cannot parse Core TOML configuration"
        "$JQ" -e '
            ((.networks // {}) | type) == "object" and
            all((.networks // {})[]; .type != "hostinband") and
            ((.site_explorer.enabled // false) | not) and
            ((.firmware_global.autoupdate // false) | not)
        ' "$scratch/site.json" > /dev/null || die "Initial delivery must not define HostInband or enable discovery/firmware automation"
        "$JQ" -e '.nicoCore["nico-dhcp"].replicas == 0' "$scratch/core.json" > /dev/null || die "Initial delivery must keep nico-dhcp scaled to zero"
        "$JQ" --arg owner "$NAMESPACE-pxeye" '
            .nicoCore["nico-dhcp"].externalService.enabled = false |
            .nicoCore["nico-dns"].externalService.enabled = false |
            .nicoCore["nico-pxe"].externalService.enabled = false |
            .nicoCore["nico-ntp"].externalService.enabled = false |
            .nicoCore["nico-pxe"].pxeyeStorage = {
              enabled:true, claimName:($owner+"-storage"), ownerRelease:$owner}
        ' "$scratch/core.json" > "$scratch/substituted.json" || die "Cannot disable initial external boot Services"
    fi
    "$JQ" -e '[.. | strings | select(test("@\\{[a-z_]+\\}"))] | length == 0' "$scratch/substituted.json" > /dev/null || die "Unresolved values variables in $phase_id"
    "$YQ" -P -p json -o yaml '.' "$scratch/substituted.json" > "$output" || die "Cannot write phase values"
    chmod 600 "$output"
}

prepare_recipe() {
    local root=$DEPLOY/recipe catalog=$DEPLOY/catalog.json temporary recipe plan mode phase phase_id chart_id record chart target digest name relative provenance
    if [[ -e $root || -L $root ]]; then
        validate_recipe
        printf 'REUSE_RECIPE %s\n' "$root"
        if [[ ! -f $DEPLOY/ui-recipe.tar.gz || ! -f $DEPLOY/recipe-result.json ]]; then ui_package; fi
        return
    fi
    cluster_preflight
    "$JQ" -e --slurpfile state "$STATE" '.ready == true and .bundle_inventory_sha256 == $state[0].bundle_inventory_sha256' "$catalog" > /dev/null || die "Import this bundle first"
    refresh_catalog_images "$catalog"
    temporary=$(mktemp -d "$DEPLOY/.recipe-XXXXXXXX") || die "Cannot create recipe staging directory"
    recipe=$temporary/nico-recipe
    provenance=$temporary/chart-provenance.json
    printf '{}\n' > "$provenance"
    mkdir -p "$recipe/charts" "$recipe/values" "$temporary/pulled"
    mode=$("$JQ" -r '.cert_manager_mode' "$STATE")
    [[ $mode == install || $mode == reuse ]] || die "Missing cert-manager installation decision"
    plan=$temporary/deployment.json
    validate_install_plan_structure "$BUNDLE/profiles/install-plan.json"
    "$JQ" --arg mode "$mode" '
        .schema_version = 1 | .phases |= map(select($mode != "reuse" or .id != "cert-manager") | del(.material_chart))
    ' "$BUNDLE/profiles/install-plan.json" > "$plan" || die "Cannot read installation plan"
    validate_install_plan_structure "$plan"
    if [[ $mode == reuse ]]; then printf '%s\n' 'SKIP_CERT_MANAGER_PHASE reuse-shared-controller'; fi
    while IFS= read -r phase; do
        phase_id=$("$JQ" -r '.id' <<< "$phase")
        chart_id=$("$JQ" -r '.chart_id' <<< "$phase")
        [[ $phase_id =~ ^[a-z]([a-z0-9-]{0,47}[a-z0-9])?$ && $chart_id =~ ^[a-z]([a-z0-9-]{0,47}[a-z0-9])?$ ]] || die "Invalid installation phase or Chart id"
        record=$("$JQ" -ce --arg id "$chart_id" '[.charts[] | select(.id == $id)] | if length == 1 then .[0] else error("Chart is missing or ambiguous") end' "$catalog") || die "Missing imported Chart: $chart_id"
        pull_chart "$record" "$temporary/pulled/$phase_id"
        chart=$PULLED_CHART
        target=$recipe/charts/$chart_id.tgz
        if [[ ! -e $target ]]; then
            derive_recipe_chart "$chart" "$target" "$temporary/chart-$chart_id"
            jq_atomic "$provenance" '.[$chart]={source:{oci:$source.oci,oci_digest:$source.oci_digest,sha256:$source.sha256},sha256:$digest,naming_policy:"dns-cert-manager-alias-v1",aliases:$aliases[0]}' \
                --arg chart "charts/$chart_id.tgz" --argjson source "$record" --arg digest "$(sha "$target")" --slurpfile aliases "$temporary/chart-$chart_id/aliases.json"
        fi
        chart=$target
        hrun "$phase_id-defaults" show values "$chart" || die "Cannot read Chart defaults: $phase_id"
        mkdir -p "$temporary/values-$phase_id"
        cp "$RESULT" "$temporary/values-$phase_id/defaults.yaml"
        recipe_values "$temporary/values-$phase_id/defaults.yaml" "$phase" "$catalog" "$recipe/values/$phase_id.yaml" "$temporary/values-$phase_id" "$temporary/chart-$chart_id/aliases.json"
        jq_atomic "$plan" '.phases |= map(if .id == $id then del(.chart_id,.values_inline) + {chart:($chart),values:[$values],release:$release} else . end)' \
            --arg id "$phase_id" --arg chart "charts/$chart_id.tgz" --arg values "values/$phase_id.yaml" --arg release "$RELEASE"
        hrun "$phase_id-render" template "$RELEASE" "$chart" -n "$NAMESPACE" -f "$recipe/values/$phase_id.yaml" || die "Cannot render phase: $phase_id"
        check_images "$RESULT" "$catalog"
    done < <("$JQ" -c '.phases[]' "$plan")
    cp "$catalog" "$recipe/catalog.json"
    "$JQ" --slurpfile provenance "$provenance" --arg namespace "$NAMESPACE" --arg release "$RELEASE" --arg site "$("$JQ" -r '.site_name' "$CONFIG")" \
        --arg mode "$mode" --arg version "$("$JQ" -r '.bundle_version | tostring' "$catalog")" '
        walk(if type == "string" then gsub("@\\{release_prefix\\}"; $release) | gsub("@\\{namespace\\}"; $namespace) | gsub("@\\{site_name\\}"; $site) else . end) |
        .version = $version | .name = "NICo offline onsite recipe" | .cert_manager_mode = $mode | .chart_derivations=$provenance[0] | .files = {}
    ' "$plan" > "$recipe/deployment.json" || die "Cannot finalize deployment manifest"
    while IFS= read -r name; do
        relative=${name#"$recipe/"}
        digest=$(sha "$name")
        jq_atomic "$recipe/deployment.json" '.files[$name] = $digest' --arg name "$relative" --arg digest "$digest"
    done < <(find "$recipe/charts" "$recipe/values" -type f -print | LC_ALL=C sort)
    digest=$(sha "$recipe/catalog.json")
    jq_atomic "$recipe/deployment.json" '.files["catalog.json"] = $digest' --arg digest "$digest"
    validate_recipe_structure "$recipe/deployment.json"
    digest=$(sha "$recipe/deployment.json")
    jq_atomic "$STATE" '.recipe_manifest_sha256 = $digest' --arg digest "$digest"
    mv "$recipe" "$root"
    rm -rf -- "$temporary"
    printf 'RECIPE_READY %s\n' "$root"
    ui_package
}

validate_recipe() {
    local root=$DEPLOY/recipe expected name digest chart aliases alias_count
    RECIPE_MANIFEST=$root/deployment.json
    [[ -d $root && ! -L $root && -f $RECIPE_MANIFEST && ! -L $RECIPE_MANIFEST ]] || die "Missing or unsafe frozen recipe"
    [[ -z $(find "$root" -type l -print -quit) ]] || die "Frozen recipe contains a symlink"
    expected=$("$JQ" -er '.recipe_manifest_sha256' "$STATE") || die "Missing frozen recipe identity"
    [[ $(sha "$RECIPE_MANIFEST") == "$expected" ]] || die "Frozen deployment manifest changed"
    validate_recipe_structure "$RECIPE_MANIFEST"
    while IFS=$'\t' read -r name digest; do
        case "$name" in ''|/*|*\\*|..|../*|*/../*|*/..|.|./*|*/./*|*/.) die "Unsafe frozen recipe path: $name" ;; esac
        [[ -f $root/$name && ! -L $root/$name ]] || die "Missing frozen recipe file: $name"
        [[ $digest =~ ^[0-9a-f]{64}$ && $(sha "$root/$name") == "$digest" ]] || die "Frozen recipe changed: $name"
    done < <("$JQ" -r '.files | to_entries[] | [.key,.value] | @tsv' "$RECIPE_MANIFEST")
    while IFS= read -r chart; do
        aliases=$(mktemp "$DEPLOY/private/frozen-chart-aliases-XXXXXX")
        recipe_chart_alias_map "$root/$chart" "$aliases"
        alias_count=$("$JQ" 'length' "$aliases")
        rm -f -- "$aliases" "$aliases.yaml" "$aliases.metadata"
        [[ $alias_count == 0 ]] || die 'Frozen recipe has a non-DNS cert-manager alias; inspect and archive only an unconsumed recipe before regenerating it'
    done < <("$JQ" -r '[.phases[].chart]|unique[]' "$RECIPE_MANIFEST")
}

ui_package() {
    local root=$DEPLOY/recipe phase archive=$DEPLOY/ui-recipe.tar.gz digest
    validate_recipe
    while IFS= read -r phase; do check_ownership "$root" "$phase"; done < <("$JQ" -c '.phases[]' "$RECIPE_MANIFEST")
    tar -czf "$archive" -C "$DEPLOY" recipe || die "Cannot create frozen UI recipe archive"
    chmod 600 "$archive"
    digest=$(sha "$archive")
    jq_atomic "$DEPLOY/recipe-result.json" '{archive_sha256:$digest,archive:$archive,notice:"May include private Helm values; transfer securely; do not commit"}' \
        --arg digest "$digest" --arg archive "$archive"
    printf 'UI_UPLOAD %s ; use frozen site defaults; do not run UI and CLI installation concurrently\n' "$archive"
}
