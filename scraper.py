import pyotp
import undetected_chromedriver as uc
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, NoSuchElementException, WebDriverException
import time
import inspect
from typing import List, Dict, Any, Tuple
import re
import json
import os

# --- CONFIGURATION CONSTANTS ---
CONFIG_FILE = "config.json"
SERVER_MAP_FILE = "server_map.json"
LOGIN_URL = "https://account.protonvpn.com/login"
DOWNLOAD_URL = "https://account.protonvpn.com/downloads"
OUTPUT_FILE_NAME = "best_server_ip.txt" 

# Server filtering
STATES = ["MA", "NY", "NJ"]

# Selenium Selectors
USER_ID = "username"
PASS_ID = "password"
TOTP_ID = "totp"
MAILBOX_PASSWORD_ID = "mailboxPassword"
CONTINUE_BUTTON_SELECTOR = "button.w-full.button-large.button-solid-norm.mt-6"
US_COUNTRY_DETAILS_XPATH = '//*[@id="openvpn-configuration-files"]/div/div[6]/div[2]/details[122]'
SERVER_TABLE_XPATH = f'{US_COUNTRY_DETAILS_XPATH}/div/div/table'

# Server mapping data structure (Keep outside the main logic, maybe load from a file)
KEYS = ["us-ma-01","us-ma-05","us-ma-09","us-ma-11","us-ma-15","us-ma-19","us-ma-40","us-ma-44","us-ma-48","us-ma-50","us-ma-54","us-ma-58","us-nj-09","us-nj-114","us-nj-118","us-nj-12","us-nj-141","us-nj-145","us-nj-149","us-nj-214","us-nj-218","us-nj-241","us-nj-245","us-nj-47","us-ny-179","us-ny-424","us-ny-479","us-ny-520","us-ny-524","us-ny-528","us-ny-579","us-ny-620","us-ny-624","us-ny-679","us-ny-720","us-ny-724"]
VALUES = ["79.127.160.187","79.127.160.187","79.127.160.187","79.127.160.187","79.127.160.187","79.127.160.187","79.127.160.158","79.127.160.158","79.127.160.158","79.127.160.158","79.127.160.158","79.127.160.129","69.10.63.242","163.5.171.83","163.5.171.83","69.10.63.242","205.142.240.210","205.142.240.210","205.142.240.210","151.243.141.4","151.243.141.4","151.243.141.4","151.243.141.5","163.5.171.2","146.70.202.162","143.244.44.186","89.187.178.173","146.70.72.130","146.70.72.130","146.70.72.130","146.70.202.66","146.70.202.18","146.70.202.18","149.40.49.1","149.40.49.30","149.40.49.30"]
PROTON_DICT = dict(zip(KEYS, VALUES))

# Global variables for credentials, will be loaded in main
USERNAME = ""
PASSWORD = ""
MAILBOX_PASSWORD = ""
TOTP_SECRET_KEY = ""

# --- CREDENTIAL LOADING FUNCTION ---
def load_credentials(file_path: str):
    """Loads credentials from a JSON configuration file."""
    global USERNAME, PASSWORD, MAILBOX_PASSWORD, TOTP_SECRET_KEY
    
    if not os.path.exists(file_path):
        raise FileNotFoundError(f"Configuration file not found: {file_path}. Please create it.")
        
    try:
        with open(file_path, 'r') as f:
            config = json.load(f)
            
        USERNAME = config["USERNAME"]
        PASSWORD = config["PASSWORD"]
        MAILBOX_PASSWORD = config["MAILBOX_PASSWORD"]
        TOTP_SECRET_KEY = config["TOTP_SECRET_KEY"]
        
        # Basic check to ensure credentials were loaded
        if not all([USERNAME, PASSWORD, TOTP_SECRET_KEY]):
             raise ValueError("One or more required credentials (USERNAME, PASSWORD, TOTP_SECRET_KEY) are missing or empty in config.json.")
             
    except json.JSONDecodeError:
        raise ValueError(f"Error decoding JSON from {file_path}. Check for syntax errors.")
    except KeyError as e:
        raise ValueError(f"Missing required key in config.json: {e}. Check that all keys are present and correctly spelled.")

def load_server_map(file_path: str):
    """Loads the server key-to-IP mapping from a JSON file."""
    global PROTON_DICT
    
    if not os.path.exists(file_path):
        raise FileNotFoundError(f"Server map file not found: {file_path}. Please create it.")
        
    try:
        with open(file_path, 'r') as f:
            PROTON_DICT = json.load(f)
            
        if not PROTON_DICT:
             raise ValueError("Server map loaded but is empty. Check server_map.json content.")
             
    except json.JSONDecodeError:
        raise ValueError(f"Error decoding JSON from {file_path}. Check for syntax errors.")
        
# --- HELPER FUNCTIONS ---

def get_totp_code() -> str:
    """Generates the current TOTP code using the loaded secret key."""
    # Ensure TOTP_SECRET_KEY is loaded before using it
    if not TOTP_SECRET_KEY:
        raise ValueError("TOTP_SECRET_KEY is empty. Cannot generate TOTP.")
        
    totp = pyotp.TOTP(TOTP_SECRET_KEY)
    return totp.now()

