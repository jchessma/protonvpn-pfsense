# protonvpn-pfsense

Scripts to find the fastest ProtonVPN OpenVPN server in a chosen set of
US states, and automatically point a pfSense firewall at it.

## Background

I used to pull this data from ProtonVPN's own API and identify the
lowest-load server directly. After ProtonVPN deprecated that API, this
project switched to scraping the ProtonVPN account download page instead
(username, password, mailbox password, and TOTP). Because scraping requires
a headless Chrome browser, and I didn't want that running directly on the
pfSense box, the scrape happens on a separate machine; only plain HTTPS
calls need to reach pfSense.

## How it works

Two scripts, meant to be chained (`scrape-ng-v2.py && update_pfsense.py`),
typically from cron on the off-box machine:

- **`scrape-ng-v2.py`** logs into ProtonVPN's account page with a headless
  Chrome browser, and reads the OpenVPN server table for the configured
  country. It filters to servers in the configured states, checks each
  row's own P2P-support icon live on the page (no manual server list to
  maintain), picks the lowest-utilization match, downloads that server's
  actual `.ovpn` config file, and extracts its `remote <ip> <port>` entry
  point IP. That IP is written to `OUTPUT_FILE`.
- **`update_pfsense.py`** reads that IP and pushes it into pfSense entirely
  over the [pfSense REST API](https://github.com/jaredhendrickson13/pfsense-api)
  (PATCH the DNS Resolver host override, apply DNS changes, then restart
  the matching OpenVPN client) - no SSH or local pfSense execution required.
  A failed DNS update will not trigger a pointless OpenVPN restart.

Everything tunable - selectors, timeouts, the state list, URLs, wait
durations - lives in `config.json` and is reloaded fresh on every run, so
adjusting to a ProtonVPN page change doesn't require editing code.

## Requirements

- Python 3 with the packages in `requirements.txt` (`pip install -r requirements.txt`)
- Google Chrome or Chromium installed on the machine running
  `scrape-ng-v2.py` (install the real `.deb`, not a snap package - snap's
  confinement breaks headless automation tooling like this)
- A ProtonVPN account with OpenVPN/TOTP credentials
- A pfSense firewall with the
  [pfSense REST API package](https://github.com/jaredhendrickson13/pfsense-api)
  installed, an API key, and an existing DNS Resolver host override for
  whatever hostname you want kept pointed at the fastest server (e.g.
  `fastest.protonvpn.com`) - the script updates this override, it does not
  create one

## Setup

1. `python3 -m venv venv && venv/bin/pip install -r requirements.txt`
2. `cp config.example.json config.json`, then fill in your ProtonVPN
   credentials, pfSense API details, and desired states. `chmod 600
   config.json` since it holds live secrets.
3. Run the pair, from this directory (both scripts use paths relative to
   the working directory):
   ```
   venv/bin/python3 scrape-ng-v2.py && venv/bin/python3 update_pfsense.py
   ```
4. Wire that command into cron on whatever schedule you want the fastest
   server re-checked.

## Security notes

- `config.json` contains your ProtonVPN password, mailbox password, TOTP
  secret, and pfSense API key in plaintext. Keep it `chmod 600` and never
  commit it (it's gitignored here for exactly that reason).
- If a pfSense API key is ever exposed (committed, logged, pasted
  somewhere public), rotate it immediately in the pfSense REST API package
  settings.
