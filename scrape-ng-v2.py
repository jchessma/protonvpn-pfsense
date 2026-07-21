import pyotp
import undetected_chromedriver as uc
from selenium.webdriver.common.by import By
from selenium.webdriver.remote.webelement import WebElement
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, NoSuchElementException, WebDriverException
import inspect
import shutil
import subprocess
import sys
import tempfile
import time
from typing import List, Optional, Tuple
import re
import json
import os

# --- BOOTSTRAP CONSTANT ---
# CONFIG_FILE can't itself live inside config.json (chicken-and-egg), so it's
# the one true constant. Every value below is a fallback default only - the
# real value is (re)loaded from config.json by load_config() on every run, so
# tuning a selector/timeout/URL/state list never requires a code change.
CONFIG_FILE = "config.json"

# --- RUNTIME CONFIG (populated by load_config(); values below are fallback
# defaults used only if a key is absent from config.json) ---
USERNAME = ""
PASSWORD = ""
MAILBOX_PASSWORD = ""
TOTP_SECRET_KEY = ""

OUTPUT_FILE_NAME = "/tmp/tmpIPFile.txt"
LOGIN_URL = "https://account.protonvpn.com/login"
DOWNLOAD_URL = "https://account.protonvpn.com/downloads"

STATES = ["MA", "NY", "NJ"]
# Countries are rendered as collapsible <details><summary>Country Name</summary>...</details>
# blocks. Matching on the visible country name is far more resilient to page changes than a
# fixed positional index (the old `details[122]` approach broke every time Proton
# added/removed/reordered a country).
COUNTRY_NAME = "United States"

USER_ID = "username"
PASS_ID = "password"
TOTP_ID = "totp"
MAILBOX_PASSWORD_ID = "mailboxPassword"
CONTINUE_BUTTON_SELECTOR = "button.w-full.button-large.button-solid-norm.mt-6"
ERROR_BANNER_SELECTOR = '[role="alert"]'
# Proton shows periodic account-security nags (e.g. "Do you remember your
# password? Verify now") using the same role="alert" markup as genuine login
# errors. These are benign/dismissible and not an indication of failure, so
# they're excluded from the error check below.
BENIGN_BANNER_PHRASES = ["remember your password"]

# A server row only carries this icon span when it advertises P2P/BitTorrent
# support - its absence means the server does not support P2P. Read live from
# the row on every run instead of a static exclusion list, so it can never go
# stale.
P2P_ICON_SELECTOR = "span.mx-2"
# Scoped to a single row (each row has exactly one action button, in its last
# cell) to avoid ever depending on an absolute nth-child position.
DOWNLOAD_BUTTON_XPATH = ".//button"

ELEMENT_WAIT_TIMEOUT = 20
LOGIN_ERROR_CHECK_TIMEOUT = 3
DASHBOARD_WAIT_TIMEOUT = 20
# Headless Chrome writes the file to disk rather than showing it in the DOM,
# so this bounds how long to wait for the download to finish rather than for
# an element to appear.
DOWNLOAD_WAIT_TIMEOUT = 20

