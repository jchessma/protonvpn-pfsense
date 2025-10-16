# protonvpn-pfsense
Scripts to scrape ProtonVPN's VPN status page for a region and identify the fastest server

Previously I used ProtonVPN's own API's to pull a list of available servers and identify the one with the lowest load. I then took this server, updated a hostname in my pfSense instance and restarted my pfSense ProtonVPN OpenVPN client. I ran this script daily and it allowed me to always have a connection to a (at least in theory) lightly loaded server.

After ProtonVPN deprecated that functionality I needed a new approach. While nowhere near as elegant this is what I've come up with. Instead of using the API I scrape the screen of the ProtonVPN download page (using a username, password, mailbox password, and TOTP) and extract the servers and their associated loads. I then determine the lightest load server (from a list of the closes servers) and update a file. Because I am screen scraping I use a headless Chrome browser and for seccurity reasons I did not want to do that directly on my pfSense box. Thus I perform the scraping on a separate system and upload a file containing the IP of the new server to my pfSense box. A separate script on the pfSense box then updates the DNS setting and restarts the OpenVPN client.

Requirements are pretty limited. Mainly you need a ProtonVPN account, appropriate ProtonVPN API access, SSH access to the pfSense server, and the excellent pfSense REST API from jaredhendrickson31 (https://github.com/jaredhendrickson13/pfsense-api) installed on your pfSense box.

There are three separate scripts here (that's how I chose to do things, there are different, and likely better, ways to achieve the same goals):
 * scraper.py - Python script to scrape the ProtonVPN downloads page screen
 * config.json - Configuration file (JSON format) containing the username, password, mailbox password, and TOTP secret key
 * scrapeProton.sh - BASH script to execute the above Python script, store the resulting IP in a file, and SCP the file to a pfSense server
 * updateVPN.sh - BASH script that I run on my pfSense box to update the DNS name (I use "fastest.protonvpn.com"), restart DNS, and restart the OpenVPN client

Within Python you need the following libraries installed: pyotp, undetected_chromedriver, selenium, time, inspect

For the Python script to work you need to ensure the above Python 3 libraries are installed (pip3 install ...) and update the script as follows:
 * Replace the username, password, mailbox password, and TOTP secret key as appropriate in the config.json file
 * Update the list of states (I'm US based and wrote this on that basis but there is no reason it can't be easily modified to support other regions, on my todo list)
 * Change the output filename if desired
 * Update the list of keys/values of the chosen specific servers and their associated IP's (also something on my todo list to make this more automated)

For the BASH script (scrapeProton.sh) to run you need to update the IP/username (and ensure you can SSH/SCP to your pfSense server)
For the BASH script (updateVPN.sh) to run you need to update the pfSense API key appropriately

That's it. Once you have made the updates the script should run and return the IP of the server with the lowest load (from the list of servers).

