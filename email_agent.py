"""
email_agent.py
--------------
Email Agent Core Logic — Handles scanning outputs/ directory for generated
Excel files, extracting unique valid business email addresses, performing template
personalization, and sending emails asynchronously in a background thread via Gmail SMTP.
"""

import os
import re
import time
import json
import smtplib
import threading
import uuid
from datetime import datetime
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.header import Header
from email.utils import make_msgid
import pandas as pd
from dotenv import load_dotenv

OUTPUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "outputs")
LOG_FILE = os.path.join(OUTPUT_DIR, "sent_log.json")

# In-memory status store for active email campaigns
# Structure:
# {
#   "campaign_id": {
#       "status": "running" | "completed" | "failed",
#       "total": int,
#       "sent": int,
#       "failed": int,
#       "details": [{"email": str, "status": "sent"|"failed", "error": str|None}],
#       "error": str|None,
#       "file_name": str,
#       "subject": str,
#       "timestamp": str
#   }
# }
active_campaigns = {}


def is_valid_email(email_str):
    """Simple check to ensure email string is valid and not N/A or placeholder."""
    if not email_str or not isinstance(email_str, str):
        return False
    clean = email_str.strip().lower()
    if clean in ("n/a", "none", "null", ""):
        return False
    # Basic email pattern check
    return bool(re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", clean))


def extract_leads_from_excel(filename):
    """
    Reads complete lead rows so reply tracking can preserve
    business context, while maintaining snake_case keys for template interpolation.
    """
    filepath = os.path.join(OUTPUT_DIR, filename)
    if not os.path.exists(filepath):
        return []

    try:
        df = pd.read_excel(filepath)
        
        # Apply forward fill to handle merged cells from xlsxwriter
        df = df.ffill()
        
        leads = []
        seen = set()

        for _, row in df.iterrows():
            email_val = row.get("Email")
            if pd.isna(email_val):
                continue
            email_str = str(email_val).strip()
            
            if is_valid_email(email_str):
                lower_email = email_str.lower()
                if lower_email not in seen:
                    seen.add(lower_email)
                    
                    lead = {}
                    # Preserve all raw columns as strings
                    for column in df.columns:
                        value = row.get(column)
                        val_str = str(value).strip() if not pd.isna(value) else ""
                        col_str = str(column)
                        lead[col_str] = val_str
                        # Support snake_case keys for backward compatibility
                        col_clean = col_str.strip().lower().replace(" ", "_")
                        lead[col_clean] = val_str

                    # Ensure essential fields exist even if columns are missing
                    lead.setdefault("email", email_str)
                    if "business_name" not in lead or lead["business_name"] == "":
                        lead["business_name"] = lead.get("Business Name") or lead.get("Business") or lead.get("Name") or "N/A"
                    lead.setdefault("website", "N/A")
                    lead.setdefault("reviewer_name", "N/A")
                    lead.setdefault("review_stars", "N/A")
                    lead.setdefault("review_text", "")
                    lead.setdefault("review_date", "N/A")
                    lead.setdefault("review_link", "N/A")
                    lead.setdefault("business_maps_link", "N/A")

                    leads.append(lead)

        return leads
    except Exception as e:
        print(f"Error reading leads from excel file {filename}: {e}")
        return []


def extract_emails_from_excel(filename):
    """
    Backwards compatibility: Returns a list of unique email strings from Excel.
    """
    leads = extract_leads_from_excel(filename)
    return [lead["email"] for lead in leads]


def get_available_files(user_id=None):
    """
    Lists all .xlsx files in the outputs/ directory along with the count
    of valid email addresses in each file.
    """
    if not os.path.exists(OUTPUT_DIR):
        return []

    files = [f for f in os.listdir(OUTPUT_DIR) if f.endswith(".xlsx")]
    if user_id is not None:
        files = [f for f in files if f.startswith(f"user_{user_id}_")]
    else:
        files = [f for f in files if not f.startswith("user_")]

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


def log_campaign(file_name, subject, message, result, user_id=None):
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
        "message_body": message,
        "result": result,
        "user_id": user_id
    }

    history.append(log_entry)

    try:
        with open(LOG_FILE, "w", encoding="utf-8") as f:
            json.dump(history, f, indent=2)
    except Exception as e:
        print(f"Error writing to sent_log.json: {e}")


def get_campaign_history(user_id=None):
    """
    Reads outputs/sent_log.json and returns past campaign entries, most recent first.
    """
    if not os.path.exists(LOG_FILE):
        return []

    try:
        with open(LOG_FILE, "r", encoding="utf-8") as f:
            history = json.load(f)
            if isinstance(history, list):
                if user_id is not None:
                    history = [c for c in history if c.get("user_id") == user_id]
                return list(reversed(history))
            return []
    except Exception as e:
        print(f"Error reading campaign history: {e}")
        return []