# --- DATA LOADING FUNCTIONS ---
def load_config(file_path: str):
    """Loads credentials and every tunable setting from the JSON configuration
    file, fresh on each run. Nothing dynamic is hardcoded above - the module
    level values are only fallback defaults for configs written before a given
    key existed."""
    global USERNAME, PASSWORD, MAILBOX_PASSWORD, TOTP_SECRET_KEY, OUTPUT_FILE_NAME
    global LOGIN_URL, DOWNLOAD_URL
    global STATES, COUNTRY_NAME, USER_ID, PASS_ID, TOTP_ID, MAILBOX_PASSWORD_ID
    global CONTINUE_BUTTON_SELECTOR, ERROR_BANNER_SELECTOR, BENIGN_BANNER_PHRASES
    global P2P_ICON_SELECTOR, DOWNLOAD_BUTTON_XPATH
    global ELEMENT_WAIT_TIMEOUT, LOGIN_ERROR_CHECK_TIMEOUT, DASHBOARD_WAIT_TIMEOUT, DOWNLOAD_WAIT_TIMEOUT

    if not os.path.exists(file_path):
        raise FileNotFoundError(f"Configuration file not found: {file_path}. Please create it.")

    try:
        with open(file_path, 'r') as f:
            config = json.load(f)

        USERNAME = config.get("USERNAME", "")
        PASSWORD = config.get("PASSWORD", "")
        MAILBOX_PASSWORD = config.get("MAILBOX_PASSWORD", "")
        TOTP_SECRET_KEY = config.get("TOTP_SECRET_KEY", "")
        # OUTPUT_FILE is the single source of truth for the handoff path to update_pfsense.py.
        OUTPUT_FILE_NAME = config.get("OUTPUT_FILE", OUTPUT_FILE_NAME)

        LOGIN_URL = config.get("LOGIN_URL", LOGIN_URL)
        DOWNLOAD_URL = config.get("DOWNLOAD_URL", DOWNLOAD_URL)

        STATES = config.get("STATES", STATES)
        COUNTRY_NAME = config.get("COUNTRY_NAME", COUNTRY_NAME)

        USER_ID = config.get("USER_ID", USER_ID)
        PASS_ID = config.get("PASS_ID", PASS_ID)
        TOTP_ID = config.get("TOTP_ID", TOTP_ID)
        MAILBOX_PASSWORD_ID = config.get("MAILBOX_PASSWORD_ID", MAILBOX_PASSWORD_ID)
        CONTINUE_BUTTON_SELECTOR = config.get("CONTINUE_BUTTON_SELECTOR", CONTINUE_BUTTON_SELECTOR)
        ERROR_BANNER_SELECTOR = config.get("ERROR_BANNER_SELECTOR", ERROR_BANNER_SELECTOR)
        BENIGN_BANNER_PHRASES = config.get("BENIGN_BANNER_PHRASES", BENIGN_BANNER_PHRASES)

        P2P_ICON_SELECTOR = config.get("P2P_ICON_SELECTOR", P2P_ICON_SELECTOR)
        DOWNLOAD_BUTTON_XPATH = config.get("DOWNLOAD_BUTTON_XPATH", DOWNLOAD_BUTTON_XPATH)

        ELEMENT_WAIT_TIMEOUT = config.get("ELEMENT_WAIT_TIMEOUT", ELEMENT_WAIT_TIMEOUT)
        LOGIN_ERROR_CHECK_TIMEOUT = config.get("LOGIN_ERROR_CHECK_TIMEOUT", LOGIN_ERROR_CHECK_TIMEOUT)
        DASHBOARD_WAIT_TIMEOUT = config.get("DASHBOARD_WAIT_TIMEOUT", DASHBOARD_WAIT_TIMEOUT)
        DOWNLOAD_WAIT_TIMEOUT = config.get("DOWNLOAD_WAIT_TIMEOUT", DOWNLOAD_WAIT_TIMEOUT)

        if not all([USERNAME, PASSWORD, TOTP_SECRET_KEY]):
             raise ValueError("One or more required credentials (USERNAME, PASSWORD, TOTP_SECRET_KEY) are missing or empty in config.json.")

    except json.JSONDecodeError:
        raise ValueError(f"Error decoding JSON from {file_path}. Check for syntax errors.")
    except KeyError as e:
        raise ValueError(f"Missing required key in config.json: {e}. Check that all keys are present and correctly spelled.")

# --- HELPER FUNCTIONS ---

def detect_chrome_major_version() -> Optional[int]:
    """Detects the installed Chrome/Chromium major version so we can request a
    matching chromedriver explicitly. undetected_chromedriver caches its patched
    driver and doesn't reliably re-check it against the browser actually
    installed, so a driver cached against one Chrome version can go stale after
    an unrelated apt upgrade and fail with SessionNotCreatedException."""
    for binary in ("google-chrome-stable", "google-chrome", "chromium-browser", "chromium"):
        try:
            result = subprocess.run(
                [binary, "--version"], capture_output=True, text=True, timeout=10
            )
        except (FileNotFoundError, subprocess.TimeoutExpired):
            continue
        match = re.search(r'(\d+)\.\d+\.\d+\.\d+', result.stdout)
        if match:
            return int(match.group(1))
    return None

