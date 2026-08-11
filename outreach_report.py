"""
outreach_report.py
------------------
Combined Outreach Reporting Engine — Merges Email campaign history (sent_log.json)
and WhatsApp campaign history (whatsapp_log.json) into a unified report per business,
and exports to outputs/combined_outreach_report.xlsx formatted with xlsxwriter.
"""

import os
import json
import re
import pandas as pd
import xlsxwriter

OUTPUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "outputs")
EMAIL_LOG_FILE = os.path.join(OUTPUT_DIR, "sent_log.json")
WHATSAPP_LOG_FILE = os.path.join(OUTPUT_DIR, "whatsapp_log.json")


def scan_output_excel_mappings(user_id=None):
    """
    Scans all .xlsx report files in outputs/ to build lookup mappings for:
    - email -> business_name, phone
    - phone -> business_name, email
    - business_name -> email, phone
    """
    email_to_biz = {}
    phone_to_biz = {}
    biz_to_info = {}

    if not os.path.exists(OUTPUT_DIR):
        return email_to_biz, phone_to_biz, biz_to_info

    # Exclude combined outreach reports (for any user)
    excel_files = [
        f for f in os.listdir(OUTPUT_DIR) 
        if f.endswith(".xlsx") and not f.endswith("combined_outreach_report.xlsx")
    ]
    if user_id is not None:
        excel_files = [f for f in excel_files if f.startswith(f"user_{user_id}_")]
    else:
        excel_files = [f for f in excel_files if not f.startswith("user_")]

    for fname in excel_files:
        filepath = os.path.join(OUTPUT_DIR, fname)
        try:
            df = pd.read_excel(filepath)
            df = df.ffill()

            for _, row in df.iterrows():
                biz_val = str(row.get("Business Name", "")).strip() if not pd.isna(row.get("Business Name")) else ""
                email_val = str(row.get("Email", "")).strip() if not pd.isna(row.get("Email")) else ""
                phone_val = str(row.get("Phone", "")).strip() if not pd.isna(row.get("Phone")) else ""

                if biz_val.lower() in ("n/a", "none", "null", ""):
                    biz_val = ""
                if email_val.lower() in ("n/a", "none", "null", ""):
                    email_val = ""
                if phone_val.lower() in ("n/a", "none", "null", ""):
                    phone_val = ""

                raw_digits = re.sub(r'[^\d]', '', phone_val)
                if len(raw_digits) < 7:
                    phone_val = ""

                if email_val and biz_val:
                    email_to_biz[email_val.lower()] = biz_val
                if phone_val and biz_val:
                    phone_to_biz[raw_digits] = biz_val

                if biz_val:
                    key = biz_val.lower()
                    if key not in biz_to_info:
                        biz_to_info[key] = {"email": email_val, "phone": phone_val}
                    else:
                        if not biz_to_info[key]["email"] and email_val:
                            biz_to_info[key]["email"] = email_val
                        if not biz_to_info[key]["phone"] and phone_val:
                            biz_to_info[key]["phone"] = phone_val
        except Exception as e:
            print(f"Error scanning excel file {fname} for mappings: {e}")

    return email_to_biz, phone_to_biz, biz_to_info