def replace_placeholders(text, lead):
    """
    Performs case-insensitive replacement of personalization placeholders in templates.
    """
    if not text:
        return ""
    t = text
    t = re.sub(r'(?i)\{business_name\}', lead.get("business_name", ""), t)
    t = re.sub(r'(?i)\{website\}', lead.get("website", ""), t)
    t = re.sub(r'(?i)\{reviewer_name\}', lead.get("reviewer_name", ""), t)
    t = re.sub(r'(?i)\{review_stars\}', lead.get("review_stars", ""), t)
    t = re.sub(r'(?i)\{review_text\}', lead.get("review_text", ""), t)
    t = re.sub(r'(?i)\{review_date\}', lead.get("review_date", ""), t)
    t = re.sub(r'(?i)\{review_link\}', lead.get("review_link", ""), t)
    t = re.sub(r'(?i)\{business_maps_link\}', lead.get("business_maps_link", ""), t)
    return t


def bg_send_emails_worker(campaign_id, leads, subject, message, sender_name, file_name, sender_email=None, sender_password=None, user_id=None):
    """
    Worker function executed in a background thread to send template-replaced emails.
    """
    load_dotenv()
    email_address = sender_email or os.getenv("EMAIL_ADDRESS", "").strip()
    password = sender_password or os.getenv("EMAIL_APP_PASSWORD", "").strip()

    status_entry = active_campaigns[campaign_id]

    if not email_address or not password:
        status_entry["status"] = "failed"
        status_entry["error"] = "Email credentials not configured."
        return

    # Connect to Gmail SMTP server
    try:
        server = smtplib.SMTP("smtp.gmail.com", 587, timeout=30)
        server.starttls()
        server.login(email_address, password)
    except Exception as e:
        status_entry["status"] = "failed"
        status_entry["error"] = f"Failed to connect/authenticate with Gmail SMTP: {str(e)}"
        return

    total_leads = len(leads)

    for idx, lead in enumerate(leads):
        recipient = lead["email"]
        try:
            # Perform personalization replacement if not pre-generated
            personalized_subject = lead.get("subject") or replace_placeholders(subject, lead)
            personalized_message = lead.get("body") or replace_placeholders(message, lead)

            msg = MIMEMultipart()
            
            message_id = make_msgid()

            # Format display name if provided
            if sender_name:
                msg["From"] = f"{Header(sender_name, 'utf-8').encode()} <{email_address}>"
            else:
                msg["From"] = email_address
                
            msg["To"] = recipient
            msg["Subject"] = personalized_subject
            msg["Message-ID"] = message_id
            
            msg.attach(MIMEText(personalized_message, "plain", "utf-8"))

            server.sendmail(email_address, recipient, msg.as_string())
            
            status_entry["sent"] += 1
            status_entry["details"].append({
                "email": recipient,
                "status": "sent",
                "error": None,
                "message_id": message_id,
                "business_name": lead.get("business_name") or lead.get("Business Name") or lead.get("Business") or lead.get("Name") or "",
                "lead_data": lead
            })
        except Exception as e:
            status_entry["failed"] += 1
            status_entry["details"].append({
                "email": recipient,
                "status": "failed",
                "error": str(e),
                "message_id": None,
                "business_name": lead.get("business_name") or lead.get("Business Name") or lead.get("Business") or lead.get("Name") or "",
                "lead_data": lead
            })

        # Update in-memory status periodically
        # Delay of 1.5 seconds to avoid Gmail rate limits
        if idx < total_leads - 1:
            time.sleep(1.5)

    try:
        server.quit()
    except Exception:
        pass

    status_entry["status"] = "completed"
    
    # Save the final log entry to sent_log.json
    summary = {
        "success": True,
        "total": total_leads,
        "sent": status_entry["sent"],
        "failed": status_entry["failed"],
        "details": status_entry["details"]
    }
    log_campaign(file_name, subject, message, summary, user_id)


def start_campaign_send(leads, subject, message, sender_name, file_name, sender_email=None, sender_password=None, user_id=None):
    """
    Initializes campaign tracking state and starts a background sending thread.
    Returns the campaign_id.
    """
    campaign_id = str(uuid.uuid4())
    active_campaigns[campaign_id] = {
        "status": "running",
        "total": len(leads),
        "sent": 0,
        "failed": 0,
        "details": [],
        "error": None,
        "file_name": file_name,
        "subject": subject,
        "timestamp": datetime.now().isoformat(),
        "user_id": user_id
    }

    # Spawn thread
    thread = threading.Thread(
        target=bg_send_emails_worker,
        args=(campaign_id, leads, subject, message, sender_name, file_name, sender_email, sender_password, user_id)
    )
    thread.daemon = True
    thread.start()

    return campaign_id


def get_campaign_status(campaign_id):
    """
    Returns the campaign send status dictionary from in-memory tracking.
    """
    return active_campaigns.get(campaign_id)
