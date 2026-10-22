#!/bin/bash
# P5032 CPU USB adaptation of Grant Skidmore's mctp-stressor.sh (2025-04-09).
# Source: Allen Guan's attachment to NVBug 6891346, comment 2.
# Sends GetFirmwareParameters (PLDM type 5, command 2); does not flash firmware.
set -u
set -o pipefail
export LC_ALL=C

usage() {
    cat <<'EOF'
Usage: bash mctp-stressor-p5032.sh <16|17> [loops] [--check] [--stop-pldmd]
  16 = CPU0, 17 = CPU1 on the saved P5032 BMC configuration.
  loops defaults to 10; each run also makes one baseline request.
  --check        Read USB endpoint inventory and service state only.
  --stop-pldmd   Allow stopping active pldmd.service for the test; restore on exit.
  REQUEST_TIMEOUT=10 sets the per-request timeout in seconds (positive integer).
Run one endpoint at a time on the BMC. Save stdout and stderr to a log.
EOF
}
die() { printf 'ERROR: %s\n' "$*" >&2; exit 2; }
case "${1:-}" in -h|--help) usage; exit 0;; esac
[[ $# -ge 1 ]] || { usage; exit 2; }
eid=$1; shift
case "$eid" in 16) cpu=CPU0;; 17) cpu=CPU1;; *) die 'Select P5032 CPU EID 16 or 17.';; esac
loops=10
if [[ $# -gt 0 && $1 != --* ]]; then loops=$1; shift; fi
check_only=0
stop_pldmd=0
for arg in "$@"; do
    case "$arg" in
        --check) check_only=1;;
        --stop-pldmd) stop_pldmd=1;;
        *) die "Unknown argument: $arg";;
    esac
done
request_timeout=${REQUEST_TIMEOUT:-10}
[[ $loops =~ ^[1-9][0-9]{0,6}$ ]] || die 'loops must be 1..9999999.'
[[ $request_timeout =~ ^[1-9][0-9]{0,3}$ ]] || die 'REQUEST_TIMEOUT must be 1..9999 seconds.'
for tool in pldmtool mctp-list-eps systemctl timeout awk mktemp mkdir rmdir rm cat; do
    command -v "$tool" >/dev/null || die "Required command not found: $tool"
done

# Serialize runs because pldmd is shared by both CPUs. Never remove a lock
# belonging to another run. A stale lock after power loss requires inspection.
lock_dir=${TMPDIR:-/tmp}/p5032-mctp-stressor.lock
mkdir "$lock_dir" 2>/dev/null || die "Another run or stale lock exists: $lock_dir"
work_dir=''
restore_pldmd=0
request_pid=''
cleanup() {
    local rc=$?
    trap - EXIT INT TERM HUP
    if [[ -n $request_pid ]]; then
        kill -TERM "$request_pid" 2>/dev/null || :
        wait "$request_pid" 2>/dev/null || :
    fi
    if [[ $restore_pldmd -eq 1 ]]; then
        printf 'Restoring pldmd.service\n'
        if ! timeout -k 2 60 systemctl start pldmd.service ||
           ! systemctl is-active --quiet pldmd.service; then
            printf 'ERROR: pldmd.service did not recover; inspect systemctl status/journalctl.\n' >&2
            rc=2
        fi
    fi
    if [[ -n $work_dir ]]; then rm -f "$work_dir/request.log"; rmdir "$work_dir"; fi
    rmdir "$lock_dir"
    exit "$rc"
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
trap 'exit 129' HUP
work_dir=$(mktemp -d "${TMPDIR:-/tmp}/p5032-mctp.XXXXXX") || die 'mktemp failed.'

printf 'P5032 %s / EID %s: %s loops plus baseline; timeout %ss\n' "$cpu" "$eid" "$loops" "$request_timeout"
inventory=$(timeout -k 2 15 mctp-list-eps) || die 'Cannot read MCTP endpoint inventory.'
printf '%s\n' "$inventory"
# Require exactly one entry for this EID and require its transport to be USB.
# This accepts the pipe-delimited mctp-list-eps format in saved Neutrino logs.
printf '%s\n' "$inventory" | awk -F '|' -v target="$eid" '
    { transport=$1; id=$2; gsub(/[[:space:]]/, "", transport); gsub(/[[:space:]]/, "", id) }
    id == target { count++; if (transport == "USB") usb++ }
    END { exit !(count == 1 && usb == 1) }
' || die "EID $eid is absent, ambiguous, or not USB. Verify the live CPU mapping/namespace first."
load_state=$(systemctl show -p LoadState --value pldmd.service) || die 'Cannot inspect pldmd.service.'
[[ $load_state == loaded ]] || die 'Expected pldmd.service is not loaded; inspect this BMC layout.'
service_state=$(systemctl show -p ActiveState --value pldmd.service) || die 'Cannot inspect pldmd state.'
printf 'pldmd.service state: %s\n' "$service_state"
case "$service_state" in active|inactive|failed) ;; *) die 'pldmd is transitioning; retry after it settles.';; esac
if [[ $check_only -eq 1 ]]; then
    printf 'Preflight passed. No PLDM requests sent or service state changed. Confirm EID-to-CPU mapping before stress.\n'
    exit 0