def wait_and_find(driver: uc.Chrome, by: By, value: str, timeout: int = 20):
    """Waits for an element to be visible before finding and returning it."""
    return WebDriverWait(driver, timeout).until(
        EC.visibility_of_element_located((by, value))
    )

def safe_click(driver: uc.Chrome, by: By, value: str, timeout: int = 20):
    """Waits for an element to be clickable and then clicks it."""
    element = WebDriverWait(driver, timeout).until(
        EC.element_to_be_clickable((by, value))
    )
    element.click()

def extract_table_data(driver: uc.Chrome) -> List[List[str]]:
    """Navigates to the download page and extracts the server table data."""
    print("Navigating to the download page...")
    driver.get(DOWNLOAD_URL)

    try:
        # Wait for and expand the country section (e.g., US)
        country_element = wait_and_find(driver, By.XPATH, US_COUNTRY_DETAILS_XPATH)
        driver.execute_script("arguments[0].setAttribute('open', '')", country_element)
        
        # Wait for the table to become visible after expanding the section
        table = wait_and_find(driver, By.XPATH, SERVER_TABLE_XPATH)
    except TimeoutException:
        raise Exception("Timed out waiting for server list table to load.")

    table_data = []
    rows = table.find_elements(By.TAG_NAME, "tr")
    
    for row in rows[1:]:
        cells = row.find_elements(By.TAG_NAME, "td")
        if cells:
             table_data.append([cell.text.strip() for cell in cells])

    return table_data

def find_lowest_utilization_server(table_data: List[List[str]]) -> Tuple[str, int]:
    """Processes table data to find the server with the lowest utilization
       among the specified states."""
    
    lowest_server_key = ""
    lowest_utilization = 101
    state_pattern = re.compile(r'us-([a-z]{2})#\d+', re.IGNORECASE)

    for row in table_data:
        try:
            server_name = row[0].strip()
            utilization_str = row[2].strip()
            
            match = state_pattern.search(server_name)
            if not match: continue
                 
            state_code = match.group(1).upper()

            if state_code in STATES:
                percent_str = re.sub(r'[^0-9]', '', utilization_str)
                if not percent_str: continue
                    
                percent = int(percent_str)
                
                if percent < lowest_utilization:
                    server_key = server_name.replace('#','-').lower()
                    
                    # Uses the globally loaded PROTON_DICT
                    if server_key in PROTON_DICT:
                        lowest_server_key = server_key
                        lowest_utilization = percent
                        
        except (IndexError, ValueError, Exception) as e:
            continue

    if not lowest_server_key:
        raise ValueError("Could not find a valid server matching the state criteria.")
        
    return lowest_server_key, lowest_utilization

# --- MAIN EXECUTION ---
if __name__ == "__main__":
    driver = None
    best_server_ip = None

    try:
        # 1. Load Credentials First
        print(f"Loading credentials from {CONFIG_FILE}...")
        load_credentials(CONFIG_FILE)
        
        print(f"Loading server map from {SERVER_MAP_FILE}...")
        load_server_map(SERVER_MAP_FILE)
        
        # --- Driver Setup ---
        options = uc.ChromeOptions()
        options.headless = True
        options.add_argument('--no-sandbox')
        options.add_argument('--disable-dev-shm-usage')

        print("Initializing WebDriver...")
        driver = uc.Chrome(
            use_subprocess=False,
            options=options,
        )

        # --- Login Flow ---
        print(f"Visiting login URL: {LOGIN_URL}")
        driver.get(LOGIN_URL)
        
        print("Entering username...")
        # Now uses the globally loaded USERNAME
        wait_and_find(driver, By.ID, USER_ID).send_keys(USERNAME) 
        safe_click(driver, By.CSS_SELECTOR, CONTINUE_BUTTON_SELECTOR)
        
        print("Entering password...")
        # Now uses the globally loaded PASSWORD
        wait_and_find(driver, By.ID, PASS_ID).send_keys(PASSWORD)
        safe_click(driver, By.CSS_SELECTOR, CONTINUE_BUTTON_SELECTOR)
        
        print("Entering TOTP...")
        totp = get_totp_code()
        wait_and_find(driver, By.ID, TOTP_ID).send_keys(totp)
        
        print("Entering mailbox password...")
        # Now uses the globally loaded MAILBOX_PASSWORD
        wait_and_find(driver, By.ID, MAILBOX_PASSWORD_ID).send_keys(MAILBOX_PASSWORD)
        safe_click(driver, By.CSS_SELECTOR, CONTINUE_BUTTON_SELECTOR)
        
        print("Login complete. Waiting for dashboard...")
        WebDriverWait(driver, 20).until(
            EC.url_changes(LOGIN_URL) 
        )

        # --- Data Extraction ---
        table_data = extract_table_data(driver)
        print(f"Successfully extracted {len(table_data)} server rows.")
        
        # --- Data Processing and Result ---
        lowest_server_key, utilization = find_lowest_utilization_server(table_data)
        best_server_ip = PROTON_DICT.get(lowest_server_key)
        
        print("\n--- RESULT ---")
        print(f"Lowest Utilization Server Key: {lowest_server_key}")
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
