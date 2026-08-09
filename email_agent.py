"""
email_agent.py
--------------
Email Agent Core Logic — Handles scanning outputs/ directory for generated
Excel files, extracting unique valid business email addresses, and sending
individual customized emails via Gmail SMTP.
"""

import os
import re
import time
import json
import smtplib
from datetime import datetime
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import pandas as pd
from dotenv import load_dotenv

OUTPUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "outputs")
LOG_FILE = os.path.join(OUTPUT_DIR, "sent_log.json")


def is_valid_email(email_str):
    """Simple check to ensure email string is valid and not N/A or placeholder."""
    if not email_str or not isinstance(email_str, str):
        return False
    clean = email_str.strip().lower()
    if clean in ("n/a", "none", "null", ""):
        return False
    # Basic email pattern check
    return bool(re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", clean))


def extract_emails_from_excel(filename):
    """
    Reads the 'Email' column from a given .xlsx file in outputs/ folder.
    Returns a deduplicated list of valid email strings.
    """
    filepath = os.path.join(OUTPUT_DIR, filename)
    if not os.path.exists(filepath):
        return []

    try:
        df = pd.read_excel(filepath)
        if "Email" not in df.columns:
            return []

        raw_emails = df["Email"].dropna().astype(str).tolist()
        valid_emails = []
        seen = set()

        for em in raw_emails:
            clean_email = em.strip()
            if is_valid_email(clean_email):
                lower_email = clean_email.lower()
                if lower_email not in seen:
                    seen.add(lower_email)
                    valid_emails.append(clean_email)

        return valid_emails
    except Exception as e:
        print(f"Error reading excel file {filename}: {e}")
        return []


def get_available_files():
    """
    Lists all .xlsx files in the outputs/ directory along with the count
    of valid email addresses in each file.
    """
    if not os.path.exists(OUTPUT_DIR):
        return []

    files = [f for f in os.listdir(OUTPUT_DIR) if f.endswith(".xlsx")]
    file_info_list = []

    # Sort files by last modified time (newest first)
    files.sort(key=lambda x: os.path.getmtime(os.path.join(OUTPUT_DIR, x)), reverse=True)

    for fname in files:
        emails = extract_emails_from_excel(fname)
        file_info_list.append({
            "filename": fname,
            "valid_email_count": len(emails)
        })

    return file_info_list


def log_campaign(file_name, subject, message, result):
    """
    Logs campaign send results into outputs/sent_log.json.
    """
    history = []
    if os.path.exists(LOG_FILE):
        try:
            with open(LOG_FILE, "r", encoding="utf-8") as f:
                history = json.load(f)
        except Exception as e:
            print(f"Error reading sent_log.json: {e}")
            history = []

    log_entry = {
        "timestamp": datetime.now().isoformat(),
        "file_name": file_name,
        "subject": subject,
        "message_preview": message[:100] if message else "",
        "result": result
    }

    history.append(log_entry)

    try:
        with open(LOG_FILE, "w", encoding="utf-8") as f:
            json.dump(history, f, indent=2)
    except Exception as e:
        print(f"Error writing to sent_log.json: {e}")


def get_campaign_history():
    """
    Reads outputs/sent_log.json and returns past campaign entries, most recent first.
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
        print(f"Error reading campaign history: {e}")
        return []


def send_emails(filename, subject, message):
    """
    Sends customized emails to all extracted recipients from the specified excel file.
    Uses Gmail SMTP (smtp.gmail.com:587 TLS).
    Returns summary dict with sent/failed counts and recipient details.
    """
    load_dotenv()
    sender_email = os.getenv("EMAIL_ADDRESS", "").strip()
    sender_password = os.getenv("EMAIL_APP_PASSWORD", "").strip()

    if not sender_email or not sender_password:
        return {
            "success": False,
            "error": "Email credentials not configured in .env (EMAIL_ADDRESS and EMAIL_APP_PASSWORD required)."
        }

    emails = extract_emails_from_excel(filename)
    if not emails:
        return {
            "success": False,
            "error": f"Selected file '{filename}' has no valid email addresses to send to."
        }

    if not subject or not subject.strip():
        return {"success": False, "error": "Subject line cannot be empty."}

    if not message or not message.strip():
        return {"success": False, "error": "Message body cannot be empty."}

    # Connect to Gmail SMTP server
    try:
        server = smtplib.SMTP("smtp.gmail.com", 587, timeout=30)
        server.starttls()
        server.login(sender_email, sender_password)
    except Exception as e:
        return {
            "success": False,
            "error": f"Failed to connect/authenticate with Gmail SMTP: {str(e)}"
        }

    sent_count = 0
    failed_count = 0
    details = []
    total_emails = len(emails)

    for idx, recipient in enumerate(emails):
        try:
            msg = MIMEMultipart()
            msg["From"] = sender_email
            msg["To"] = recipient
            msg["Subject"] = subject
            msg.attach(MIMEText(message, "plain", "utf-8"))

            server.sendmail(sender_email, recipient, msg.as_string())
            sent_count += 1
            details.append({
                "email": recipient,
                "status": "sent",
                "error": None
            })
        except Exception as e:
            failed_count += 1
            details.append({
                "email": recipient,
                "status": "failed",
                "error": str(e)
            })

        # Delay of 1.5 seconds to avoid Gmail rate limits (except after the last email)
        if idx < total_emails - 1:
            time.sleep(1.5)

    try:
        server.quit()
    except Exception:
        pass

    summary = {
        "success": True,
        "total": len(emails),
        "sent": sent_count,
        "failed": failed_count,
        "details": details
    }

    log_campaign(filename, subject, message, summary)
    return summary