def get_totp_code() -> str:
    """Generates the current TOTP code using the loaded secret key."""
    if not TOTP_SECRET_KEY:
        raise ValueError("TOTP_SECRET_KEY is empty. Cannot generate TOTP.")
        
    totp = pyotp.TOTP(TOTP_SECRET_KEY)
    return totp.now()

def wait_and_find(driver: uc.Chrome, by: By, value: str, timeout: Optional[int] = None):
    """Waits for an element to be visible before finding and returning it."""
    if timeout is None:
        timeout = ELEMENT_WAIT_TIMEOUT
    return WebDriverWait(driver, timeout).until(
        EC.visibility_of_element_located((by, value))
    )

def safe_click(driver: uc.Chrome, by: By, value: str, timeout: Optional[int] = None):
    """Waits for an element to be clickable and then clicks it."""
    if timeout is None:
        timeout = ELEMENT_WAIT_TIMEOUT
    element = WebDriverWait(driver, timeout).until(
        EC.element_to_be_clickable((by, value))
    )
    element.click()

def check_for_login_error(driver: uc.Chrome, timeout: Optional[int] = None):
    """Briefly checks for a visible error banner (e.g. wrong password, bad TOTP)
    so failures are reported clearly instead of surfacing as an opaque timeout
    on the next step."""
    if timeout is None:
        timeout = LOGIN_ERROR_CHECK_TIMEOUT
    try:
        error_element = WebDriverWait(driver, timeout).until(
            EC.visibility_of_element_located((By.CSS_SELECTOR, ERROR_BANNER_SELECTOR))
        )
        banner_text = error_element.text.strip()
        if any(phrase.lower() in banner_text.lower() for phrase in BENIGN_BANNER_PHRASES):
            print(f"Ignoring benign banner: {banner_text!r}")
            return
        raise RuntimeError(f"Login step failed: {banner_text}")
    except TimeoutException:
        pass  # No error banner appeared - proceed as normal.

def extract_server_rows(driver: uc.Chrome) -> List[WebElement]:
    """Navigates to the download page, expands the country section, and
    returns the raw <tr> WebElements (not just their text) so callers can
    also inspect P2P support and trigger a specific row's own download
    button."""
    print("Navigating to the download page...")
    driver.get(DOWNLOAD_URL)

    # Built here (not at module load) since COUNTRY_NAME is only known once
    # load_config() has run.
    country_details_xpath = (
        f'//*[@id="openvpn-configuration-files"]'
        f'//details[.//summary[contains(normalize-space(.), "{COUNTRY_NAME}")]]'
    )
    server_table_xpath = f'{country_details_xpath}/div/div/table'

    try:
        # Wait for and expand the country section (e.g., US)
        country_element = wait_and_find(driver, By.XPATH, country_details_xpath)
        driver.execute_script("arguments[0].setAttribute('open', '')", country_element)

        # Wait for the table to become visible after expanding the section
        table = wait_and_find(driver, By.XPATH, server_table_xpath)
    except TimeoutException:
        raise Exception("Timed out waiting for server list table to load.")

    rows = table.find_elements(By.TAG_NAME, "tr")
    return rows[1:]  # skip header row

def parse_row(row: WebElement) -> Optional[Tuple[str, int, bool]]:
    """Extracts (server_name, utilization_percent, supports_p2p) from a row,
    or None if the row is malformed / missing a utilization cell. P2P support
    is read live from the row's icon span (see P2P_ICON_SELECTOR) instead of
    a static exclusion list, so it's always current as of this run."""
    cells = row.find_elements(By.TAG_NAME, "td")
    if not cells:
        return None

    try:
        server_name = cells[0].text.strip()
        utilization_str = cells[2].text.strip()
    except IndexError:
        return None

    percent_str = re.sub(r'[^0-9]', '', utilization_str)
    if not percent_str:
        return None
    utilization = int(percent_str)

    supports_p2p = len(row.find_elements(By.CSS_SELECTOR, P2P_ICON_SELECTOR)) > 0
    return server_name, utilization, supports_p2p

