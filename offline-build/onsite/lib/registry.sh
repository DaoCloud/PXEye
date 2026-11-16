# Registry discovery and the local HTTP transport used by relok8s 0.5.4.

registry_url_parts() {
    "$JQ" -cen --arg url "$1" '
      $url | capture("^(?<scheme>https?)://(?<authority>\\[[0-9A-Fa-f:.]+\\](?::[0-9]+)?|[A-Za-z0-9_.-]+(?::[0-9]+)?)/?$")
      | .scheme as $scheme
      | .authority |= ascii_downcase
      | . + (.authority | capture("^(?<host>\\[[^]]+\\]|[^:]+)(?::(?<port>[0-9]+))?$") )
      | .port = ((.port // (if $scheme == "https" then "443" else "80" end)) | tonumber)
      | if .port < 1 or .port > 65535 then error("Invalid Registry port") else . end
      | .hostname = (.host | ltrimstr("[") | rtrimstr("]"))
      | .authority = (.host + (if .port == (if $scheme == "https" then 443 else 80 end) then "" else ":" + (.port|tostring) end))
      | .url = (.scheme + "://" + .authority)
    '
}

registry_curl_flags() {
    REGISTRY_CURL_FLAGS=(--silent --show-error --noproxy '*' --connect-timeout 4 --max-time 4)
    local skip=true ca=
    if [[ -n ${CONFIG:-} && -f $CONFIG ]]; then
        skip=$("$JQ" -r '.registry.skip_tls_verify // false' "$CONFIG")
        ca=$("$JQ" -r '.registry.ca_file // empty' "$CONFIG")
    fi
    [[ $skip != true ]] || REGISTRY_CURL_FLAGS+=(--insecure)
    [[ -z $ca ]] || REGISTRY_CURL_FLAGS+=(--cacert "$ca")
}

registry_helm_flags() {
    HELM_TLS_FLAGS=()
    [[ $REGISTRY_URL != http://* ]] || HELM_TLS_FLAGS+=(--plain-http)
    [[ $("$JQ" -r '.registry.skip_tls_verify // false' "$CONFIG") != true ]] || HELM_TLS_FLAGS+=(--insecure-skip-tls-verify)
    local ca
    ca=$("$JQ" -r '.registry.ca_file // empty' "$CONFIG")
    [[ -z $ca ]] || HELM_TLS_FLAGS+=(--ca-file "$ca")
}

registry_v2_header() {
    awk 'tolower($0) ~ /^docker-distribution-api-version[[:space:]]*:/ {
      sub(/^[^:]*:[[:space:]]*/, ""); sub(/\r$/, ""); print tolower($0)
    }' "$1" | tail -n 1
}

probe_registry() {
    local url=${1:-$REGISTRY_URL} private code status=0
    private=$(mktemp -d "$DEPLOY/private/registry-probe-XXXXXX")
    registry_curl_flags
    code=$(curl "${REGISTRY_CURL_FLAGS[@]}" --dump-header "$private/headers" --output "$private/body" \
        --write-out '%{http_code}' "$url/v2/" 2>"$private/error") || status=$?
    [[ $status == 0 && ( $code == 200 || $code == 401 ) && $(registry_v2_header "$private/headers") == registry/2.0 ]] ||
        die "Registry V2 endpoint is unavailable or has invalid TLS/API evidence; see $private"
    printf 'REGISTRY_V2_OK %s\n' "${url#*://}"
}

detect_registry() {
    local private candidates raw objects hint authority scheme code status valid error parts count found
    local schemes=(https http)
    private=$(mktemp -d "$WORK/.registry-discovery-XXXXXX")
    candidates=$private/candidates.jsonl
    : > "$candidates"
    if [[ -n ${NICO_REGISTRY_URL:-} ]]; then
        parts=$(registry_url_parts "$NICO_REGISTRY_URL") || die 'NICO_REGISTRY_URL must be http(s)://host[:port] without credentials or a path'
        schemes=("$("$JQ" -r '.scheme' <<< "$parts")")
        authority=${NICO_REGISTRY_URL#*://}
        authority=${authority%/}
        "$JQ" -nc --arg authority "$authority" \
            '{authority:$authority,source:"NICO_REGISTRY_URL"}' >> "$candidates"
    else
        kctl registry-workload-evidence --request-timeout=15s get pods,deployments -A -o json ||
            die 'Registry discovery cannot read cluster workload evidence'
        objects=$RESULT
        "$JQ" -c '
          def private_host:
            ascii_downcase as $h
            | if $h == "localhost" or ($h|endswith(".localhost")) then true
              elif ($h|contains(":")) and ($h|test("^(fc|fd|fe[89ab]|2001:db8:)|^::1$";"i")) then true
              elif ($h|test("^[0-9]+\\.[0-9]+\\.[0-9]+\\.[0-9]+$")) then
                ($h|split(".")|map(tonumber)) as $p
                | ($p|all(.>=0 and .<=255)) and
                  (($p[0] == 10) or ($p[0] == 127) or ($p[0] == 169 and $p[1] == 254)
                   or ($p[0] == 172 and $p[1] >= 16 and $p[1] <= 31)
                   or ($p[0] == 192 and $p[1] == 168)
                   or ($p[0] == 192 and $p[1] == 0 and ($p[2] == 0 or $p[2] == 2))
                   or ($p[0] == 198 and ($p[1] == 18 or $p[1] == 19 or ($p[1] == 51 and $p[2] == 100)))
                   or ($p[0] == 203 and $p[1] == 0 and $p[2] == 113)
                   or ($p[0] >= 240) or ($p[0] == 0 and ($p[1:] != [0,0,0])))
              else false end;
          .items[] | (if .kind == "Pod" then .spec else .spec.template.spec end)
          | ((.containers // []) + (.initContainers // []))[]
          | select((.image // "")|contains("/"))
          | (.image|split("/")[0]|ascii_downcase) as $authority
          | select($authority|contains(".") or contains(":") or . == "localhost")
          | ($authority|sub(":[0-9]+$";"")|ltrimstr("[")|rtrimstr("]")) as $host
          | select(["docker.io","index.docker.io","registry-1.docker.io","ghcr.io","quay.io","nvcr.io","registry.k8s.io","gcr.io"]|index($host)|not)
          | select(($host|private_host) or .name == "pxeye")
          | {authority:$authority,source:"workload-image"}
        ' "$objects" >> "$candidates" || die 'Invalid Registry workload evidence'
        if kctl registry-hosting-hint --request-timeout=15s -n kube-public get configmap local-registry-hosting --ignore-not-found -o json; then
            hint=$RESULT
            if [[ -s $hint ]]; then
                "$JQ" -r '.data["localRegistryHosting.v1"] // empty' "$hint" > "$private/hint.yaml"
                if [[ -s $private/hint.yaml ]]; then
                    "$YQ" -p yaml -o json '.' "$private/hint.yaml" > "$private/hint.json" || die 'Invalid local-registry-hosting hint'
                    "$JQ" -c 'select(type=="object") | select(.host|type=="string") | {authority:.host,source:"local-registry-hosting"}' \
                        "$private/hint.json" >> "$candidates"
                fi
            fi
        else
            printf '%s\n' 'REGISTRY_DISCOVERY_HINT_UNAVAILABLE: optional local-registry-hosting ConfigMap'
        fi
    fi
    : > "$private/validated.jsonl"
    while IFS= read -r raw; do
        authority=$("$JQ" -r '.authority' <<< "$raw")
        if parts=$(registry_url_parts "http://$authority" 2>/dev/null); then
            # Keep an explicit :80 here: discovery probes HTTPS before HTTP.
            "$JQ" -c --arg authority "$(printf '%s' "$authority" | tr '[:upper:]' '[:lower:]')" '.authority=$authority' <<< "$raw" >> "$private/validated.jsonl"
        fi
    done < "$candidates"
    "$JQ" -s 'group_by(.authority)|map({key:.[0].authority,value:(map(.source)|unique)})|from_entries' \
        "$private/validated.jsonl" > "$private/sources.json"
    count=$("$JQ" 'length' "$private/sources.json")
    ((count > 0)) || die 'No Registry candidate found; make the site Registry visible to a workload or set NICO_REGISTRY_URL'
    ((count <= 16)) || die 'Too many Registry candidates; set NICO_REGISTRY_URL to select the site endpoint'
    : > "$private/probes.jsonl"
    : > "$private/found"
    registry_curl_flags
    while IFS= read -r authority; do
        for scheme in "${schemes[@]}"; do
            status=0
            code=$(curl "${REGISTRY_CURL_FLAGS[@]}" --header 'Accept: application/json' --dump-header "$private/headers" \
                --output "$private/body" --write-out '%{http_code}' "$scheme://$authority/v2/" 2>"$private/error") || status=$?
            valid=false
            if [[ $status == 0 ]]; then
                [[ ( $code == 200 || $code == 401 ) && $(registry_v2_header "$private/headers") == registry/2.0 ]] && valid=true
                "$JQ" -nc --arg url "$scheme://$authority" --argjson status "${code:-0}" --argjson valid "$valid" \
                    '{url:$url,status:$status,registry_v2:$valid}' >> "$private/probes.jsonl"
            else
                error='Registry transport failed'
                [[ $status != 60 ]] || error='TLS certificate verification failed'
                "$JQ" -nc --arg url "$scheme://$authority" --arg error "$error" '{url:$url,error:$error}' >> "$private/probes.jsonl"
            fi
            if [[ $valid == true ]]; then
                registry_url_parts "$scheme://$authority" | "$JQ" -r '.url' >> "$private/found"
                break
            fi
            [[ $status != 60 ]] || break
        done
    done < <("$JQ" -r 'keys[]' "$private/sources.json")
    "$JQ" -s --slurpfile sources "$private/sources.json" '{sources:$sources[0],probes:.}' "$private/probes.jsonl" > "$WORK/registry-discovery.json.tmp"
    chmod 600 "$WORK/registry-discovery.json.tmp"
    mv "$WORK/registry-discovery.json.tmp" "$WORK/registry-discovery.json"
    while IFS= read -r raw; do printf 'REGISTRY_PROBE %s\n' "$raw"; done < "$private/probes.jsonl"
    found=$(sort -u "$private/found")
    [[ -n $found && $(printf '%s\n' "$found" | wc -l | tr -d ' ') == 1 ]] ||
        die 'Expected one reachable Registry V2 endpoint; check probe results or set NICO_REGISTRY_URL'
    REGISTRY_URL=$found
    REGISTRY=${REGISTRY_URL#*://}
    printf 'REGISTRY_DETECTED %s\n' "$REGISTRY_URL"
}

registry_bridge_config() {
    local output=$1 port=$2 parts host authority dial skip ca
    parts=$(registry_url_parts "$REGISTRY_URL") || die 'Invalid frozen Registry URL'
    host=$("$JQ" -r '.hostname' <<< "$parts")
    authority=$("$JQ" -r '.authority' <<< "$parts")
    dial=$("$JQ" -r '.host + ":" + (.port|tostring)' <<< "$parts")
    skip=$("$JQ" -r '.registry.skip_tls_verify // false' "$CONFIG")
    ca=$("$JQ" -r '.registry.ca_file // empty' "$CONFIG")
    "$JQ" -n --arg url "$REGISTRY_URL" --arg authority "$authority" --arg host "$host" --arg dial "$dial" \
        --argjson port "$port" --argjson skip "$skip" --arg ca "$ca" --arg ready "${BRIDGE_READY_PATH:-/__pxeye_bridge_ready}" '
      def escaped: gsub("(?<character>[.^$|?*+()\\[\\]{}\\\\])"; "\\" + .character);
      ("localhost:" + ($port|tostring)) as $bridge
      | ($authority|escaped) as $up_re
      | ("^(https?://|//)" + $up_re + "([/?#].*)?$|^http://localhost:" + ($port|tostring) + "([/?#].*)?$") as $safe
      | "{http.reverse_proxy.header.Location}" as $loc
      | ($loc + " != \"\" && (" + $loc + ".startsWith(\"//\") || " + $loc + ".matches(\"^[A-Za-z][A-Za-z0-9+.-]*:.*\")) && !" + $loc + ".matches(" + ($safe|tojson) + ")") as $unsafe
      | {admin:{disabled:true,config:{persist:false}},logging:{logs:{default:{writer:{output:"discard"}}}},apps:{http:{servers:{registry:{
          listen:["127.0.0.1:"+($port|tostring)],automatic_https:{disable:true},routes:[
            {match:[{path:[$ready]}],handle:[{handler:"static_response",status_code:204}]},
            {handle:[{handler:"reverse_proxy",upstreams:[{dial:$dial}],flush_interval:-1,
              transport:({protocol:"http",dial_timeout:15000000000,response_header_timeout:300000000000,read_timeout:300000000000,write_timeout:300000000000}
                + (if $url|startswith("https://") then {tls:({insecure_skip_verify:$skip,server_name:$host} + (if $ca!="" then {root_ca_pem_files:[$ca]} else {} end))} else {} end)),
              headers:{request:{set:{Host:[$authority]}},response:{replace:{
                Location:[{search_regexp:("^(https?://|//)"+$up_re+"([/?#].*)?$"),replace:("http://"+$bridge+"${2}")}],
                "Www-Authenticate":[{search_regexp:($url|escaped),replace:("http://"+$bridge)}]
              }}},handle_response:[{routes:[
                {match:[{expression:$unsafe}],handle:[{handler:"static_response",status_code:502,body:"Registry transport refused an offsite upload redirect"}]},
                {handle:[{handler:"copy_response"}]}
              ]}]}]}
          ]}}}}}
    ' > "$output" || die 'Cannot generate Registry transport configuration'
    chmod 600 "$output"
}

registry_bridge_start() {
    local attempt port ready auth_dir ready_attempt
    BRIDGE_PRIVATE=$(mktemp -d "$DEPLOY/private/relok-auth-XXXXXX")
    BRIDGE_READY_PATH=/__pxeye_bridge_$(basename "$BRIDGE_PRIVATE")
    chmod 700 "$BRIDGE_PRIVATE"
    auth_dir=$("$JQ" -r '.registry.docker_config_directory // empty' "$CONFIG")
    if [[ -n $auth_dir ]]; then
        "$JQ" -e '(.credsStore // "") == "" and ((.credHelpers // {})|length)==0' "$auth_dir/config.json" > /dev/null ||
            die 'Use a restricted Docker auth config with inline auths; credential-helper aliasing is unsupported'
    fi
    for ((attempt=0;attempt<12;attempt++)); do
        port=$((30000 + ((RANDOM << 1 ^ RANDOM) % 25000)))
        BRIDGE_ADDRESS=localhost:$port
        registry_bridge_config "$BRIDGE_PRIVATE/caddy.json" "$port"
        "$CADDY" validate --config "$BRIDGE_PRIVATE/caddy.json" > "$BRIDGE_PRIVATE/validate.log" 2>&1 ||
            die "Invalid Registry transport configuration; see $BRIDGE_PRIVATE/validate.log"
        env -u HTTP_PROXY -u HTTPS_PROXY -u ALL_PROXY -u http_proxy -u https_proxy -u all_proxy \
            "$CADDY" run --config "$BRIDGE_PRIVATE/caddy.json" > "$BRIDGE_PRIVATE/caddy.log" 2>&1 &
        BRIDGE_PID=$!
        ready=false
        for ((ready_attempt=0;ready_attempt<30;ready_attempt++)); do
            if ! kill -0 "$BRIDGE_PID" 2>/dev/null; then break; fi
            if [[ $(curl --silent --noproxy '*' --connect-timeout 1 --max-time 1 --output /dev/null --write-out '%{http_code}' \
                "http://127.0.0.1:$port$BRIDGE_READY_PATH" 2>/dev/null) == 204 ]] && kill -0 "$BRIDGE_PID" 2>/dev/null; then ready=true; break; fi
            sleep 0.1
        done
        [[ $ready != true ]] || break
        kill "$BRIDGE_PID" 2>/dev/null || true
        wait "$BRIDGE_PID" 2>/dev/null || true
        BRIDGE_PID=
    done
    [[ $ready == true ]] || die "Cannot reserve a loopback Registry transport port; see $BRIDGE_PRIVATE/caddy.log"
    if [[ -n $auth_dir ]]; then
        "$JQ" --arg address "$BRIDGE_ADDRESS" --arg registry "$REGISTRY" '
          (.auths // {} | to_entries | map(select((.key|rtrimstr("/")|sub("^https?://";""))==$registry)) | .[0].value // {}) as $auth
          | {auths:{($address):$auth,($registry):$auth}}
        ' "$auth_dir/config.json" > "$BRIDGE_PRIVATE/config.json"
    else
        "$JQ" -n --arg address "$BRIDGE_ADDRESS" --arg registry "$REGISTRY" '{auths:{($address):{},($registry):{}}}' > "$BRIDGE_PRIVATE/config.json"
    fi
    chmod 600 "$BRIDGE_PRIVATE/config.json"
}

registry_bridge_stop() {
    if [[ -n ${BRIDGE_PID:-} ]]; then
        kill "$BRIDGE_PID" 2>/dev/null || true
        wait "$BRIDGE_PID" 2>/dev/null || true
        BRIDGE_PID=
    fi
    [[ -z ${BRIDGE_PRIVATE:-} ]] || rm -f -- "$BRIDGE_PRIVATE/config.json"
}
