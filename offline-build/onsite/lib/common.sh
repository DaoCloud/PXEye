#!/usr/bin/env bash
# Shared Linux/Bash primitives. No host Python is used by the onsite runner.

die() {
    printf '%s\n' "ERROR: $*" >&2
    if [[ ${JOURNAL_READY:-false} == true ]]; then onsite_failure 1 "${BASH_LINENO[0]:-unknown}"; fi
    exit 1
}
now() { date -u '+%Y-%m-%dT%H:%M:%SZ'; }
sha() { sha256sum -- "$1" | awk '{print $1}'; }

jq_atomic() {
    local file=$1 filter=$2 temporary
    shift 2
    mkdir -p -- "$(dirname -- "$file")"
    temporary=$(mktemp "${file}.tmp.XXXXXX")
    if [[ -f $file ]]; then
        "$JQ" "$@" "$filter" "$file" > "$temporary"
    else
        printf '{}\n' | "$JQ" "$@" "$filter" > "$temporary"
    fi
    chmod 600 "$temporary"
    # fdatasync only this new state file; syncfs (-f) can wait on unrelated
    # writes across a shared host filesystem.
    sync -d "$temporary"
    mv -f -- "$temporary" "$file"
}

state_mark() {
    jq_atomic "$STATE" '.steps[$key]=$value' --arg key "$1" --argjson value "$2"
}
state_has() { "$JQ" -e --arg key "$1" '.steps[$key] != null' "$STATE" >/dev/null; }

run() {
    local label=$1 status started ended history
    shift
    [[ $label =~ ^[A-Za-z0-9._-]+$ ]] || die 'Invalid command log label'
    mkdir -p "$DEPLOY/private"
    RESULT="$DEPLOY/private/$label.stdout"
    started=$(date +%s)
    printf '%s RUN ' "$(now)"
    printf '%q ' "$@"
    printf '\n'
    if timeout --signal=TERM --kill-after=10 "${COMMAND_TIMEOUT:-3600}" "$@" >"$RESULT" 2>"$DEPLOY/private/$label.stderr"; then
        status=0
    else
        status=$?
    fi
    chmod 600 "$RESULT" "$DEPLOY/private/$label.stderr"
    history=$(mktemp -d "$DEPLOY/private/$label.attempt-XXXXXX")
    cp "$RESULT" "$history/stdout"
    cp "$DEPLOY/private/$label.stderr" "$history/stderr"
    ended=$(date +%s)
    "$JQ" -nc --arg step "$label" --arg logs "$history" --argjson seconds "$((ended-started))" --argjson exit_code "$status" \
        '{step:$step,seconds:$seconds,exit_code:$exit_code,logs:$logs}' >> "$DEPLOY/timings.jsonl"
    if ((status)); then
        printf '%s failed (exit %s); see %s/private/%s.stderr\n' "$label" "$status" "$DEPLOY" "$label" >&2
    fi
    return "$status"
}
kctl() { local label=$1; shift; run "$label" kubectl --context "$CONTEXT" "$@"; }
hrun() { local label=$1; shift; run "$label" "$HELM" --kube-context "$CONTEXT" "$@"; }

merge_yaml() {
    local first=$1 second=$2 output=$3
    "$YQ" eval-all 'select(fileIndex == 0) * select(fileIndex == 1)' "$first" "$second" > "$output"
}

safe_extract() {
    local archive=$1 destination=$2 limit=${3:-0} listing names total
    [[ -f $archive && ! -L $archive ]] || die "Missing or unsafe archive: $archive"
    mkdir -p -- "$destination"
    listing=$(mktemp "${WORK}/.tar-list.XXXXXX")
    names=$(mktemp "${WORK}/.tar-names.XXXXXX")
    LC_ALL=C tar --list --verbose --numeric-owner --full-time --quoting-style=escape --file "$archive" > "$listing"
    # GNU tar's verbose listing has five metadata fields before the member name.
    # Escaped names are rejected so newline/tab/backslash names cannot confuse it.
    LC_ALL=C awk '
      {
        type=substr($0,1,1)
        if (type!="-" && type!="d") {print "Archive links/special files are unsupported" > "/dev/stderr"; exit 1}
        line=$0
        sub(/^[^ ]+ +[^ ]+ +[0-9]+ +[^ ]+ +[^ ]+ +/, "", line)
        if (line==$0 || line=="" || line ~ /\\/ || line ~ /[[:cntrl:]]/ || line ~ /^\// || line ~ /(^|\/)\.\.(\/|$)/ || line ~ /\/\// || line ~ /(^|\/)\.(\/|$)/) {
          print "Unsafe archive member" > "/dev/stderr"; exit 1
        }
        sub(/\/$/, "", line)
        if (seen[line]++) {print "Duplicate archive member" > "/dev/stderr"; exit 1}
        print line
      }' "$listing" > "$names"
    total=$(awk '{sum += $3} END {printf "%.0f",sum}' "$listing")
    [[ $total =~ ^[0-9]+$ ]] || die 'Cannot determine archive expansion size'
    if ((limit > 0 && total > limit)); then die 'Archive expansion exceeds available space or configured limit'; fi
    tar --extract --file "$archive" --directory "$destination" --no-same-owner --no-same-permissions \
        --delay-directory-restore --keep-old-files
    rm -f -- "$listing" "$names"
}

pack_chart() {
    local root=$1 output=$2
    tar --create --gzip --file "$output" --directory "$(dirname -- "$root")" -- "$(basename -- "$root")"
}