def find_lowest_utilization_p2p_server(rows: List[WebElement]) -> Tuple[str, int, WebElement]:
    """Filters rows to the configured states with live P2P support, and
    returns (server_name, utilization, row) for the lowest-utilization match.
    The row itself is returned (not just its data) so the caller can click
    that specific server's own download button next."""
    state_pattern = re.compile(r'us-([a-z]{2})#\d+', re.IGNORECASE)

    candidates = []
    for row in rows:
        parsed = parse_row(row)
        if parsed is None:
            continue
        server_name, utilization, supports_p2p = parsed

        match = state_pattern.search(server_name)
        if not match:
            continue
        state_code = match.group(1).upper()
        if state_code not in STATES:
            continue

        if not supports_p2p:
            print(f"Skipping server {server_name} ({utilization}%): no P2P support.")
            continue

        candidates.append((utilization, server_name, row))

    if not candidates:
        raise ValueError("Could not find a P2P-capable server matching the state criteria.")

    candidates.sort(key=lambda c: c[0])
    utilization, server_name, row = candidates[0]
    print(f"Selected {server_name} ({utilization}%) - lowest utilization P2P match.")
    return server_name, utilization, row

def download_openvpn_config(driver: uc.Chrome, row: WebElement, download_dir: str) -> str:
    """Clicks the row's own download button and returns the local path to
    the downloaded .ovpn file. Headless Chrome blocks downloads unless
    explicitly allowed via CDP (see set_download_directory), which main()
    sets up once before this is ever called."""
    existing = set(os.listdir(download_dir))

    download_button = row.find_element(By.XPATH, DOWNLOAD_BUTTON_XPATH)
    download_button.click()

    deadline = time.time() + DOWNLOAD_WAIT_TIMEOUT
    while time.time() < deadline:
        new_files = set(os.listdir(download_dir)) - existing
        # Chrome names in-progress downloads with a .crdownload suffix.
        finished = [f for f in new_files if not f.endswith('.crdownload')]
        if finished:
            return os.path.join(download_dir, finished[0])
        time.sleep(0.5)

    raise TimeoutException(f"Timed out waiting for the OpenVPN config download in {download_dir}.")

def extract_endpoint_ip(config_path: str) -> str:
    """Parses the downloaded .ovpn file for its first "remote <ip> <port>"
    line. Proton lists the same entry IP multiple times with different
    ports, so the first match is sufficient."""
    with open(config_path, 'r') as f:
        content = f.read()

    match = re.search(r'^remote\s+([\d.]+)\s+\d+', content, re.MULTILINE)
    if not match:
        raise RuntimeError(
            f"Could not find a 'remote <ip> <port>' line in downloaded config "
            f"{config_path} - the .ovpn format may have changed."
        )
    return match.group(1)

def set_download_directory(driver: uc.Chrome, download_dir: str) -> None:
    """Headless Chrome blocks file downloads by default; this explicitly
    allows them and directs them to download_dir."""
    driver.execute_cdp_cmd("Page.setDownloadBehavior", {
        "behavior": "allow",
        "downloadPath": download_dir,
    })

