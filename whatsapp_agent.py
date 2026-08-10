"""
whatsapp_agent.py
------------------
WhatsApp Agent Core Logic — Reads phone numbers & business names from Excel files
in outputs/ directory, performs template personalization, and sends WhatsApp messages
via Selenium with Chrome persistent user session and randomized delays.
"""

import os
import re
import time
import json
import random
from datetime import datetime
from urllib.parse import quote
import pandas as pd

from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.chrome import ChromeDriverManager

OUTPUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "outputs")
LOG_FILE = os.path.join(OUTPUT_DIR, "whatsapp_log.json")
SESSION_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "whatsapp_session")


def normalize_phone(phone_str):
    """
    Cleans a phone number into the international format WhatsApp Web needs.
    Digits only. Assumes Pakistani numbers: strips leading '0' and prepends '92'.
    Examples:
    '0312 5999970' -> '923125999970'
    '+923125999970' -> '923125999970'
    '3125999970' -> '923125999970'
    """
    if not phone_str or not isinstance(phone_str, str):
        return ""
    
    clean = phone_str.strip()
    digits = re.sub(r'[^\d]', '', clean)
    
    if not digits:
        return ""
    
    # If starts with leading zero (e.g. 03125999970)
    if digits.startswith("0"):
        digits = "92" + digits[1:]
    # If 10 digits starting with 3 (e.g. 3125999970)
    elif len(digits) == 10 and digits.startswith("3"):
        digits = "92" + digits
        
    return digits


def extract_contacts_from_excel(filename):
    """
    Reads BOTH 'Phone' and 'Business Name' columns from the given Excel file in outputs/.
    Uses forward fill (ffill) to propagate values across merged cells.
    Returns a deduplicated list of dicts like [{"phone": "92...", "business_name": "..."}],
    skipping rows where Phone is N/A/empty/invalid (at least 7 digits after removing non-digits).
    """
    filepath = os.path.join(OUTPUT_DIR, filename)
    if not os.path.exists(filepath):
        return []

    try:
        df = pd.read_excel(filepath)
        df = df.ffill()

        contacts = []
        seen_phones = set()

        for _, row in df.iterrows():
            phone_val = row.get("Phone")
            if pd.isna(phone_val):
                continue
            
            phone_str = str(phone_val).strip()
            if phone_str.lower() in ("n/a", "none", "null", ""):
                continue

            raw_digits = re.sub(r'[^\d]', '', phone_str)
            if len(raw_digits) < 7:
                continue

            norm_phone = normalize_phone(phone_str)
            if not norm_phone or len(norm_phone) < 7:
                continue

            if norm_phone not in seen_phones:
                seen_phones.add(norm_phone)

                biz_name_val = row.get("Business Name")
                biz_name = str(biz_name_val).strip() if not pd.isna(biz_name_val) else "N/A"
                if biz_name.lower() in ("n/a", "none", "null", ""):
                    biz_name = "N/A"

                contacts.append({
                    "phone": norm_phone,
                    "business_name": biz_name
                })

        return contacts
    except Exception as e:
        print(f"Error reading contacts from excel file {filename}: {e}")
        return []


def get_available_files():
    """
    Lists all .xlsx files in the outputs/ directory along with the count
    of valid WhatsApp phone numbers in each file.
    """
    if not os.path.exists(OUTPUT_DIR):
        return []

    files = [f for f in os.listdir(OUTPUT_DIR) if f.endswith(".xlsx")]
    files.sort(key=lambda x: os.path.getmtime(os.path.join(OUTPUT_DIR, x)), reverse=True)
    
    file_info_list = []
    for fname in files:
        contacts = extract_contacts_from_excel(fname)
        file_info_list.append({
            "filename": fname,
            "valid_phone_count": len(contacts)
        })

    return file_info_list


def log_campaign(file_name, message_template, result):
    """
    Logs WhatsApp campaign send results into outputs/whatsapp_log.json.
    """
    history = []
    if os.path.exists(LOG_FILE):
        try:
            with open(LOG_FILE, "r", encoding="utf-8") as f:
                history = json.load(f)
        except Exception as e:
            print(f"Error reading whatsapp_log.json: {e}")
            history = []

    log_entry = {
        "timestamp": datetime.now().isoformat(),
        "file_name": file_name,
        "message_template": message_template,
        "message_preview": message_template[:100] if message_template else "",
        "result": result
    }

    history.append(log_entry)

    try:
        with open(LOG_FILE, "w", encoding="utf-8") as f:
            json.dump(history, f, indent=2)
    except Exception as e:
        print(f"Error writing to whatsapp_log.json: {e}")


def get_campaign_history():
    """
    Reads outputs/whatsapp_log.json and returns past campaign entries, most recent first.
    """
    if not os.path.exists(LOG_FILE):
        return []

    try:
        with open(LOG_FILE, "r", encoding="utf-8") as f:
            history = json.load(f)
            if isinstance(history, list):
                return list(reversed(history))
            return []
    except Exception as e:
        print(f"Error reading WhatsApp campaign history: {e}")
        return []


