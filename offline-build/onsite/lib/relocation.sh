# Adapt relok8s metadata and import the unchanged image payload through its CLI.

relocation_yaml_json() { "$YQ" -p yaml -o json '.' "$1" > "$2"; }
relocation_json_yaml() { "$YQ" -p json -o yaml '.' "$1" > "$2"; }

prepare_intermediate() {
    local source=$1 destination=$2 metadata fields name
    metadata=$(mktemp -d "$(dirname "$destination")/.metadata-XXXXXX")
    mkdir -p "$metadata/original-chart"
    for name in hints.yaml original-chart/values.yaml; do
        tar -xOf "$source" -- "$name" > "$metadata/$name" || die "Missing relocation metadata: $name"
        [[ $(wc -c < "$metadata/$name") -le 4194304 ]] || die "Oversized relocation metadata: $name"
    done
    relocation_yaml_json "$metadata/hints.yaml" "$metadata/hints.json"
    relocation_yaml_json "$metadata/original-chart/values.yaml" "$metadata/values.json"
    "$JQ" -e 'type=="array" and all(.[];type=="string")' "$metadata/hints.json" > /dev/null || die 'Invalid relocation image hints'
    "$JQ" '[.[]|scan("\\{\\{\\s*\\.([A-Za-z_][A-Za-z0-9_.]*)\\s*\\}\\}")|.[0]]|unique' "$metadata/hints.json" > "$metadata/fields.json"
    if [[ $("$JQ" 'length' "$metadata/fields.json") == 0 ]]; then PREPARED_RELOCATION=$source; return; fi
    if "$JQ" -e 'has("__pxeye_relocation_root_fields__")' "$metadata/values.json" > /dev/null; then
        "$JQ" -e --slurpfile fields "$metadata/fields.json" '
          .__pxeye_relocation_root_fields__ as $a
          | ($a|type)=="object" and ($a|length)>0 and ($a|all(.[];type=="string"))
            and (($fields[0]|map(select(startswith("__pxeye_relocation_root_fields__."))|ltrimstr("__pxeye_relocation_root_fields__."))|sort)==($a|keys|sort))
        ' "$metadata/values.json" > /dev/null || die 'Reserved relocation field exists outside a compatible archive'
        printf '%s\n' 'REUSE_ADAPTED_ROOT_IMAGE_HINTS'
        PREPARED_RELOCATION=$source
        return
    fi
    "$JQ" --slurpfile fields "$metadata/fields.json" '
      . as $values | $fields[0] as $fields
      | ($fields|map({key:(gsub("\\.";"__")),value:.})|from_entries) as $aliases
      | if ($aliases|length)!=($fields|length) then error("Relocation image hint aliases collide") else . end
      | .__pxeye_relocation_root_fields__ = ($aliases|with_entries(.value as $path | .value = ($values|getpath($path|split(".")))))
      | if .__pxeye_relocation_root_fields__|all(.[];type=="string") then . else error("Relocation image hint must reference a scalar string") end
    ' "$metadata/values.json" > "$metadata/values-next.json" || die 'Cannot adapt relocation image fields'
    "$JQ" --slurpfile fields "$metadata/fields.json" '
      map(reduce $fields[0][] as $field (.;
        gsub("\\{\\{\\s*\\."+($field|gsub("\\.";"\\."))+"\\s*\\}\\}"; "{{ .__pxeye_relocation_root_fields__."+($field|gsub("\\.";"__"))+" }}")))
    ' "$metadata/hints.json" > "$metadata/hints-next.json"
    relocation_json_yaml "$metadata/hints-next.json" "$metadata/hints.yaml"
    relocation_json_yaml "$metadata/values-next.json" "$metadata/original-chart/values.yaml"
    cp "$metadata/hints.yaml" "$metadata/original-chart/.relok8s-images.yaml"
    # Copy the tar, then replace only small metadata members. images.tar is
    # neither extracted nor recompressed and its member payload stays intact.
    cp "$source" "$destination"
    local members=(hints.yaml original-chart/values.yaml)
    if tar -tf "$source" -- original-chart/.relok8s-images.yaml > /dev/null 2>&1; then
        members+=(original-chart/.relok8s-images.yaml)
    fi
    tar --delete --file "$destination" -- "${members[@]}" || die 'Cannot replace relocation metadata'
    tar --append --file "$destination" --directory "$metadata" -- "${members[@]}" || die 'Cannot append relocation metadata'
    PREPARED_RELOCATION=$destination
    printf '%s\n' 'ADAPT_ROOT_IMAGE_HINTS'
}