# --- MAIN EXECUTION ---
if __name__ == "__main__":
    driver = None
    best_server_ip = None
    download_dir = tempfile.mkdtemp(prefix="protonvpn-ovpn-")

    try:
        # 1. Load Configuration
        print(f"Loading configuration from {CONFIG_FILE}...")
        load_config(CONFIG_FILE)

        # --- Driver Setup ---
        options = uc.ChromeOptions()
        options.add_argument('--headless=new')
        options.add_argument('--no-sandbox')
        options.add_argument('--disable-dev-shm-usage')

        chrome_version = detect_chrome_major_version()
        if chrome_version:
            print(f"Detected installed Chrome major version: {chrome_version}")
        else:
            print("Warning: could not detect installed Chrome version; "
                  "falling back to undetected_chromedriver's own auto-detection.")

        print("Initializing WebDriver...")
        driver = uc.Chrome(
            use_subprocess=False,
            options=options,
            version_main=chrome_version,
        )
        set_download_directory(driver, download_dir)

        # --- Login Flow ---
        print(f"Visiting login URL: {LOGIN_URL}")
        driver.get(LOGIN_URL)
        
        print("Entering username...")
        wait_and_find(driver, By.ID, USER_ID).send_keys(USERNAME)
        safe_click(driver, By.CSS_SELECTOR, CONTINUE_BUTTON_SELECTOR)
        check_for_login_error(driver)

        print("Entering password...")
        wait_and_find(driver, By.ID, PASS_ID).send_keys(PASSWORD)
        safe_click(driver, By.CSS_SELECTOR, CONTINUE_BUTTON_SELECTOR)
        check_for_login_error(driver)

        print("Entering TOTP...")
        totp = get_totp_code()
        wait_and_find(driver, By.ID, TOTP_ID).send_keys(totp)
        check_for_login_error(driver)

        print("Entering mailbox password...")
        wait_and_find(driver, By.ID, MAILBOX_PASSWORD_ID).send_keys(MAILBOX_PASSWORD)
        safe_click(driver, By.CSS_SELECTOR, CONTINUE_BUTTON_SELECTOR)
        check_for_login_error(driver)

        print("Login complete. Waiting for dashboard...")
        WebDriverWait(driver, DASHBOARD_WAIT_TIMEOUT).until(
            EC.url_changes(LOGIN_URL)
        )

        # --- Data Extraction ---
        rows = extract_server_rows(driver)
        print(f"Found {len(rows)} server rows.")

        # --- Data Processing and Result ---
        server_name, utilization, best_row = find_lowest_utilization_p2p_server(rows)

        print(f"Downloading OpenVPN config for {server_name}...")
        config_path = download_openvpn_config(driver, best_row, download_dir)
        best_server_ip = extract_endpoint_ip(config_path)

        print("\n--- RESULT ---")
        print(f"Selected Server: {server_name}")
        print(f"Utilization: {utilization}%")
        print(f"**Best Server IP Address: {best_server_ip}**")

    except (TimeoutException, NoSuchElementException, WebDriverException) as e:
        print(f"\n--- FATAL ERROR (LINE {inspect.currentframe().f_lineno}) ---")
        print(f"A Selenium error occurred: {type(e).__name__} - {e}")
        if driver:
            driver.save_screenshot("error_screenshot.png")
            print("Saved error_screenshot.png for debugging.")
    except Exception as e:
        print(f"\n--- FATAL ERROR (LINE {inspect.currentframe().f_lineno}) ---")
        print(f"An unexpected error occurred: {type(e).__name__} - {e}")
    finally:
        # --- File Output and Cleanup ---
        if best_server_ip:
            try:
                with open(OUTPUT_FILE_NAME, 'w') as f:
                    f.write(best_server_ip)
                print(f"✅ IP address successfully written to **{OUTPUT_FILE_NAME}**")
            except IOError as e:
                print(f"❌ Failed to write IP to file {OUTPUT_FILE_NAME}: {e}")
                
        if driver:
            print("Closing WebDriver.")
            driver.quit()

        # The downloaded .ovpn file contains Proton's shared CA cert/tls-crypt
        # key (not per-user secrets, but no reason to leave it on disk).
        shutil.rmtree(download_dir, ignore_errors=True)

    # A caller chaining `scrape-ng-v2.py && update_pfsense.py` must be able to tell a
    # failed run apart from a successful one - otherwise a failure here silently falls
    # through to update_pfsense.py reusing the previous run's stale IP.
    sys.exit(0 if best_server_ip else 1)