#!/usr/local/bin/bash
#
# Downloads the list of ProtonVPN servers from https://api.protonmail.ch/vpn/logicals parses the list looking for appropriate servers by load (less than 40% utilized and greater than 0%
# (to avoid servers that are down) and feature (feature==0). Puts that information into $tmp which. The IP for $tmp is looked up and the result used with a API call to pfSense to update
# the OpenVPN client address. The script then waits 30s and restarts the OpenVPN client.

logfile='/var/log/find_vpn.log'

log_data () {
                date=$(date)
                echo "$date $1" >> $logfile
                echo "$date $1"
}

log_data "Reading file tmpIPFile.txt to $tmp2 and $tmp"

tmp2=`cat /root/tmpIPFile.txt`
tmp=`cat /root/tmpIPFile.txt`

log_data "Copying $tmp2 to backup for reference purposes"
cp /root/tmpIPFile.txt /root/tmpIPFile.bak

log_data "Changing DNS to IP $tmp2 for $tmp"

# Build the data string
printf -v data '{"id": 0, "host": "fastest", "domain": "protonvpn.com", "ip": ["%s"], "descr": "%s"}' "${tmp2}" "${tmp}"

# Use curl to PATCH the new IP into pfSense via the API
curl_output=`curl -k -X PATCH https://home.chessman.net/api/v2/services/dns_resolver/host_override -H 'accept:application/json' -H 'Content-Type: application/json' -H 'X-API-Key: <Insert API key here>' -d "${data}"` | jq

log_data "Output from curl statement: $curl_output"

log_data "Sleeping for 5s..."
sleep 5

log_data "Applying changes to dns_resolver"
# Use curl to restart the DNS service (via POST)
curl_output=`curl -k -X POST  https://home.chessman.net/api/v2/services/dns_resolver/apply -H 'accept:application/json' -H 'Content-Type: application/json' -H 'X-API-Key: <Insert API key here>'` | jq

log_data "Sleeping for 30s..."
# Sleep for 30s
sleep 30

log_data "Restarting VPN..."
# Use pfSsh.php to restart the apporpriate OpenVPN client
openvpn_restart=`pfSsh.php playback svc restart openvpn client 3`

log_data "OpenVPN restart output: $openvpn_restart"
