#!/usr/local/bin/bash
#
# Runs on the pfSense box itself. Reads a ProtonVPN server IP (written by an
# off-box scraper - see scrape-ng-v2.py - and copied to IP_FILE) and updates
# pfSense's DNS Resolver host override to point at it, then restarts the
# matching OpenVPN client. The DNS update goes through the pfSense REST API;
# the restart uses the local pfSsh.php playback mechanism since this script
# runs directly on the firewall.
#
# All environment-specific values (API key, host, DNS names, paths, wait
# times) live in find_vpn.conf, sourced below - never hardcode them here.

set -u

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CONFIG_FILE="${SCRIPT_DIR}/find_vpn.conf"

if [ ! -f "$CONFIG_FILE" ]; then
    echo "Configuration file not found: $CONFIG_FILE (copy find_vpn.conf.example and fill it in)" >&2
    exit 1
fi
# shellcheck source=find_vpn.conf
. "$CONFIG_FILE"

: "${PFSENSE_BASE_URL:?PFSENSE_BASE_URL not set in $CONFIG_FILE}"
: "${PFSENSE_API_KEY:?PFSENSE_API_KEY not set in $CONFIG_FILE}"
: "${DNS_HOST:?DNS_HOST not set in $CONFIG_FILE}"
: "${DNS_DOMAIN:?DNS_DOMAIN not set in $CONFIG_FILE}"
: "${OPENVPN_VPNID:?OPENVPN_VPNID not set in $CONFIG_FILE}"
: "${IP_FILE:?IP_FILE not set in $CONFIG_FILE}"
: "${LOG_FILE:=/var/log/find_vpn.log}"
: "${BACKUP_FILE:=${IP_FILE}.bak}"
: "${PFSENSE_VERIFY_TLS:=false}"
: "${APPLY_WAIT_SECONDS:=5}"
: "${RESTART_WAIT_SECONDS:=30}"

curl_insecure_flag=""
if [ "$PFSENSE_VERIFY_TLS" = "false" ]; then
    curl_insecure_flag="-k"
fi

# Writes to LOG_FILE and echoes to stderr (not stdout) so this is always
# safe to call from inside a function whose stdout is being captured via
# command substitution elsewhere in this script.
log_data() {
    local line
    line="$(date) $1"
    echo "$line" >> "$LOG_FILE"
    echo "$line" >&2
}

api_request() {
    # api_request METHOD PATH [DATA]
    local method="$1" path="$2" data="${3:-}"
    local args=(-s -w '\n%{http_code}')
    if [ -n "$curl_insecure_flag" ]; then
        args+=("$curl_insecure_flag")
    fi
    args+=(-X "$method" "${PFSENSE_BASE_URL}${path}" \
        -H 'accept: application/json' -H 'Content-Type: application/json' \
        -H "X-API-Key: ${PFSENSE_API_KEY}")
    if [ -n "$data" ]; then
        args+=(-d "$data")
    fi
    curl "${args[@]}"
}

# api_request's raw output is "<json-body>\n<http_status>". This splits it
# apart and treats both a non-2xx HTTP status and the API's own embedded
# "code" field as failure - pfSense's REST API always reports its own
# status/code inside the JSON body regardless of the transport-level HTTP
# status, so either one failing means the call did not succeed.
check_response() {
    local raw="$1" context="$2"
    local http_status body api_code
    http_status="${raw##*$'\n'}"
    body="${raw%$'\n'*}"
    api_code=$(echo "$body" | jq -r '.code // empty' 2>/dev/null)

    if [ "${http_status:0:1}" != "2" ] || { [ -n "$api_code" ] && [ "$api_code" -ge 300 ]; }; then
        log_data "ERROR: $context failed (HTTP $http_status): $body"
        return 1
    fi
    log_data "$context succeeded: $body"
    echo "$body"
}

if [ ! -f "$IP_FILE" ]; then
    log_data "ERROR: $IP_FILE does not exist. Nothing to do."
    exit 1
fi

new_ip=$(cat "$IP_FILE")
if [ -z "$new_ip" ]; then
    log_data "ERROR: $IP_FILE is empty."
    exit 1
fi

log_data "Read best server IP: $new_ip"
cp "$IP_FILE" "$BACKUP_FILE"

# Look up the host override's real id - never assume it's 0, since that
# shifts if overrides are ever added/reordered in the pfSense UI.
lookup_raw=$(api_request GET "/api/v2/services/dns_resolver/host_overrides")
lookup_body=$(check_response "$lookup_raw" "Host override lookup") || exit 1

override_id=$(echo "$lookup_body" | jq -r --arg host "$DNS_HOST" --arg domain "$DNS_DOMAIN" \
    '.data[] | select(.host == $host and .domain == $domain) | .id' | head -1)

if [ -z "$override_id" ]; then
    log_data "ERROR: no existing DNS Resolver host override found for ${DNS_HOST}.${DNS_DOMAIN} - create it once in the pfSense UI before running this script."
    exit 1
fi

log_data "Found host override id=$override_id for ${DNS_HOST}.${DNS_DOMAIN}"

printf -v data '{"id": %s, "host": "%s", "domain": "%s", "ip": ["%s"], "descr": "Fastest ProtonVPN server, updated %s"}' \
    "$override_id" "$DNS_HOST" "$DNS_DOMAIN" "$new_ip" "$(date '+%Y-%m-%d %H:%M:%S')"

patch_raw=$(api_request PATCH "/api/v2/services/dns_resolver/host_override" "$data")
check_response "$patch_raw" "Host override update" >/dev/null || exit 1

apply_raw=$(api_request POST "/api/v2/services/dns_resolver/apply")
check_response "$apply_raw" "DNS Resolver apply" >/dev/null || exit 1

log_data "Waiting ${APPLY_WAIT_SECONDS}s for DNS apply to settle..."
sleep "$APPLY_WAIT_SECONDS"

log_data "Waiting ${RESTART_WAIT_SECONDS}s before restarting OpenVPN..."
sleep "$RESTART_WAIT_SECONDS"

log_data "Restarting OpenVPN client (vpnid=$OPENVPN_VPNID)..."
openvpn_restart=$(pfSsh.php playback svc restart openvpn client "$OPENVPN_VPNID" 2>&1)
restart_status=$?
log_data "OpenVPN restart output: $openvpn_restart"

if [ "$restart_status" -ne 0 ]; then
    log_data "ERROR: OpenVPN restart command exited with status $restart_status"
    exit 1
fi

log_data "Done."
exit 0
