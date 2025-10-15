#!/bin/bash

tmpIPFile="/tmp/tmpIPFile.txt"

cd /home/josh/dev/pfsense-proton
source venv/bin/activate

python3 /home/josh/dev/pfsense-proton/scrape-ng.py > $tmpIPFile

scp $tmpIPFile admin@<IP/FQDN of pfSense>:
