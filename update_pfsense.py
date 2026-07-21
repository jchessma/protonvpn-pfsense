"""Pushes the fastest-server IP (written by scrape-ng-v2.py) into pfSense.

Replaces the old find_vpn.sh. Everything here happens over the pfSense REST
API (https://pfrest.org/ - the jaredhendrickson13/pfsense-api project) rather
than requiring a locally-executed `pfSsh.php`, so this script can run
anywhere that can reach pfSense's web UI - it does not need to run on the
firewall itself.

Steps, all via the API:
  1. Read the winning IP from OUTPUT_FILE (written by scrape-ng-v2.py).
  2. Look up the existing DNS Resolver host override for DNS_HOST.DNS_DOMAIN
     to get its real id (never assume it's 0 - it shifts if overrides are
     added/removed/reordered in the UI).
  3. PATCH that host override with the new IP.
  4. POST /services/dns_resolver/apply to activate the change.
  5. Look up the running OpenVPN client matching OPENVPN_VPNID to get the
     Service model's id (a positional index, distinct from vpnid).
  6. POST /status/service with action=restart for that service.

Every step checks the HTTP status and the API's own "status" field before
moving on - unlike the old script, a failed DNS update will NOT be followed
by a pointless OpenVPN restart.
"""
import json
import os
import sys
from datetime import datetime
from typing import Any, Dict

import requests
import urllib3

# CONFIG_FILE can't itself live inside config.json (chicken-and-egg), so it's
# the one true constant. The values below are fallback defaults only - main()
# overrides them from config.json on every run.
CONFIG_FILE = "config.json"
LOG_FILE = "/var/log/find_vpn.log" if os.path.isdir("/var/log") and os.access("/var/log", os.W_OK) else "update_pfsense.log"
APPLY_WAIT_SECONDS = 5
RESTART_WAIT_SECONDS = 30


def log(message: str) -> None:
    line = f"{datetime.now().isoformat(timespec='seconds')} {message}"
    print(line)
    try:
        with open(LOG_FILE, "a") as f:
            f.write(line + "\n")
    except OSError:
        pass  # Logging is best-effort; never fail the run over it.


def load_config(path: str) -> Dict[str, Any]:
    if not os.path.exists(path):
        raise FileNotFoundError(f"Configuration file not found: {path}")
    with open(path, "r") as f:
        config = json.load(f)

    required = ["PFSENSE_BASE_URL", "PFSENSE_API_KEY", "DNS_HOST", "DNS_DOMAIN", "OPENVPN_VPNID"]
    missing = [k for k in required if not config.get(k) and config.get(k) != 0]
    if missing:
        raise ValueError(f"Missing required config keys: {', '.join(missing)}")
    return config


def api_request(config: Dict[str, Any], method: str, path: str, **kwargs) -> Dict[str, Any]:
    url = config["PFSENSE_BASE_URL"].rstrip("/") + path
    verify_tls = config.get("PFSENSE_VERIFY_TLS", True)
    if not verify_tls:
        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

    headers = {
        "Accept": "application/json",
        "Content-Type": "application/json",
        "X-API-Key": config["PFSENSE_API_KEY"],
    }
    response = requests.request(method, url, headers=headers, verify=verify_tls, timeout=30, **kwargs)

    try:
        body = response.json()
    except ValueError:
        raise RuntimeError(f"{method} {path} returned non-JSON response (HTTP {response.status_code}): {response.text[:500]}")

    # pfSense REST API responses always carry their own {"code": <http status>, "status": "ok"|...}
    # regardless of the transport-level HTTP status, so check both.
    if not response.ok or body.get("code", 500) >= 300:
        raise RuntimeError(f"{method} {path} failed: {json.dumps(body)[:500]}")

    return body


def find_host_override_id(config: Dict[str, Any]) -> int:
    body = api_request(config, "GET", "/api/v2/services/dns_resolver/host_overrides")
    for entry in body.get("data", []):
        if entry.get("host") == config["DNS_HOST"] and entry.get("domain") == config["DNS_DOMAIN"]:
            return entry["id"]
    raise RuntimeError(
        f"No existing DNS Resolver host override found for "
        f"{config['DNS_HOST']}.{config['DNS_DOMAIN']} - create it once in the "
        f"pfSense UI (Services > DNS Resolver > Host Overrides) before running this script."
    )


def find_openvpn_service_id(config: Dict[str, Any]) -> int:
    body = api_request(config, "GET", "/api/v2/status/services")
    target_vpnid = int(config["OPENVPN_VPNID"])
    for entry in body.get("data", []):
        if entry.get("name") == "openvpn" and str(entry.get("vpnid")) == str(target_vpnid):
            return entry["id"]
    raise RuntimeError(f"No running OpenVPN client found with vpnid={target_vpnid}.")


def main() -> int:
    global LOG_FILE, APPLY_WAIT_SECONDS, RESTART_WAIT_SECONDS

    config = load_config(CONFIG_FILE)
    LOG_FILE = config.get("LOG_FILE", LOG_FILE)
    APPLY_WAIT_SECONDS = config.get("APPLY_WAIT_SECONDS", APPLY_WAIT_SECONDS)
    RESTART_WAIT_SECONDS = config.get("RESTART_WAIT_SECONDS", RESTART_WAIT_SECONDS)

    output_file = config.get("OUTPUT_FILE", "/tmp/tmpIPFile.txt")

    if not os.path.exists(output_file):
        log(f"ERROR: {output_file} does not exist. Run scrape-ng-v2.py first.")
        return 1

    with open(output_file, "r") as f:
        new_ip = f.read().strip()

    if not new_ip:
        log(f"ERROR: {output_file} is empty.")
        return 1

    log(f"Read best server IP: {new_ip}")

    try:
        override_id = find_host_override_id(config)
        log(f"Found host override id={override_id} for {config['DNS_HOST']}.{config['DNS_DOMAIN']}")

        api_request(
            config, "PATCH", "/api/v2/services/dns_resolver/host_override",
            json={
                "id": override_id,
                "host": config["DNS_HOST"],
                "domain": config["DNS_DOMAIN"],
                "ip": [new_ip],
                "descr": f"Fastest ProtonVPN server, updated {datetime.now().isoformat(timespec='seconds')}",
            },
        )
        log(f"Updated host override -> {new_ip}")

        api_request(config, "POST", "/api/v2/services/dns_resolver/apply")
        log("Applied DNS Resolver changes")

    except Exception as e:
        log(f"ERROR updating DNS: {e}")
        return 1

    log(f"Waiting {APPLY_WAIT_SECONDS}s for DNS apply to settle...")
    import time
    time.sleep(APPLY_WAIT_SECONDS)

    try:
        service_id = find_openvpn_service_id(config)
        log(f"Found OpenVPN client service id={service_id} (vpnid={config['OPENVPN_VPNID']})")
    except Exception as e:
        log(f"ERROR locating OpenVPN client service, NOT restarting: {e}")
        return 1

    log(f"Waiting {RESTART_WAIT_SECONDS}s before restarting OpenVPN...")
    time.sleep(RESTART_WAIT_SECONDS)

    try:
        api_request(
            config, "POST", "/api/v2/status/service",
            json={"id": service_id, "name": "openvpn", "action": "restart"},
        )
        log(f"Restarted OpenVPN client (vpnid={config['OPENVPN_VPNID']})")
    except Exception as e:
        log(f"ERROR restarting OpenVPN client: {e}")
        return 1

    log("Done.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