restore_root_fields() {
    local root=$1 temporary alias
    temporary=$(mktemp -d "$root/.restore-images-XXXXXX")
    relocation_yaml_json "$root/values.yaml" "$temporary/values.json"
    if ! "$JQ" -e 'has("__pxeye_relocation_root_fields__")' "$temporary/values.json" > /dev/null; then rm -rf -- "$temporary"; return; fi
    "$JQ" '.__pxeye_relocation_root_fields__' "$temporary/values.json" > "$temporary/aliases.json"
    "$JQ" --slurpfile aliases "$temporary/aliases.json" '
      if ($aliases[0]|type)!="object" or ($aliases[0]|all(.[];type=="string")|not) then error("Invalid relocated root aliases") else . end
      | del(.__pxeye_relocation_root_fields__)
      | reduce ($aliases[0]|to_entries[]) as $item (.;
          ($item.key|split("__")) as $path
          | if (getpath($path)|type)!="string" then error("Relocation image path disappeared") else setpath($path;$item.value) end)
    ' "$temporary/values.json" > "$temporary/next.json" || die 'Cannot restore relocated root image fields'
    relocation_json_yaml "$temporary/next.json" "$root/values.yaml"
    if [[ -f $root/.relok8s-images.yaml ]]; then
        "$JQ" -Rs --slurpfile aliases "$temporary/aliases.json" '
          reduce ($aliases[0]|keys[]) as $alias (.;split(".__pxeye_relocation_root_fields__."+$alias)|join("."+($alias|split("__")|join("."))))
        ' "$root/.relok8s-images.yaml" | "$JQ" -rj '.' > "$temporary/hints.yaml"
        mv "$temporary/hints.yaml" "$root/.relok8s-images.yaml"
    fi
    rm -rf -- "$temporary"
}

