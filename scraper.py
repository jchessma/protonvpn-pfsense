import pyotp
import undetected_chromedriver as uc
from selenium.webdriver.common.by import By
import time
import inspect

# Some URL's that are required
login_url = "https://account.protonvpn.com/login"
downloadURL = "https://account.protonvpn.com/downloads"

# Credentials
username = "<Insert Username>"
password = "<Insert Password>"
mailboxPassword = "<Insert Mailbox Password>"

# These are the states to choose from
states = ["MA", "NY", "NJ"]

# DOM elements that Selenium searches for to enter text/click buttons/etc
userID = "username"
passID = "password"
# TOTP element ID's are totp, totp-1, totp-2, totp-3, totp-4, totp-5
totpID = "totp"
bestServerClass = "button.button-medium.button-solid-norm" 
textareaXPATH="/html/body/div[4]/dialog/form/div[2]/div[3]/div/div/div/div[2]/div/textarea"
continueClass = "button.w-full.button-large.button-solid-norm.mt-6"
mailboxPasswordID = "mailboxPassword"

# List of specific servers and their matching IP's stored in a dictionary
keys = ["us-ma-01","us-ma-05","us-ma-09","us-ma-11","us-ma-15","us-ma-19","us-ma-40","us-ma-44","us-ma-48","us-ma-50","us-ma-54","us-ma-58","us-nj-09","us-nj-114","us-nj-118","us-nj-12","us-nj-141","us-nj-145","us-nj-149","us-nj-214","us-nj-218","us-nj-241","us-nj-245","us-nj-47","us-ny-179","us-ny-424","us-ny-479","us-ny-520","us-ny-524","us-ny-528","us-ny-579","us-ny-620","us-ny-624","us-ny-679","us-ny-720","us-ny-724"]
values = ["79.127.160.187","79.127.160.187","79.127.160.187","79.127.160.187","79.127.160.187","79.127.160.187","79.127.160.158","79.127.160.158","79.127.160.158","79.127.160.158","79.127.160.158","79.127.160.129","69.10.63.242","163.5.171.83","163.5.171.83","69.10.63.242","205.142.240.210","205.142.240.210","205.142.240.210","151.243.141.4","151.243.141.4","151.243.141.4","151.243.141.5","163.5.171.2","146.70.202.162","143.244.44.186","89.187.178.173","146.70.72.130","146.70.72.130","146.70.72.130","146.70.202.66","146.70.202.18","146.70.202.18","149.40.49.1","149.40.49.30","149.40.49.30"]
protonDict = dict(zip(keys, values))

# Generate the TOTP from the secret key
def genTOTP():
    secretKey = "<Insert TOTP Secret Key>"

    totp = pyotp.TOTP(secretKey)
    return(totp.now())

if __name__ == "__main__":

    # instantiate Chrome options
    options = uc.ChromeOptions()
    # add headless mode
    options.headless = True

    # instantiate a Chrome browser and add the options
    driver = uc.Chrome(
        use_subprocess=False,
        options=options,
    )

    # visit the target URL
    try:
        driver.get(login_url)
    except Exception as e:
        print(f"{inspect.currentframe().f_lineno} Exception occurred: {e}")
    
    # Find the username field and enter it
    try:
        usernameElem = driver.find_element(By.ID, userID)
        usernameElem.send_keys(username)
        time.sleep(1)
    except Exception as e:
        print(f"{inspect.currentframe().f_lineno} Exception occurred: {e}")
    
    # Click to continue
    try:
        driver.find_element(By.CSS_SELECTOR, continueClass).click()    
        time.sleep(5)
    except Exception as e:
        print(f"{inspect.currentframe().f_lineno} Exception Occurred: {e}")
    
    # Find the password field and enter it
    try:
        passwordElem = driver.find_element(By.ID, passID)
        passwordElem.send_keys(password)
        time.sleep(1)
    except Exception as e:
        print(f"{inspect.currentframe().f_lineno} Exception Occurred: {e}")
    
    # Click to continue
    try:
        driver.find_element(By.CSS_SELECTOR, continueClass).click()
        time.sleep(5)
    except Exception as e:
        print(f"{inspect.currentframe().f_lineno} Exception Occurred: {e}")
    
    # Generate the TOTP
    totp = genTOTP()
    
    # Find the first TOTP entry field
    try:
        totpElem = driver.find_element(By.ID, totpID)
        totpElem.send_keys(totp)
        time.sleep(5)
    except Exception as e:
        print(f"{inspect.currentframe().f_lineno} Exception Occurred: {e}")
  
    # Enter mailbox password
    try:    
        mailboxPwdElem = driver.find_element(By.ID, mailboxPasswordID)
        mailboxPwdElem.send_keys(mailboxPassword)
        time.sleep(1)
    except Exception as e:
        print(f"{inspect.currentframe().f_lineno} Exception Occurred: {e}")
    
    # Click to continue
    try:
        driver.find_element(By.CSS_SELECTOR, continueClass).click()
        time.sleep(10)
    except Exception as e:
        print(f"{inspect.currentframe().f_lineno} Exception Occurred: {e}")
    
    # Navigate to the download page
    try:
        driver.get(downloadURL)
        time.sleep(5)
    except Exception as e:
        print(f"{inspect.currentframe().f_lineno} Exception occurred: {e}")
        
    try:
        countryElement = driver.find_element(By.XPATH, '//*[@id="openvpn-configuration-files"]/div/div[6]/div[2]/details[122]')
        driver.execute_script("arguments[0].setAttribute('open', '')", countryElement)
        time.sleep(3)
    except Exception as e:
        print(f"{inspect.currentframe().f_lineno} Exception occurred: {e}")
    
    try:
        table = driver.find_element(By.XPATH, '//*[@id="openvpn-configuration-files"]/div/div[6]/div[2]/details[122]/div/div/table')
        time.sleep(2)
    except Exception as e:
        print(f"{inspect.currentframe().f_lineno} Exception occurred: {e}")
    
    try:
        tableData = []
        
        rows = table.find_elements(By.TAG_NAME, "tr")
        for row in rows:
            rowData = []
            cells = row.find_elements(By.TAG_NAME, "td")
            for cell in cells:
                rowData.append(cell.text)
            tableData.append(rowData)
    except Exception as e:
        print(f"{inspect.currentframe().f_lineno} Exception occurred: {e}")
        
    validRows = []
    
    # Parse the data and find the fastest, closest server
    for row in tableData:
        # Try parsing the row, if it fails, move on
        # We are looking for servers from the list states
        try:
            if any(sub in row[0] for sub in states):
                # Found a matching row, add it to the tracker
                validRows.append(row)
        except Exception as e:
            pass
    
    # Look for the least loaded server
    lowestRow = ["", 100]
    for row in validRows:
        percent = int(row[2].split('%')[0])
        if percent < lowestRow[1]:
            lowestRow[0] = row[0].replace('#','-').lower()
            lowestRow[1] = percent
    
    # Print the lowest load server IP
    print(protonDict[lowestRow[0]])
        
    driver.quit()
