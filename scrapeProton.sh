#!/bin/bash

tmpIPFile="best_server_ip.txt" # Change this to whatever the filename in the primary script is

cd /home/josh/dev/pfsense-proton
source venv/bin/activate

python3 /home/josh/dev/pfsense-proton/scrape-ng.py

scp $tmpIPFile admin@<IP/FQDN of pfSense>:
