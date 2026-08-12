"""
whatsapp_agent.py
------------------
WhatsApp Agent Core Logic — Reads phone numbers & business leads from Excel files
in outputs/ directory, performs template personalization, clickable link safety,
daily send limits, progress persistence, and sends WhatsApp messages via Selenium
in a background thread with randomized delays.
"""

import os
import re
import time
import json
import random
import uuid
import threading
import sys
import shutil
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
SENT_LOG_FILE = os.path.join(OUTPUT_DIR, "whatsapp_sent_log.json")
PROGRESS_FILE = os.path.join(OUTPUT_DIR, "whatsapp_progress.json")
SESSION_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "whatsapp_session")

# In-memory store for active campaigns
active_campaigns = {}


def bring_window_to_front(driver):
    """
    Forces the Selenium Chrome window into the foreground / front of screen.
    Uses native Selenium window management and Windows User32 API if available.
    """
    if not driver:
        return

    try:
        driver.switch_to.window(driver.current_window_handle)
        driver.minimize_window()
        driver.maximize_window()
        driver.execute_script("window.focus();")
    except Exception:
        pass

    if sys.platform.startswith("win") or os.name == "nt":
        try:
            import ctypes
            user32 = ctypes.windll.user32

            def enum_windows_proc(hwnd, extra):
                if user32.IsWindowVisible(hwnd):
                    length = user32.GetWindowTextLengthW(hwnd)
                    if length > 0:
                        buff = ctypes.create_unicode_buffer(length + 1)
                        user32.GetWindowTextW(hwnd, buff, length + 1)
                        title = buff.value
                        if "WhatsApp" in title or "Chrome" in title:
                            user32.ShowWindow(hwnd, 9)  # SW_RESTORE / SW_SHOWNORMAL
                            user32.SetForegroundWindow(hwnd)
                return True

            WNDENUMPROC = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)
            user32.EnumWindows(WNDENUMPROC(enum_windows_proc), 0)
        except Exception:
            pass


def normalize_phone(phone_str):
    """
    Cleans a phone number into digits only.
    Handles Pakistani formats (leading '0' -> '92', 10 digits starting with '3' -> '923...').
    Returns cleaned digit string.
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


def extract_leads_from_excel(filename):
    """
    Reads complete lead rows from Excel file in outputs/.
    Applies forward fill (ffill) for merged cells.
    Returns list of lead dicts with snake_case keys and original column values.
    """
    filepath = os.path.join(OUTPUT_DIR, filename)
    if not os.path.exists(filepath):
        return []

    try:
        df = pd.read_excel(filepath)
        df = df.ffill()

        leads = []
        for _, row in df.iterrows():
            lead = {}
            for col in df.columns:
                val = row.get(col)
                val_str = str(val).strip() if not pd.isna(val) else ""
                col_str = str(col)
                lead[col_str] = val_str
                col_clean = col_str.strip().lower().replace(" ", "_")
                lead[col_clean] = val_str

            phone_val = lead.get("phone") or lead.get("mobile") or lead.get("contact") or lead.get("Phone") or ""
            norm_phone = normalize_phone(str(phone_val))

            biz_name = lead.get("business_name") or lead.get("business") or lead.get("name") or lead.get("Business Name") or "N/A"
            if str(biz_name).lower() in ("n/a", "none", "null", ""):
                biz_name = "N/A"

            review_link = lead.get("review_link") or lead.get("business_maps_link") or lead.get("Review Link") or lead.get("Business Maps Link") or ""

            lead["phone_raw"] = str(phone_val).strip()
            lead["phone"] = norm_phone
            lead["business_name"] = str(biz_name).strip()
            lead["review_link"] = str(review_link).strip()
            lead["review_stars"] = str(lead.get("review_stars") or lead.get("rating") or lead.get("Review Stars") or "").strip()
            lead["reviewer_name"] = str(lead.get("reviewer_name") or lead.get("reviewer") or lead.get("Reviewer Name") or "").strip()
            lead["review_text"] = str(lead.get("review_text") or lead.get("review") or lead.get("Review Text") or "").strip()
            lead["review_date"] = str(lead.get("review_date") or lead.get("Review Date") or "").strip()

            leads.append(lead)

        return leads
    except Exception as e:
        print(f"Error reading leads from excel file {filename}: {e}")
        return []


def extract_contacts_from_excel(filename):
    """
    Backward compatibility helper: Returns deduplicated valid contact list.
    """
    leads = extract_leads_from_excel(filename)
    contacts = []
    seen = set()
    for lead in leads:
        phone = lead["phone"]
        if phone and len(phone) >= 7 and phone not in seen:
            seen.add(phone)
            contacts.append({
                "phone": phone,
                "business_name": lead["business_name"]
            })
    return contacts


def get_available_files(user_id=None):
    """
    Lists all .xlsx files in outputs/ with valid WhatsApp phone number counts.
    """
    if not os.path.exists(OUTPUT_DIR):
        return []

    files = [f for f in os.listdir(OUTPUT_DIR) if f.endswith(".xlsx") and f != "combined_outreach_report.xlsx"]
    if user_id is not None:
        files = [f for f in files if f.startswith(f"user_{user_id}_")]
    else:
        files = [f for f in files if not f.startswith("user_")]
        
    files.sort(key=lambda x: os.path.getmtime(os.path.join(OUTPUT_DIR, x)), reverse=True)

    file_info_list = []
    for fname in files:
        contacts = extract_contacts_from_excel(fname)
        file_info_list.append({
            "filename": fname,
            "valid_phone_count": len(contacts)
        })

    return file_info_list


def clean_placeholder_val(v):
    if v is None or pd.isna(v):
        return ""
    s = str(v).strip()
    if s.lower() in ("n/a", "none", "null", ""):
        return ""
    return s


def replace_placeholders(text, lead):
    """
    Performs case-insensitive replacement of personalization placeholders.
    Includes clickable link safety for {review_link}.
    """
    if not text:
        return ""
    t = text

    # 1. Clickable Link Safety for {review_link}
    link_val = clean_placeholder_val(lead.get("review_link"))
    if link_val:
        # Clean leading/trailing/hidden whitespace and newlines
        clean_link = re.sub(r'[\s\r\n]+', '', link_val)
        # Ensure a plain space immediately before AND after inserted link so WhatsApp auto-detects it
        t = re.sub(r'(?i)\{review_link\}', f" {clean_link} ", t)
    else:
        # Skip inserting if empty/invalid/missing
        t = re.sub(r'(?i)\{review_link\}', "", t)

    # 2. Replacements for other tags
    for tag in ["business_name", "review_stars", "reviewer_name", "review_text", "review_date"]:
        val = clean_placeholder_val(lead.get(tag))
        t = re.sub(r'(?i)\{' + tag + r'\}', val, t)

    return t.strip()


def log_campaign(file_name, message_template, result, user_id=None):
    """
    Logs WhatsApp campaign send results into both outputs/whatsapp_log.json and outputs/whatsapp_sent_log.json.
    """
    log_entry = {
        "timestamp": datetime.now().isoformat(),
        "file_name": file_name,
        "message_template": message_template,
        "message_preview": message_template[:100] if message_template else "",
        "result": result,
        "user_id": user_id
    }

    for log_path in [LOG_FILE, SENT_LOG_FILE]:
        history = []
        if os.path.exists(log_path):
            try:
                with open(log_path, "r", encoding="utf-8") as f:
                    history = json.load(f)
            except Exception:
                history = []
        history.append(log_entry)
        try:
            with open(log_path, "w", encoding="utf-8") as f:
                json.dump(history, f, indent=2)
        except Exception as e:
            print(f"Error writing to {log_path}: {e}")


def get_campaign_history(user_id=None):
    """
    Reads outputs/whatsapp_log.json and returns past campaign entries, most recent first.
    """
    log_path = LOG_FILE if os.path.exists(LOG_FILE) else SENT_LOG_FILE
    if not os.path.exists(log_path):
        return []

    try:
        with open(log_path, "r", encoding="utf-8") as f:
            history = json.load(f)
            if isinstance(history, list):
                if user_id is not None:
                    history = [c for c in history if c.get("user_id") == user_id]
                return list(reversed(history))
            return []
    except Exception as e:
        print(f"Error reading WhatsApp campaign history: {e}")
        return []


def save_progress():
    """
    Persists active campaigns state to outputs/whatsapp_progress.json for crash recovery / RESUME.
    """
    try:
        with open(PROGRESS_FILE, "w", encoding="utf-8") as f:
            json.dump(active_campaigns, f, indent=2)
    except Exception as e:
        print(f"Error saving whatsapp progress: {e}")


def load_progress():
    """
    Loads active campaigns state from outputs/whatsapp_progress.json.
    """
    global active_campaigns
    if os.path.exists(PROGRESS_FILE):
        try:
            with open(PROGRESS_FILE, "r", encoding="utf-8") as f:
                active_campaigns = json.load(f)
        except Exception as e:
            print(f"Error loading whatsapp progress: {e}")


def bg_send_whatsapp_worker(campaign_id, leads, message_template, min_delay, max_delay, daily_limit_enabled, daily_limit, drafts=None, start_index=0, user_id=None):
    """
    Worker function executed in a background thread to send WhatsApp messages asynchronously.
    """
    status_entry = active_campaigns[campaign_id]
    status_entry["status"] = "running"
    status_entry["status_message"] = "Initializing Chrome driver & checking WhatsApp Web..."
    save_progress()

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
        status_entry["status"] = "failed"
        status_entry["error"] = f"Failed to launch Chrome driver via Selenium: {str(e)}"
        save_progress()
        return

    try:
        driver.get("https://web.whatsapp.com")
        
        # Wait up to 120s for WhatsApp Web login
        login_timeout = 120
        start_time = time.time()
        logged_in = False

        # Initial check to see if session is already logged in
        time.sleep(2.5)
        try:
            if driver.find_elements(By.XPATH, '//div[@id="pane-side"] | //header | //div[@contenteditable="true"]'):
                logged_in = True
        except Exception:
            pass

        # Bring window to front ONLY if fresh QR scan is needed
        if not logged_in:
            bring_window_to_front(driver)

        while not logged_in and (time.time() - start_time < login_timeout):
            try:
                if driver.find_elements(By.XPATH, '//div[@id="pane-side"] | //header | //div[@contenteditable="true"]'):
                    logged_in = True
                    break
            except Exception:
                pass
            time.sleep(2)

        if not logged_in:
            status_entry["status"] = "failed"
            status_entry["error"] = "WhatsApp Web login timed out (120s). Please scan the QR code in the opened Chrome window."
            save_progress()
            return

        status_entry["status_message"] = "WhatsApp Web logged in. Dispatching messages..."

        seen_phones = set()
        # Collect previously processed numbers if resuming
        for d in status_entry.get("details", []):
            p = d.get("phone")
            if p and d.get("status") in ("sent", "skipped"):
                seen_phones.add(p)

        # Build custom drafts lookup by phone if provided
        drafts_map = {}
        if drafts:
            for d in drafts:
                if d.get("phone"):
                    drafts_map[d["phone"]] = d.get("message", "")

        total_leads = len(leads)
        diag_inplace_count = 0
        diag_fallback_count = 0

        for idx in range(start_index, total_leads):
            # Check for Daily Limit reach
            if daily_limit_enabled and status_entry["sent_today"] >= daily_limit:
                status_entry["status"] = "paused"
                remaining = total_leads - status_entry["processed_count"]
                status_entry["status_message"] = f"Daily limit reached ({daily_limit} messages) — resume tomorrow ({remaining} left to send)"
                save_progress()

                summary = {
                    "total": total_leads,
                    "sent": status_entry["sent"],
                    "failed": status_entry["failed"],
                    "skipped": status_entry["skipped"],
                    "details": status_entry["details"]
                }
                log_campaign(status_entry["file_name"], message_template, summary, user_id)
                print(f"[DIAG SUMMARY] In-place search succeeded: {diag_inplace_count} | Fallback used: {diag_fallback_count}")
                return

            lead = leads[idx]
            phone = lead.get("phone", "")
            phone_raw = lead.get("phone_raw", "")
            biz_name = lead.get("business_name", "N/A")

            status_entry["processed_count"] = idx + 1

            # 1. Validation Check: Missing or invalid phone number (< 7 digits)
            if not phone or len(phone) < 7:
                status_entry["skipped"] += 1
                status_entry["details"].append({
                    "phone": phone_raw or phone or "N/A",
                    "business_name": biz_name,
                    "status": "skipped",
                    "error": "Invalid or missing phone number (< 7 digits)"
                })
                save_progress()
                continue

            # 2. Validation Check: Duplicate phone number in campaign
            if phone in seen_phones:
                status_entry["skipped"] += 1
                status_entry["details"].append({
                    "phone": phone,
                    "business_name": biz_name,
                    "status": "skipped",
                    "error": "Duplicate phone number in campaign"
                })
                save_progress()
                continue

            seen_phones.add(phone)

            # Personalize message or use custom draft
            if phone in drafts_map and drafts_map[phone]:
                personalized_msg = drafts_map[phone]
            else:
                personalized_msg = replace_placeholders(message_template, lead)

            print(f"[DIAG] Processing recipient: {phone}")

            search_input_xpaths = [
                '//div[@id="side"]//div[@contenteditable="true"]',
                '//div[@id="side"]//div[contains(@aria-label, "Search") or contains(@aria-label, "search") or contains(@title, "Search") or contains(@title, "search")]',
                '//div[@contenteditable="true" and (contains(@aria-label, "Search") or contains(@aria-label, "search"))]',
                '//div[contains(@data-testid, "search") or contains(@data-testid, "chat-list-search")]//div[@contenteditable="true"]',
                '//div[@id="side"]//p[contains(@class, "selectable-text")]',
                '//div[@id="side"]//div[@role="textbox"]'
            ]
            search_button_xpaths = [
                '//button[@aria-label="Search or start new chat"]',
                '//button[contains(@aria-label, "Search") or contains(@aria-label, "search")]',
                '//div[@id="side"]//button[contains(@aria-label, "Search") or contains(@aria-label, "search") or contains(@title, "Search")]'
            ]
            chat_result_xpath = '//div[@id="pane-side"]//div[contains(@role, "listitem")] | //div[@id="pane-side"]//div[@role="button"] | //div[@id="pane-side"]//span[@title] | //div[@id="pane-side"]//div[contains(@class, "_ak72")] | //div[@id="side"]//div[contains(@role, "gridcell")]'
            input_box_xpath = '//footer//div[@contenteditable="true"] | //div[@id="main"]//footer//div[@contenteditable="true"] | //div[@contenteditable="true"][@data-tab="10"] | //footer//p[contains(@class, "selectable-text")] | //div[@title="Type a message"]'
            send_button_xpath = '//span[@data-icon="send"]/parent::button | //button[@aria-label="Send"] | //button[contains(@class, "x1c4vz4f")] | //span[@data-icon="aria-send"]/parent::button | //footer//button[span[@data-icon="send"]]'
            invalid_popup_xpath = '//div[contains(text(), "invalid phone number") or contains(text(), "Phone number shared via url is invalid") or contains(text(), "isn\'t on WhatsApp") or contains(text(), "is not on WhatsApp") or contains(text(), "No results found")]'
            sent_verification_xpath = '//div[@id="main"]//div[contains(@class, "message-out")] | //div[@id="main"]//span[@data-icon="msg-check" or @data-icon="msg-dblcheck" or @data-icon="status-time" or @data-icon="msg-time" or @data-icon="msg-dblcheck-ack" or @data-icon="msg-check-ack"]'

            chat_opened = False
            is_invalid = False
            input_box = None

            # 1. Attempt to open chat via search box without full page reload
            search_start = time.time()
            search_input_el = None
            matched_search_xpath = None
            search_fail_reason = None

            # Wait up to 6 seconds to locate and interact with search input
            while time.time() - search_start < 6:
                for xpath in search_input_xpaths:
                    els = driver.find_elements(By.XPATH, xpath)
                    if els and els[0].is_displayed():
                        search_input_el = els[0]
                        matched_search_xpath = xpath
                        break

                if not search_input_el:
                    for s_btn_xpath in search_button_xpaths:
                        s_btns = driver.find_elements(By.XPATH, s_btn_xpath)
                        if s_btns and s_btns[0].is_displayed():
                            try:
                                s_btns[0].click()
                                print(f"[DIAG] Search button clicked using selector: {s_btn_xpath}")
                                time.sleep(0.5)
                            except Exception as sb_err:
                                print(f"[DIAG] Failed clicking search button ({s_btn_xpath}): {sb_err}")
                            break

                if search_input_el:
                    break

                time.sleep(0.5)

            if not search_input_el:
                print(f"[DIAG] Search box NOT found with any selector within 6s for {phone}")
                search_fail_reason = "Search box element not found in DOM within timeout"
                try:
                    side_els = driver.find_elements(By.XPATH, '//div[@id="side"]')
                    if side_els:
                        print(f"[WhatsApp Agent Diagnostic] Outer HTML snippet of #side for {phone}:")
                        print(side_els[0].get_attribute("outerHTML")[:500])
                except Exception:
                    pass
            else:
                print(f"[DIAG] Search box found using selector: {matched_search_xpath}")
                try:
                    search_input_el.click()
                    time.sleep(0.3)
                    search_input_el.send_keys(Keys.CONTROL, "a")
                    search_input_el.send_keys(Keys.BACKSPACE)
                    try:
                        driver.execute_script("arguments[0].textContent = '';", search_input_el)
                    except Exception:
                        pass
                    time.sleep(0.2)
                    search_input_el.send_keys(phone)
                    print(f"[DIAG] Typed '{phone}' into search box: success")
                    time.sleep(2.5)

                    results_start = time.time()
                    matched_result = None
                    while time.time() - results_start < 5:
                        res_els = driver.find_elements(By.XPATH, chat_result_xpath)
                        if res_els:
                            for res in res_els:
                                if res.is_displayed():
                                    matched_result = res
                                    break
                        if matched_result:
                            break
                        time.sleep(0.5)

                    if matched_result:
                        res_text = "N/A"
                        try:
                            res_text = matched_result.text.strip().replace("\n", " ")[:60]
                        except Exception:
                            pass
                        print(f"[DIAG] Search result found: '{res_text}'")

                        try:
                            matched_result.click()
                        except Exception:
                            driver.execute_script("arguments[0].click();", matched_result)

                        time.sleep(1.5)

                        inp_start = time.time()
                        while time.time() - inp_start < 4:
                            inp_els = driver.find_elements(By.XPATH, input_box_xpath)
                            if inp_els and inp_els[0].is_displayed():
                                input_box = inp_els[0]
                                chat_opened = True
                                break
                            time.sleep(0.5)

                        if chat_opened:
                            print(f"[DIAG] Chat opened successfully via search for {phone}")
                        else:
                            print(f"[DIAG] Chat did NOT open after clicking search result for {phone}")
                            search_fail_reason = f"Clicking search result for {phone} did not reveal compose input box"
                    else:
                        print(f"[DIAG] No search result appeared within 5s for {phone}")
                        search_fail_reason = f"No matching chat result found in search sidebar for {phone}"

                except Exception as s_err:
                    print(f"[DIAG] Typing '{phone}' into search box or result interaction failed: {str(s_err)}")
                    search_fail_reason = f"Error during search box interaction for {phone}: {str(s_err)}"

            if chat_opened:
                diag_inplace_count += 1
                print(f"[WhatsApp Agent] In-place search succeeded for {phone} (no page reload).")
            else:
                diag_fallback_count += 1
                print(f"[DIAG] FALLBACK TRIGGERED for {phone} — reason: {search_fail_reason}. Falling back to URL navigation...")

            # 2. Fallback to /send?phone=... URL (without text param) for unsaved/new contacts if search didn't open chat
            if not chat_opened:
                try:
                    chat_url = f"https://web.whatsapp.com/send?phone={phone}"
                    driver.get(chat_url)

                    action_start = time.time()
                    while time.time() - action_start < 25:
                        inv_els = driver.find_elements(By.XPATH, invalid_popup_xpath)
                        if inv_els:
                            is_invalid = True
                            try:
                                ok_btns = driver.find_elements(By.XPATH, '//div[@role="button" and (translate(text(), "OK", "ok")="ok")] | //button[contains(translate(., "OK", "ok"), "ok")]')
                                if ok_btns:
                                    ok_btns[0].click()
                            except Exception:
                                pass
                            break

                        inp_els = driver.find_elements(By.XPATH, input_box_xpath)
                        if inp_els:
                            input_box = inp_els[0]
                            chat_opened = True
                            break
                        time.sleep(1)
                except Exception:
                    pass

            if is_invalid:
                status_entry["failed"] += 1
                status_entry["details"].append({
                    "phone": phone,
                    "business_name": biz_name,
                    "status": "failed",
                    "error": "Phone number not registered on WhatsApp",
                    "message": personalized_msg
                })
            elif chat_opened and input_box:
                try:
                    # Focus input box
                    try:
                        input_box.click()
                        time.sleep(0.3)
                    except Exception:
                        pass

                    # Type personalized message reliably simulating real typing
                    try:
                        lines = personalized_msg.split("\n")
                        for line_idx, line in enumerate(lines):
                            if line:
                                input_box.send_keys(line)
                            if line_idx < len(lines) - 1:
                                input_box.send_keys(Keys.SHIFT, Keys.ENTER)
                                time.sleep(0.1)
                    except Exception:
                        driver.execute_script(
                            "arguments[0].focus(); document.execCommand('insertText', false, arguments[1]);",
                            input_box,
                            personalized_msg
                        )

                    time.sleep(0.5)

                    # Click Send button and VERIFY message was actually sent
                    sent_verified = False

                    for attempt in range(1, 3):
                        send_btns = driver.find_elements(By.XPATH, send_button_xpath)
                        if send_btns:
                            try:
                                send_btns[0].click()
                            except Exception:
                                try:
                                    driver.execute_script("arguments[0].click();", send_btns[0])
                                except Exception:
                                    input_box.send_keys(Keys.ENTER)
                        else:
                            input_box.send_keys(Keys.ENTER)

                        time.sleep(2.5)

                        # Verify message was sent (input box text cleared or sent message bubble/checkmark present)
                        curr_text = ""
                        try:
                            curr_text = input_box.text.strip()
                        except Exception:
                            pass

                        sent_els = driver.find_elements(By.XPATH, sent_verification_xpath)

                        if not curr_text or sent_els:
                            sent_verified = True
                            break
                        else:
                            time.sleep(1.5)

                    if sent_verified:
                        status_entry["sent"] += 1
                        status_entry["sent_today"] += 1
                        status_entry["details"].append({
                            "phone": phone,
                            "business_name": biz_name,
                            "status": "sent",
                            "error": None,
                            "message": personalized_msg
                        })
                    else:
                        status_entry["failed"] += 1
                        status_entry["details"].append({
                            "phone": phone,
                            "business_name": biz_name,
                            "status": "failed",
                            "error": "Message did not confirm as sent after retries",
                            "message": personalized_msg
                        })

                except Exception as send_err:
                    status_entry["failed"] += 1
                    status_entry["details"].append({
                        "phone": phone,
                        "business_name": biz_name,
                        "status": "failed",
                        "error": str(send_err),
                        "message": personalized_msg
                    })
            else:
                status_entry["failed"] += 1
                status_entry["details"].append({
                    "phone": phone,
                    "business_name": biz_name,
                    "status": "failed",
                    "error": "Failed to open chat window for recipient within timeout",
                    "message": personalized_msg
                })

            save_progress()

            # Random delay between min_delay and max_delay
            if idx < total_leads - 1:
                delay = random.uniform(min_delay, max_delay)
                time.sleep(delay)

        status_entry["status"] = "completed"
        status_entry["status_message"] = "WhatsApp campaign completed successfully!"
        save_progress()

        summary = {
            "total": total_leads,
            "sent": status_entry["sent"],
            "failed": status_entry["failed"],
            "skipped": status_entry["skipped"],
            "details": status_entry["details"]
        }
        log_campaign(status_entry["file_name"], message_template, summary, user_id)
        print(f"[DIAG SUMMARY] In-place search succeeded: {diag_inplace_count} | Fallback used: {diag_fallback_count}")

    finally:
        if driver:
            try:
                driver.quit()
            except Exception:
                pass


def start_campaign_send(file_name, message_template, min_delay=20, max_delay=40, daily_limit_enabled=False, daily_limit=150, drafts=None, user_id=None):
    """
    Reads leads from file, initializes campaign status, and starts a background worker thread.
    """
    leads = extract_leads_from_excel(file_name)
    if not leads:
        raise ValueError(f"No leads found in Excel file '{file_name}'.")

    campaign_id = str(uuid.uuid4())
    active_campaigns[campaign_id] = {
        "campaign_id": campaign_id,
        "status": "running",
        "status_message": "Initializing...",
        "total": len(leads),
        "sent": 0,
        "failed": 0,
        "skipped": 0,
        "processed_count": 0,
        "sent_today": 0,
        "details": [],
        "error": None,
        "file_name": file_name,
        "message_template": message_template,
        "min_delay": min_delay,
        "max_delay": max_delay,
        "daily_limit_enabled": daily_limit_enabled,
        "daily_limit": daily_limit,
        "leads": leads,
        "drafts": drafts,
        "timestamp": datetime.now().isoformat(),
        "user_id": user_id
    }
    save_progress()

    thread = threading.Thread(
        target=bg_send_whatsapp_worker,
        args=(campaign_id, leads, message_template, min_delay, max_delay, daily_limit_enabled, daily_limit, drafts, 0, user_id)
    )
    thread.daemon = True
    thread.start()

    return campaign_id


def resume_campaign(campaign_id, options=None):
    """
    Resumes a paused or interrupted campaign from its saved progress.
    """
    load_progress()
    if campaign_id not in active_campaigns:
        raise ValueError("Campaign record not found for resume.")

    campaign = active_campaigns[campaign_id]
    campaign["status"] = "running"
    campaign["status_message"] = "Resuming campaign..."
    campaign["sent_today"] = 0  # Reset daily limit counter for new session

    if options:
        if "min_delay" in options:
            campaign["min_delay"] = int(options["min_delay"])
        if "max_delay" in options:
            campaign["max_delay"] = int(options["max_delay"])
        if "daily_limit_enabled" in options:
            campaign["daily_limit_enabled"] = bool(options["daily_limit_enabled"])
        if "daily_limit" in options:
            campaign["daily_limit"] = int(options["daily_limit"])

    save_progress()

    start_idx = campaign.get("processed_count", 0)
    thread = threading.Thread(
        target=bg_send_whatsapp_worker,
        args=(
            campaign_id,
            campaign["leads"],
            campaign["message_template"],
            campaign["min_delay"],
            campaign["max_delay"],
            campaign["daily_limit_enabled"],
            campaign["daily_limit"],
            campaign.get("drafts"),
            start_idx
        )
    )
    thread.daemon = True
    thread.start()

    return campaign_id


def get_campaign_status(campaign_id):
    """
    Returns the campaign status from in-memory or persisted progress.
    """
    if campaign_id in active_campaigns:
        return active_campaigns[campaign_id]

    if os.path.exists(PROGRESS_FILE):
        try:
            with open(PROGRESS_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                return data.get(campaign_id)
        except Exception:
            pass

    return None


def generate_preview_leads(file_name, message_template):
    """
    Returns lead list with pre-generated personalized messages for optional individual customization.
    """
    leads = extract_leads_from_excel(file_name)
    preview_leads = []
    seen = set()

    for lead in leads:
        phone = lead.get("phone", "")
        if not phone or len(phone) < 7:
            continue
        if phone in seen:
            continue
        seen.add(phone)

        personalized_msg = replace_placeholders(message_template, lead)
        preview_leads.append({
            "phone": phone,
            "business_name": lead.get("business_name", "N/A"),
            "review_link": lead.get("review_link", ""),
            "review_stars": lead.get("review_stars", ""),
            "reviewer_name": lead.get("reviewer_name", ""),
            "review_text": lead.get("review_text", ""),
            "review_date": lead.get("review_date", ""),
            "message": personalized_msg
        })

    return preview_leads


def reset_whatsapp_session():
    """
    Closes any active WhatsApp Selenium browser session and deletes/renames
    the persistent session directory (SESSION_DIR) so a new WhatsApp number
    can be scanned on the next campaign run.
    """
    try:
        if not os.path.exists(SESSION_DIR):
            return {"success": True, "message": "No active session folder found to reset."}

        # Attempt deleting session directory
        try:
            shutil.rmtree(SESSION_DIR)
        except Exception:
            # Fallback: rename to backup directory if deletion is blocked
            backup_dir = f"{SESSION_DIR}_old_{int(time.time())}"
            if os.path.exists(backup_dir):
                shutil.rmtree(backup_dir, ignore_errors=True)
            os.rename(SESSION_DIR, backup_dir)

        return {"success": True, "message": "WhatsApp session reset successfully. Next send will prompt for QR scan."}
    except Exception as e:
        return {"success": False, "error": str(e)}