def build_combined_report(user_id=None):
    """
    Reads sent_log.json and whatsapp_log.json, builds a combined list of rows,
    one per unique business/contact:
    Columns:
    Business Name | Email | Email Sent (Yes/No) | Email Sent At | WhatsApp Number | WhatsApp Sent (Yes/No) | WhatsApp Sent At | Last Campaign Subject/Message
    """
    email_logs = []
    if os.path.exists(EMAIL_LOG_FILE):
        try:
            with open(EMAIL_LOG_FILE, "r", encoding="utf-8") as f:
                email_logs = json.load(f)
                if isinstance(email_logs, list) and user_id is not None:
                    email_logs = [c for c in email_logs if c.get("user_id") == user_id]
        except Exception as e:
            print(f"Error reading sent_log.json: {e}")

    whatsapp_logs = []
    if os.path.exists(WHATSAPP_LOG_FILE):
        try:
            with open(WHATSAPP_LOG_FILE, "r", encoding="utf-8") as f:
                whatsapp_logs = json.load(f)
                if isinstance(whatsapp_logs, list) and user_id is not None:
                    whatsapp_logs = [c for c in whatsapp_logs if c.get("user_id") == user_id]
        except Exception as e:
            print(f"Error reading whatsapp_log.json: {e}")

    email_to_biz, phone_to_biz, biz_to_info = scan_output_excel_mappings(user_id)

    # Dictionary mapping entity_key -> row dict
    # Key strategy: normalized business_name lower if present, else lower email, else raw phone digits
    entities = {}

    def get_or_create_entity(biz_name, email, phone):
        key = None
        clean_biz = biz_name.strip() if biz_name and biz_name.lower() not in ("n/a", "none", "null", "") else ""
        clean_email = email.strip() if email and email.lower() not in ("n/a", "none", "null", "") else ""
        clean_phone = phone.strip() if phone and phone.lower() not in ("n/a", "none", "null", "") else ""

        # Attempt mapping lookup
        if not clean_biz and clean_email and clean_email.lower() in email_to_biz:
            clean_biz = email_to_biz[clean_email.lower()]
        
        raw_digits = re.sub(r'[^\d]', '', clean_phone)
        if not clean_biz and raw_digits and raw_digits in phone_to_biz:
            clean_biz = phone_to_biz[raw_digits]

        if clean_biz:
            key = f"biz:{clean_biz.lower()}"
        elif clean_email:
            key = f"email:{clean_email.lower()}"
        elif raw_digits:
            key = f"phone:{raw_digits}"
        else:
            key = "unknown"

        if key not in entities:
            entities[key] = {
                "Business Name": clean_biz or "N/A",
                "Email": clean_email,
                "Email Sent (Yes/No)": "No",
                "Email Sent At": "",
                "WhatsApp Number": clean_phone,
                "WhatsApp Sent (Yes/No)": "No",
                "WhatsApp Sent At": "",
                "Last Campaign Subject/Message": "",
                "_email_ts": "",
                "_wa_ts": ""
            }
        else:
            if not entities[key]["Business Name"] or entities[key]["Business Name"] == "N/A":
                if clean_biz:
                    entities[key]["Business Name"] = clean_biz
            if not entities[key]["Email"] and clean_email:
                entities[key]["Email"] = clean_email
            if not entities[key]["WhatsApp Number"] and clean_phone:
                entities[key]["WhatsApp Number"] = clean_phone

        return entities[key]

    # Process Email Logs
    for campaign in email_logs:
        timestamp = campaign.get("timestamp", "")
        subject = campaign.get("subject", "")
        result = campaign.get("result", {})
        details = result.get("details", [])

        for item in details:
            recipient_email = item.get("email", "")
            status = item.get("status", "")
            if not recipient_email:
                continue

            entity = get_or_create_entity("", recipient_email, "")

            if status == "sent":
                entity["Email Sent (Yes/No)"] = "Yes"
                if timestamp > entity["_email_ts"]:
                    entity["_email_ts"] = timestamp
                    entity["Email Sent At"] = timestamp.split("T")[0] if "T" in timestamp else timestamp

            # Record last campaign message
            if subject and not entity["Last Campaign Subject/Message"]:
                entity["Last Campaign Subject/Message"] = f"Email: {subject}"

    # Process WhatsApp Logs
    for campaign in whatsapp_logs:
        timestamp = campaign.get("timestamp", "")
        msg_template = campaign.get("message_template", "") or campaign.get("message_preview", "")
        result = campaign.get("result", {})
        details = result.get("details", [])

        for item in details:
            phone = item.get("phone", "")
            biz_name = item.get("business_name", "")
            status = item.get("status", "")

            entity = get_or_create_entity(biz_name, "", phone)

            if status == "sent":
                entity["WhatsApp Sent (Yes/No)"] = "Yes"
                if timestamp > entity["_wa_ts"]:
                    entity["_wa_ts"] = timestamp
                    entity["WhatsApp Sent At"] = timestamp.split("T")[0] if "T" in timestamp else timestamp

            # Record last campaign message if not set or update
            preview = msg_template[:60] + "..." if len(msg_template) > 60 else msg_template
            if preview and (not entity["Last Campaign Subject/Message"] or entity["Last Campaign Subject/Message"].startswith("Email:")):
                entity["Last Campaign Subject/Message"] = f"WhatsApp: {preview}"

    report_rows = []
    for key, data in entities.items():
        row = {
            "Business Name": data["Business Name"],
            "Email": data["Email"] or "N/A",
            "Email Sent (Yes/No)": data["Email Sent (Yes/No)"],
            "Email Sent At": data["Email Sent At"] or "N/A",
            "WhatsApp Number": data["WhatsApp Number"] or "N/A",
            "WhatsApp Sent (Yes/No)": data["WhatsApp Sent (Yes/No)"],
            "WhatsApp Sent At": data["WhatsApp Sent At"] or "N/A",
            "Last Campaign Subject/Message": data["Last Campaign Subject/Message"] or "N/A"
        }
        report_rows.append(row)

    return report_rows