fi
if [[ $service_state == active ]]; then
    [[ $stop_pldmd -eq 1 ]] || die 'pldmd is active. Use --stop-pldmd to permit a temporary stop and restore.'
    # Set before stopping so interrupted/partially failed stops also restore it.
    restore_pldmd=1
    timeout -k 2 60 systemctl stop pldmd.service || die 'Could not stop pldmd.service.'
    service_state=$(systemctl show -p ActiveState --value pldmd.service) || die 'Cannot confirm stopped state.'
    [[ $service_state == inactive || $service_state == failed ]] || die 'pldmd did not stop.'
fi

# Extract one complete hex Rx line, reject PLDM errors/malformed headers, and
# ignore only the instance ID when comparing payloads. Accept pldmtool prefixes.
parse_response() {
    awk '
    tolower($0) ~ /(^|[^[:alnum:]_])rx:[[:space:]]*/ {
        count++; line=tolower($0); sub(/^.*rx:[[:space:]]*/, "", line)
        n=split(line, bytes, /[[:space:]]+/)
        if (bytes[n] == "") n--
        # Header + fixed GetFirmwareParameters response fields = at least 14 bytes.
        if (n < 14) bad=1
        for (i=1; i<=n; i++) {
            sub(/^0x/, "", bytes[i])
            if (bytes[i] !~ /^[0-9a-f][0-9a-f]$/) bad=1
        }
        if (bytes[1] !~ /^[01][0-9a-f]$/ || bytes[2] != "05" || bytes[3] != "02" || bytes[4] != "00") bad=1
        normalized=""
        for (i=2; i<=n; i++) normalized=normalized (i==2 ? "" : " ") bytes[i]
    }
    END { if (count != 1 || bad) exit 1; print normalized }
    ' "$work_dir/request.log"
}
request() {
    local rc
    LG2_FORCE_STDERR=1 timeout -k 2 "$request_timeout" \
        pldmtool raw -m "$eid" -v -d 0x80 0x05 0x02 >"$work_dir/request.log" 2>&1 &
    request_pid=$!
    wait "$request_pid"; rc=$?
    request_pid=''
    if [[ $rc -ne 0 ]]; then
        printf 'Request failed: exit=%s (124/137 indicates timeout/kill)\n' "$rc" >&2
        return 1
    fi
    response=$(parse_response) || { printf 'Missing, malformed, multiple, or unsuccessful PLDM response\n' >&2; return 1; }
}
printf 'Capturing baseline GetFirmwareParameters response\n'
request || { cat "$work_dir/request.log"; die 'Baseline request failed; no stress iterations started.'; }
golden_response=$response
printf 'Baseline raw output:\n'; cat "$work_dir/request.log"
errors=0
for ((iter=1; iter<=loops; iter++)); do
    if ! request; then
        errors=$((errors + 1))
        printf 'FAIL iteration=%s/%s\n' "$iter" "$loops"
        cat "$work_dir/request.log"
    elif [[ $response != "$golden_response" ]]; then
        errors=$((errors + 1))
        printf 'FAIL iteration=%s/%s: response differs from baseline\nExpected: %s\nGot: %s\n' "$iter" "$loops" "$golden_response" "$response"
    else
        printf 'PASS iteration=%s/%s\n' "$iter" "$loops"
    fi
done
printf 'SUMMARY cpu=%s eid=%s attempted=%s passed=%s failed=%s\n' "$cpu" "$eid" "$loops" "$((loops-errors))" "$errors"
[[ $errors -eq 0 ]]