def send_whatsapp_campaign(filename, message_template):
    """
    Launches Chrome via Selenium with a persistent profile (whatsapp_session/),
    checks for WhatsApp Web login, sends personalized messages with random delays (8-15s),
    and records results per contact.
    """
    contacts = extract_contacts_from_excel(filename)
    if not contacts:
        raise ValueError(f"No valid phone numbers found in file '{filename}'.")

    if not os.path.exists(SESSION_DIR):
        os.makedirs(SESSION_DIR, exist_ok=True)

    options = webdriver.ChromeOptions()
    options.add_argument(f"--user-data-dir={SESSION_DIR}")
    options.add_argument("--disable-notifications")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--start-maximized")

    driver = None
    try:
        service = Service(ChromeDriverManager().install())
        driver = webdriver.Chrome(service=service, options=options)
    except Exception as e:
        raise RuntimeError(f"Failed to launch Chrome driver via Selenium: {str(e)}")

    total_contacts = len(contacts)
    sent_count = 0
    failed_count = 0
    details = []

    try:
        driver.get("https://web.whatsapp.com")
        
        # Wait up to 60s for WhatsApp Web to load / QR code scan
        print("[WhatsApp Agent] Waiting for WhatsApp Web login...")
        login_timeout = 60
        start_time = time.time()
        logged_in = False

        while time.time() - start_time < login_timeout:
            try:
                # Elements that indicate logged in state: pane-side chat list or app header
                if driver.find_elements(By.XPATH, '//div[@id="pane-side"] | //header | //div[@contenteditable="true"]'):
                    logged_in = True
                    break
            except Exception:
                pass
            time.sleep(2)

        if not logged_in:
            raise TimeoutError("WhatsApp Web login timed out (60s). Please scan the QR code in the opened browser window.")

        print(f"[WhatsApp Agent] Logged in. Dispatching campaign to {total_contacts} contacts...")

        for idx, contact in enumerate(contacts):
            phone = contact["phone"]
            biz_name = contact["business_name"]

            # Replace placeholder {business_name}
            personalized_msg = re.sub(r'(?i)\{business_name\}', biz_name, message_template)
            encoded_msg = quote(personalized_msg)
            chat_url = f"https://web.whatsapp.com/send?phone={phone}&text={encoded_msg}"

            try:
                driver.get(chat_url)
                
                # Wait for send button or invalid number popup
                wait = WebDriverWait(driver, 25)
                
                # Check if invalid number dialog appears or send button becomes available
                send_button_xpath = '//span[@data-icon="send"]/parent::button | //button[@aria-label="Send"] | //button[contains(@class, "x1c4vz4f")]'
                invalid_popup_xpath = '//div[contains(text(), "invalid phone number") or contains(text(), "Phone number shared via url is invalid") or contains(text(), "isn\'t on WhatsApp")]'

                # Poll until either send button or invalid popup is present
                action_start = time.time()
                send_btn = None
                is_invalid = False

                while time.time() - action_start < 25:
                    invalid_el = driver.find_elements(By.XPATH, invalid_popup_xpath)
                    if invalid_el:
                        is_invalid = True
                        break
                    
                    send_els = driver.find_elements(By.XPATH, send_button_xpath)
                    if send_els:
                        send_btn = send_els[0]
                        break
                    time.sleep(1)

                if is_invalid:
                    failed_count += 1
                    details.append({
                        "phone": phone,
                        "business_name": biz_name,
                        "status": "failed",
                        "error": "Phone number not registered on WhatsApp"
                    })
                    print(f"[{idx+1}/{total_contacts}] Failed {phone}: Not registered on WhatsApp")
                elif send_btn:
                    # Click send button
                    send_btn.click()
                    time.sleep(2)  # Give time for send animation
                    
                    sent_count += 1
                    details.append({
                        "phone": phone,
                        "business_name": biz_name,
                        "status": "sent",
                        "error": None
                    })
                    print(f"[{idx+1}/{total_contacts}] Sent to {phone} ({biz_name})")
                else:
                    # Fallback: Try pressing ENTER in main editable text area
                    input_box = driver.find_elements(By.XPATH, '//footer//div[@contenteditable="true"]')
                    if input_box:
                        input_box[0].send_keys(Keys.ENTER)
                        time.sleep(2)
                        sent_count += 1
                        details.append({
                            "phone": phone,
                            "business_name": biz_name,
                            "status": "sent",
                            "error": None
                        })
                        print(f"[{idx+1}/{total_contacts}] Sent (via Enter key) to {phone} ({biz_name})")
                    else:
                        raise TimeoutError("Send button / input box not found within timeout.")

            except Exception as send_err:
                failed_count += 1
                details.append({
                    "phone": phone,
                    "business_name": biz_name,
                    "status": "failed",
                    "error": str(send_err)
                })
                print(f"[{idx+1}/{total_contacts}] Failed {phone}: {send_err}")

            # Random delay between 8 and 15 seconds after each contact
            if idx < total_contacts - 1:
                delay = random.uniform(8, 15)
                time.sleep(delay)

        summary = {
            "total": total_contacts,
            "sent": sent_count,
            "failed": failed_count,
            "details": details
        }

        log_campaign(filename, message_template, summary)
        return summary

    finally:
        if driver:
            try:
                driver.quit()
            except Exception:
                pass