def export_combined_report_to_excel(user_id=None):
    """
    Calls build_combined_report() and writes result to outputs/combined_outreach_report.xlsx
    using xlsxwriter with consistent visual formatting. Returns filename.
    """
    filename = "combined_outreach_report.xlsx"
    if user_id is not None:
        filename = f"user_{user_id}_combined_outreach_report.xlsx"
    filepath = os.path.join(OUTPUT_DIR, filename)

    report_data = build_combined_report(user_id)
    df = pd.DataFrame(report_data)

    if df.empty:
        # Create empty dataframe with specified columns
        df = pd.DataFrame(columns=[
            "Business Name", "Email", "Email Sent (Yes/No)", "Email Sent At",
            "WhatsApp Number", "WhatsApp Sent (Yes/No)", "WhatsApp Sent At",
            "Last Campaign Subject/Message"
        ])

    workbook = xlsxwriter.Workbook(filepath)
    worksheet = workbook.add_worksheet("Outreach Summary")

    header_format = workbook.add_format({
        'bold': True,
        'bg_color': '#D3D3D3',
        'align': 'center',
        'valign': 'vcenter',
        'border': 1
    })

    center_format = workbook.add_format({
        'align': 'center',
        'valign': 'vcenter'
    })

    left_format = workbook.add_format({
        'align': 'left',
        'valign': 'vcenter'
    })

    headers = list(df.columns)
    worksheet.set_row(0, 26)

    for col_idx, header in enumerate(headers):
        worksheet.write(0, col_idx, header, header_format)

    center_cols = {"Email Sent (Yes/No)", "Email Sent At", "WhatsApp Sent (Yes/No)", "WhatsApp Sent At"}
    max_lens = [len(str(h)) for h in headers]

    for r_idx, (_, row) in enumerate(df.iterrows(), start=1):
        worksheet.set_row(r_idx, 20)
        for c_idx, col_name in enumerate(headers):
            val = row[col_name]
            val_str = str(val) if not pd.isna(val) else ""

            if len(val_str) > max_lens[c_idx]:
                max_lens[c_idx] = len(val_str)

            cell_fmt = center_format if col_name in center_cols else left_format
            worksheet.write(r_idx, c_idx, val_str, cell_fmt)

    # Set column widths
    for c_idx, max_len in enumerate(max_lens):
        width = max(max_len + 4, 12)
        if width > 60:
            width = 60
        worksheet.set_column(c_idx, c_idx, width)

    workbook.close()
    return filename