verify_bundle() {
    local inventory="$BUNDLE/manifests/file-inventory.json" record="$WORK/input-verification.json"
    local digest stamps path bytes expected actual listed chart count
    [[ -f $inventory && ! -L $inventory ]] || die 'Missing bundle file inventory'
    digest=$(sha "$inventory")
    if [[ -f $record ]]; then
        [[ $("$JQ" -r '.inventory_sha256' "$record") == "$digest" ]] || die 'Bundle inventory changed; use a different archive name'
    fi
    [[ -z $(find "$BUNDLE" -type l -print -quit) ]] || die 'Bundle contains a symlink'
    stamps=$(find "$BUNDLE" -type f -printf '%P %s %T@ %C@ %i\0' | LC_ALL=C sort -z | sha256sum | awk '{print $1}')
    if [[ -f $record ]] && [[ $("$JQ" -r '.stats_sha256' "$record") == "$stamps" ]]; then
        printf 'REUSE_INPUT_VERIFICATION; input file metadata unchanged\n'
        return
    fi
    "$JQ" -e '.files|type=="array" and all(.[]; (.path|type=="string" and length>0 and (test("(^/|(^|/)\\.\\.(/|$)|[\\\\\\t\\r\\n])")|not)) and (.bytes|type=="number" and .>=0 and floor==.) and (.sha256|test("^[a-f0-9]{64}$")))' "$inventory" >/dev/null
    actual=$(mktemp "$WORK/.actual-files.XXXXXX")
    listed=$(mktemp "$WORK/.listed-files.XXXXXX")
    find "$BUNDLE" -type f -printf '%P\n' | LC_ALL=C sort > "$actual"
    { "$JQ" -r '.files[].path' "$inventory"; printf '%s\n' manifests/file-inventory.json; } | LC_ALL=C sort > "$listed"
    cmp -s "$actual" "$listed" || die 'Unlisted, missing or duplicate files in delivery'
    while IFS=$'\t' read -r bytes expected path; do
        [[ -f $BUNDLE/$path && ! -L $BUNDLE/$path ]] || die "Missing/unsafe inventory file: $path"
        [[ $(stat -c %s -- "$BUNDLE/$path") == "$bytes" ]] || die "File size mismatch: $path"
        [[ $(sha "$BUNDLE/$path") == "$expected" ]] || die "Checksum mismatch: $path"
    done < <("$JQ" -r '.files[] | [.bytes,.sha256,.path] | @tsv' "$inventory")
    while IFS= read -r chart; do
        [[ $chart != /* && $chart != *'..'* ]] || die 'Unsafe relocation path'
        count=$(tar --list --file "$BUNDLE/$chart" | LC_ALL=C sort | \
            awk '$0=="hints.yaml"||$0=="original-chart/Chart.yaml"||$0=="original-chart/values.yaml"||$0=="images.tar" {n++} END {print n+0}')
        [[ $count == 4 ]] || die 'Invalid relok8s intermediate bundle'
    done < <("$JQ" -r '.charts[].relocation' "$BUNDLE/bundle.json")
    jq_atomic "$record" '{inventory_sha256:$digest,stats_sha256:$stamps}' --arg digest "$digest" --arg stamps "$stamps"
    count=$(wc -l < "$listed")
    rm -f -- "$actual" "$listed"
    printf 'HELM_BUNDLE_VERIFIED %s files\n' "$count"
}

stage() {
    local key=$1 title=$2 attempt
    shift 2
    CURRENT_STAGE=$key
    STAGE_STARTED=$(date +%s)
    jq_atomic "$PROGRESS" '.status="running" | .current_stage=$key | del(.error) | .updated_at=$at | .stages[$key]=((.stages[$key]//{}) + {status:"running",attempt:((.stages[$key].attempt//0)+1),title:$title,started_at:$at}) | del(.stages[$key].error)' \
        --arg key "$key" --arg title "$title" --arg at "$(now)"
    attempt=$("$JQ" -r --arg key "$key" '.stages[$key].attempt' "$PROGRESS")
    printf 'STAGE [%s] %s (attempt %s)\n' "$key" "$title" "$attempt"
    "$@"
    jq_atomic "$PROGRESS" '.stages[$key] += {status:"completed",ended_at:$at,seconds:$seconds} | .updated_at=$at' \
        --arg key "$key" --arg at "$(now)" --argjson seconds "$(($(date +%s)-STAGE_STARTED))"
    "$JQ" -c --arg key "$key" '{stage:$key}+ .stages[$key]' "$PROGRESS" >> "$WORK/events.jsonl"
    printf 'DONE [%s]\n' "$key"
    CURRENT_STAGE=
}

onsite_failure() {
    local status=${1:-1} line=${2:-unknown}
    trap - ERR INT TERM
    set +e
    if [[ -n ${PROGRESS:-} && -f $PROGRESS ]]; then
        jq_atomic "$PROGRESS" '.status="failed" | .updated_at=$at | .error=$error | if $key!="" then .stages[$key] += {status:"failed",ended_at:$at,error:$error} else . end' \
            --arg at "$(now)" --arg error "Command failed at line $line (exit $status)" --arg key "${CURRENT_STAGE:-}"
        if [[ -n ${CURRENT_STAGE:-} ]]; then
            "$JQ" -c --arg key "$CURRENT_STAGE" '{stage:$key}+.stages[$key]' "$PROGRESS" >> "$WORK/events.jsonl"
        fi
        printf 'FAILED [%s]; fix the cause and rerun the same command; progress: %s\n' "${CURRENT_STAGE:-startup}" "$PROGRESS" >&2
    fi
    exit "$status"
}