expand_dependencies() {
    local root=$1 archive temporary child destination entry
    [[ -d $root/charts ]] || return 0
    while IFS= read -r -d '' archive; do
        temporary=$(mktemp -d "$root/.expand-XXXXXX")
        safe_extract "$archive" "$temporary" 268435456
        local roots=()
        while IFS= read -r -d '' entry; do roots+=("$entry"); done < <(find "$temporary" -mindepth 2 -maxdepth 2 -type f -name Chart.yaml -print0)
        ((${#roots[@]} == 1)) || die 'Invalid vendored subchart archive'
        child=$(dirname "${roots[0]}")
        destination=$root/charts/$(basename "$child")
        [[ ! -e $destination ]] || die 'Duplicate vendored subchart'
        mv "$child" "$destination"
        rm -rf -- "$temporary"
        rm -- "$archive"
    done < <(find "$root/charts" -mindepth 1 -maxdepth 1 -type f -name '*.tgz' -print0)
    while IFS= read -r -d '' entry; do
        [[ ! -f $entry/Chart.yaml ]] || expand_dependencies "$entry"
    done < <(find "$root/charts" -mindepth 1 -maxdepth 1 -type d -print0)
}

restore_conditions() {
    local original=$1 relocated=$2 path relative temporary
    temporary=$(mktemp -d "$DEPLOY/private/restore-conditions-XXXXXX")
    while IFS= read -r -d '' path; do
        relative=${path#"$original"/}
        [[ -f $relocated/$relative ]] || die 'Relocation lost a vendored Chart'
        relocation_yaml_json "$path" "$temporary/source.json"
        if "$JQ" -e 'has("dependencies")' "$temporary/source.json" > /dev/null; then
            relocation_yaml_json "$relocated/$relative" "$temporary/target.json"
            "$JQ" --slurpfile source "$temporary/source.json" '.dependencies=$source[0].dependencies' "$temporary/target.json" > "$temporary/next.json"
            relocation_json_yaml "$temporary/next.json" "$relocated/$relative"
        fi
    done < <(find "$original" -type f -name Chart.yaml -print0)
    rm -rf -- "$temporary"
}

relocation_digests() {
    sed -nE 's/.*Digest:[[:space:]]*(sha256:[0-9a-f]{64}).*/\1/p' "$@" | sort -u
}

pull_chart() {
    local record=$1 directory=$2 attempt key expected path
    mkdir -p "$directory"
    attempt=$(mktemp -d "$directory/pull-XXXXXX")
    key=$("$JQ" -r '.id' <<< "$record")
    expected=$("$JQ" -r '.oci_digest' <<< "$record")
    registry_helm_flags
    hrun "$key-chart-pull" pull "$("$JQ" -r '.oci' <<< "$record")" --version "$("$JQ" -r '.version' <<< "$record")" \
        --destination "$attempt" "${HELM_TLS_FLAGS[@]}" || die 'Cannot pull imported OCI Chart'
    relocation_digests "$DEPLOY/private/$key-chart-pull.stdout" "$DEPLOY/private/$key-chart-pull.stderr" | \
        grep -Fx -- "$expected" > /dev/null || die 'OCI Chart digest changed'
    local files=()
    while IFS= read -r -d '' path; do files+=("$path"); done < <(find "$attempt" -mindepth 1 -maxdepth 1 -type f -name '*.tgz' -print0)
    ((${#files[@]} == 1)) || die 'Expected exactly one pulled Chart'
    [[ $(sha "${files[0]}") == $("$JQ" -r '.sha256' <<< "$record") ]] || die 'Pulled Chart archive checksum mismatch'
    PULLED_CHART=${files[0]}
}

refresh_catalog_images() {
    local catalog=${1:-$DEPLOY/catalog.json} temporary key
    temporary=$(mktemp -d "$DEPLOY/private/catalog-images-XXXXXX")
    : > "$temporary/transfers.log"
    while IFS= read -r key; do
        state_has "import-$key" || die 'Missing completed Chart transfer'
        [[ -f $DEPLOY/logs/$key-relocate.log ]] || die 'Missing relok8s transfer evidence'
        cat "$DEPLOY/logs/$key-relocate.log" >> "$temporary/transfers.log"
    done < <("$JQ" -r '.charts[].id' "$catalog")
    "$JQ" --slurpfile lock "$BUNDLE/manifests/images-lock.json" --rawfile logs "$temporary/transfers.log" \
        --arg registry "$REGISTRY" --arg scope "$SCOPE" '
      .images = [$lock[0][] | . as $row
        | .build_reference as $source | ($source|split("/")[-1]) as $name
        | ($name|sub(":[^:]+$";"")) as $repository
        | (":"+$source+") => ") as $marker
        | [$logs|split("\n")[]|select(contains($marker))|split($marker)[1]
            | if test("^\\S+ \\(sha256:[0-9a-f]{64}\\)") then
                capture("^(?<reference>\\S+) \\((?<digest>sha256:[0-9a-f]{64})\\)")
              else error("Unrecognized relok8s transfer evidence for "+$source) end
            | . + {path:(.reference|split("/")[1:]|join("/"))}
            | if .path != ($scope+"/images/"+$name) and .path != ($scope+"/images/"+$repository+"@"+.digest)
              then error("Unexpected relocated image path for "+$source) else .digest end] | unique
          | if length!=1 then error("Missing or conflicting transfer digest for "+$source) else .[0] end
          | {source:($row.source // $source),image:($registry+"/"+$scope+"/images/"+$name),source_digest:$row.digest,
             digest:.,kind:$row.kind,verification:"relok8s-canonicalized-transfer"}]
      | .ready=true
    ' "$catalog" > "$temporary/catalog.json" || die 'Cannot establish canonical imported image digests'
    chmod 600 "$temporary/catalog.json"
    mv "$temporary/catalog.json" "$catalog"
    printf 'REFRESH_IMAGE_DIGESTS %s; original source digests retained\n' "$("$JQ" '.images|length' "$catalog")"
}

import_bundle() {
    if [[ ${IMPORT_ONLY:-false} == true ]]; then import_preflight
    elif declare -F cluster_preflight > /dev/null; then cluster_preflight; else preflight; fi
    local inventory prefix key item record target relocation attempt path root original chart digest repository metadata catalog
    inventory=$(sha "$BUNDLE/manifests/file-inventory.json")
    prefix=$("$JQ" -r '.registry.repository_prefix // "nico-offline"' "$CONFIG")
    [[ $prefix =~ ^[a-z0-9]+([._/-][a-z0-9]+)*$ ]] || die 'Invalid Registry repository prefix'
    SCOPE=$prefix/bundle-${inventory:0:20}
    catalog=$DEPLOY/catalog.json
    [[ ! -f $catalog ]] || jq_atomic "$catalog" '.ready=false'
    mkdir -p "$DEPLOY/logs"
    local entries
    entries=$(mktemp "$DEPLOY/private/import-charts-XXXXXX")
    : > "$entries"
    registry_bridge_start
    while IFS= read -r item; do
        key=$("$JQ" -r '.id' <<< "$item")
        [[ $key =~ ^[a-z]([a-z0-9-]{0,47}[a-z0-9])?$ ]] || die 'Invalid chart id'
        if state_has "import-$key"; then
            record=$("$JQ" -c --arg key "import-$key" '.steps[$key]' "$STATE")
            chart=$DEPLOY/$("$JQ" -r '.local_chart' <<< "$record")
            [[ -f $chart && $(sha "$chart") == $("$JQ" -r '.sha256' <<< "$record") ]] || die 'Cached relocated Chart changed'
            pull_chart "$record" "$DEPLOY/verified-oci/$key"
            printf '%s\n' "$record" >> "$entries"
            printf 'REUSE_CHART %s\n' "$key"
            continue
        fi
        target=$DEPLOY/relocation/$key
        mkdir -p "$target"
        relocation=$BUNDLE/$("$JQ" -r '.relocation' <<< "$item")
        [[ $(readlink -f -- "$relocation") == "$BUNDLE/"* ]] || die 'Unsafe relocation path'
        attempt=$(mktemp -d "$target/attempt-XXXXXX")
        prepare_intermediate "$relocation" "$attempt/compatible.tar"
        if COMMAND_TIMEOUT=14400 run "$key-relocate" env DOCKER_CONFIG="$BRIDGE_PRIVATE" \
            "$RELOK" chart move "$PREPARED_RELOCATION" --registry "$BRIDGE_ADDRESS" --repo-prefix "$SCOPE/images" --out "$attempt/*.tgz" --yes; then
            cat "$DEPLOY/private/$key-relocate.stdout" "$DEPLOY/private/$key-relocate.stderr" >> "$DEPLOY/logs/$key-relocate.log"
        else
            cat "$DEPLOY/private/$key-relocate.stdout" "$DEPLOY/private/$key-relocate.stderr" >> "$DEPLOY/logs/$key-relocate.log"
            die 'relok8s transfer failed; fix the cause and rerun the same command'
        fi
        local files=()
        while IFS= read -r -d '' path; do files+=("$path"); done < <(find "$attempt" -mindepth 1 -maxdepth 1 -type f -name '*.tgz' -print0)
        ((${#files[@]} == 1)) || die 'Relok8s did not produce exactly one Chart'
        safe_extract "${files[0]}" "$attempt/tree" 268435456
        local roots=()
        while IFS= read -r -d '' path; do roots+=("$path"); done < <(find "$attempt/tree" -mindepth 2 -maxdepth 2 -type f -name Chart.yaml -print0)
        ((${#roots[@]} == 1)) || die 'Relocated Chart root is ambiguous'
        root=$(dirname "${roots[0]}")
        restore_root_fields "$root"
        expand_dependencies "$root"
        original=$BUNDLE/$("$JQ" -r '.chart' <<< "$item")
        [[ $(readlink -f -- "$original") == "$BUNDLE/"* ]] || die 'Unsafe original Chart path'
        safe_extract "$original" "$attempt/original" 268435456
        roots=()
        while IFS= read -r -d '' path; do roots+=("$path"); done < <(find "$attempt/original" -mindepth 2 -maxdepth 2 -type f -name Chart.yaml -print0)
        ((${#roots[@]} == 1)) || die 'Original Chart root is ambiguous'
        original=$(dirname "${roots[0]}")
        expand_dependencies "$original"
        restore_conditions "$original" "$root"
        while IFS= read -r -d '' path; do
            "$JQ" -Rs --arg bridge "$BRIDGE_ADDRESS" --arg registry "$REGISTRY" 'split($bridge)|join($registry)' "$path" | "$JQ" -rj '.' > "$attempt/replaced"
            cat "$attempt/replaced" > "$path"
        done < <(find "$root" -type f \( -name '*.yaml' -o -name '*.yml' -o -name '*.tpl' -o -name '*.txt' -o -name '*.json' \) -print0)
        chart=$target/chart.tgz
        pack_chart "$root" "$chart"
        digest=$(sha "$chart")
        metadata=$("$YQ" -p yaml -o json '.' "$root/Chart.yaml")
        repository=$REGISTRY/$SCOPE/charts/$digest
        registry_helm_flags
        hrun "$key-chart-push" push "$chart" "oci://$repository" "${HELM_TLS_FLAGS[@]}" || die 'Cannot push relocated OCI Chart'
        local digests=()
        while IFS= read -r path; do digests+=("$path"); done < <(relocation_digests "$DEPLOY/private/$key-chart-push.stdout" "$DEPLOY/private/$key-chart-push.stderr")
        ((${#digests[@]} == 1)) || die 'Helm push did not report one OCI digest'
        record=$("$JQ" -nc --arg id "$key" --argjson metadata "$metadata" --arg repository "$repository" --arg digest "${digests[0]}" \
            --arg sha "$digest" --arg chart "${chart#"$DEPLOY"/}" \
            '{id:$id,name:$metadata.name,version:($metadata.version|tostring),oci:("oci://"+$repository+"/"+$metadata.name),oci_digest:$digest,sha256:$sha,local_chart:$chart}')
        pull_chart "$record" "$DEPLOY/verified-oci/$key"
        state_mark "import-$key" "$record"
        printf '%s\n' "$record" >> "$entries"
    done < <("$JQ" -c '.charts[]' "$BUNDLE/bundle.json")
    registry_bridge_stop
    "$JQ" -n --slurpfile bundle "$BUNDLE/bundle.json" --slurpfile entries "$entries" --arg inventory "$inventory" --arg registry "$REGISTRY" \
        '{schema_version:1,kind:"pxeye-nico-onsite",ready:false,bundle_id:$bundle[0].id,bundle_version:$bundle[0].version,bundle_inventory_sha256:$inventory,registry:$registry,charts:$entries}' > "$catalog.tmp"
    chmod 600 "$catalog.tmp"
    mv "$catalog.tmp" "$catalog"
    refresh_catalog_images "$catalog"
    printf 'IMPORT_COMPLETE %s\n' "$catalog"
}
