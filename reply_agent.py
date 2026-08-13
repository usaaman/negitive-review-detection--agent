"""
reply_agent.py
--------------
Email Reply Assistant.

Responsibilities:
- Poll Gmail inbox through IMAP
- Match incoming replies to sent emails
- Analyze replies with Gemini
- Generate response drafts
- Track reply/positive-lead status
- Send approved replies
"""

import os
import re
import json
import imaplib
import smtplib
from datetime import datetime
from email import message_from_bytes
from email.header import decode_header
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.utils import parseaddr, make_msgid
from email.message import Message

import requests
from dotenv import load_dotenv


BASE_DIR = os.path.dirname(os.path.abspath(__file__))
OUTPUT_DIR = os.path.join(BASE_DIR, "outputs")

SENT_LOG_FILE = os.path.join(OUTPUT_DIR, "sent_log.json")
REPLIES_LOG_FILE = os.path.join(OUTPUT_DIR, "reply_log.json")

load_dotenv()


# ============================================================
# Generic JSON helpers
# ============================================================

def _load_json(path, default):
    if not os.path.exists(path):
        return default

    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
            return data
    except Exception:
        return default


def _save_json(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)

    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


# ============================================================
# Sent email records
# ============================================================

def get_sent_records():
    """
    Reads the existing sent_log.json.

    Supports both:
    - old campaign-level format
    - new per-recipient message_id records
    """
    data = _load_json(SENT_LOG_FILE, [])

    if not isinstance(data, list):
        return []

    return data


def get_all_sent_recipients():
    """
    Creates an index of previously contacted email addresses.
    """

    records = get_sent_records()
    index = {}

    for campaign in records:
        result = campaign.get("result", {})
        details = result.get("details", [])

        for detail in details:
            email = (detail.get("email") or "").strip().lower()

            if not email:
                continue

            index[email] = {
                "email": email,
                "subject": campaign.get("subject", ""),
                "message": campaign.get("message", ""),
                "message_preview": campaign.get("message_preview", ""),
                "file_name": campaign.get("file_name", ""),
                "timestamp": campaign.get("timestamp"),
                "message_id": detail.get("message_id"),
                "business_name": detail.get("business_name"),
                "lead_data": detail.get("lead_data", {})
            }

    return index


# ============================================================
# Reply log
# ============================================================

def get_replies(user_id=None):
    data = _load_json(REPLIES_LOG_FILE, [])

    if not isinstance(data, list):
        return []

    if user_id is not None:
        data = [r for r in data if r.get("user_id") == user_id]

    return list(reversed(data))


def save_replies(replies):
    _save_json(REPLIES_LOG_FILE, replies)


def find_reply(reply_id):
    replies = get_replies()

    for reply in replies:
        if reply.get("id") == reply_id:
            return reply

    return None


def update_reply(reply_id, updates):
    replies = _load_json(REPLIES_LOG_FILE, [])

    for item in replies:
        if item.get("id") == reply_id:
            item.update(updates)
            _save_json(REPLIES_LOG_FILE, replies)
            return item

    return None


# ============================================================
# Email header helpers
# ============================================================

def decode_mime_header(value):
    if not value:
        return ""

    decoded = []

    try:
        parts = decode_header(value)

        for part, encoding in parts:
            if isinstance(part, bytes):
                decoded.append(
                    part.decode(encoding or "utf-8", errors="replace")
                )
            else:
                decoded.append(str(part))

        return "".join(decoded)

    except Exception:
        return str(value)


def normalize_message_id(value):
    if not value:
        return ""

    return value.strip().strip("<>").lower()


def get_header(msg, name):
    value = msg.get(name, "")

    if isinstance(value, str):
        return value.strip()

    return ""


# ============================================================
# Email body extraction
# ============================================================

def extract_text_body(msg):
    """
    Extracts plain text from normal email messages.
    Falls back to HTML if needed.
    """

    plain_parts = []
    html_parts = []

    if msg.is_multipart():

        for part in msg.walk():

            content_type = part.get_content_type()
            disposition = str(part.get("Content-Disposition", ""))

            if "attachment" in disposition.lower():
                continue

            try:
                payload = part.get_payload(decode=True)

                if not payload:
                    continue

                charset = part.get_content_charset() or "utf-8"

                text = payload.decode(
                    charset,
                    errors="replace"
                )

                if content_type == "text/plain":
                    plain_parts.append(text)

                elif content_type == "text/html":
                    html_parts.append(text)

            except Exception:
                continue

    else:

        try:
            payload = msg.get_payload(decode=True)

            if payload:
                charset = msg.get_content_charset() or "utf-8"

                text = payload.decode(
                    charset,
                    errors="replace"
                )

                if msg.get_content_type() == "text/plain":
                    plain_parts.append(text)

                else:
                    html_parts.append(text)

        except Exception:
            pass

    if plain_parts:
        return "\n".join(plain_parts).strip()

    if html_parts:
        html = "\n".join(html_parts)

        # Basic HTML cleanup
        html = re.sub(r"<br\s*/?>", "\n", html, flags=re.I)
        html = re.sub(r"</p>", "\n", html, flags=re.I)
        html = re.sub(r"<[^>]+>", "", html)

        return html.strip()

    return ""


def clean_reply_text(text):
    """
    Removes common quoted-reply sections.
    """

    if not text:
        return ""

    patterns = [
        r"\nOn .* wrote:\n",
        r"\nFrom: .*",
        r"\nSent: .*",
        r"\n>.*"
    ]

    cleaned = text

    for pattern in patterns:
        cleaned = re.split(
            pattern,
            cleaned,
            maxsplit=1,
            flags=re.I | re.S
        )[0]

    return cleaned.strip()


# ============================================================
# Gmail IMAP
# ============================================================

def connect_imap(email_address=None, password=None):
    email_address = email_address or os.getenv("EMAIL_ADDRESS", "").strip()
    password = password or os.getenv("EMAIL_APP_PASSWORD", "").strip()

    if not email_address or not password:
        raise RuntimeError(
            "EMAIL_ADDRESS and EMAIL_APP_PASSWORD are required."
        )

    mail = imaplib.IMAP4_SSL("imap.gmail.com", 993)
    mail.login(email_address, password)
    mail.select("INBOX")

    return mail


def _header_matches_sent(msg, sent_records):
    """
    Strongest matching:
    In-Reply-To
    References
    Message-ID
    """

    in_reply_to = normalize_message_id(
        get_header(msg, "In-Reply-To")
    )

    references_raw = get_header(msg, "References")

    references = [
        normalize_message_id(x)
        for x in references_raw.split()
        if x.strip()
    ]

    sender_email = parseaddr(
        get_header(msg, "From")
    )[1].strip().lower()

    subject = decode_mime_header(
        get_header(msg, "Subject")
    ).strip()

    # --------------------------------------------------------
    # 1. Header-based match
    # --------------------------------------------------------

    for record in sent_records:

        message_id = normalize_message_id(
            record.get("message_id")
        )

        if not message_id:
            continue

        if in_reply_to and in_reply_to == message_id:
            return record

        if message_id in references:
            return record

    # --------------------------------------------------------
    # 2. Sender + subject fallback
    # --------------------------------------------------------

    clean_subject = re.sub(
        r"^(re|fw|fwd):\s*",
        "",
        subject,
        flags=re.I
    ).strip().lower()

    for record in sent_records:

        record_email = (
            record.get("email") or ""
        ).strip().lower()

        record_subject = (
            record.get("subject") or ""
        ).strip().lower()

        record_subject = re.sub(
            r"^(re|fw|fwd):\s*",
            "",
            record_subject,
            flags=re.I
        ).strip()

        if (
            sender_email
            and sender_email == record_email
            and clean_subject == record_subject
        ):
            return record

    return None


def check_for_replies(email_address=None, password=None, user_id=None):
    """
    Checks Gmail inbox for recent emails and matches them
    against previously sent emails.
    """

    existing_replies = _load_json(
        REPLIES_LOG_FILE,
        []
    )

    known_message_ids = {
        str(x.get("email_message_id", "")).strip()
        for x in existing_replies
    }

    sent_index = get_all_sent_recipients()

    # Flatten sent records
    sent_records = []

    for email, record in sent_index.items():
        item = dict(record)
        item["email"] = email
        sent_records.append(item)

    if not sent_records:
        return {
            "success": True,
            "new_replies": 0,
            "replies": []
        }

    mail = None
    new_replies = []

    try:
        mail = connect_imap(email_address, password)

        # Search recent/unread messages.
        # We deliberately don't depend only on UNSEEN because
        # an email may have been opened before monitoring runs.
        status, data = mail.search(
            None,
            "ALL"
        )

        if status != "OK":
            return {
                "success": False,
                "error": "Could not search Gmail inbox."
            }

        message_numbers = data[0].split()

        # Only inspect a reasonable recent window.
        message_numbers = message_numbers[-100:]

        for num in message_numbers:

            status, msg_data = mail.fetch(
                num,
                "(RFC822)"
            )

            if status != "OK":
                continue

            raw_email = None

            for response_part in msg_data:
                if isinstance(response_part, tuple):
                    raw_email = response_part[1]
                    break

            if not raw_email:
                continue

            msg = message_from_bytes(raw_email)

            incoming_message_id = normalize_message_id(
                get_header(msg, "Message-ID")
            )

            if (
                incoming_message_id
                and incoming_message_id in known_message_ids
            ):
                continue

            from_email = parseaddr(
                get_header(msg, "From")
            )[1].strip().lower()

            # Ignore emails from ourselves.
            my_email = (email_address or os.getenv("EMAIL_ADDRESS", "")).strip().lower()

            if from_email == my_email:
                continue

            matched = _header_matches_sent(
                msg,
                sent_records
            )

            if not matched:
                continue

            subject = decode_mime_header(
                get_header(msg, "Subject")
            )

            body = clean_reply_text(
                extract_text_body(msg)
            )

            if not body:
                continue

            # Secondary duplicate check based on sender and reply body
            is_dup = False
            for r in existing_replies:
                r_email = (r.get("sender_email") or "").strip().lower()
                if r_email == from_email:
                    r_body = (r.get("reply_body") or "").strip().lower()
                    curr_body = body.strip().lower()
                    if r_body == curr_body:
                        is_dup = True
                        break
            if is_dup:
                continue

            reply_record = {
                "id": make_msgid(),
                "email_message_id": incoming_message_id,
                "received_at": datetime.now().isoformat(),
                "user_id": user_id,

                "sender_email": from_email,
                "sender_name": parseaddr(
                    get_header(msg, "From")
                )[0],

                "subject": subject,
                "reply_body": body,

                "original_message_id": matched.get(
                    "message_id"
                ),
                "original_subject": matched.get(
                    "subject",
                    ""
                ),
                "original_message": matched.get(
                    "message",
                    ""
                ),

                "business_name": matched.get(
                    "business_name"
                ),
                "file_name": matched.get(
                    "file_name"
                ),
                "lead_data": matched.get(
                    "lead_data",
                    {}
                ),

                "status": "New",
                "intent": "unknown",
                "ai_draft": "",
                "ai_reason": "",
                "replied_at": None
            }

            existing_replies.append(reply_record)
            new_replies.append(reply_record)

            if incoming_message_id:
                known_message_ids.add(
                    incoming_message_id
                )

        save_replies(existing_replies)

        return {
            "success": True,
            "new_replies": len(new_replies),
            "replies": new_replies
        }

    finally:
        if mail:
            try:
                mail.close()
            except Exception:
                pass

            try:
                mail.logout()
            except Exception:
                pass


# ============================================================
# Gemini
# ============================================================

def analyze_reply_with_gemini(reply):
    """
    Gemini classifies the reply and generates a suggested response.
    """

    api_key = os.getenv(
        "GEMINI_API_KEY",
        ""
    ).strip()

    if not api_key:
        raise RuntimeError(
            "GEMINI_API_KEY is missing from .env"
        )

    model = os.getenv(
        "GEMINI_MODEL",
        "gemini-flash-latest"
    ).strip()

    lead_data = reply.get(
        "lead_data",
        {}
    )

    prompt = f"""
You are an email outreach reply assistant.

Analyze the business reply below.

IMPORTANT:
- Use only facts provided in the context.
- Do not invent services, prices, reviews, results, or business information.
- Do not claim that the customer agreed to buy unless their message clearly indicates interest.
- Keep the suggested response professional and concise.
- If the sender asks a question, answer only using information available in context.
- If information is missing, suggest asking the human user to provide it.
- Sign off the response using the name 'Reputation Specialist' and the company 'US agents'. Do NOT use any placeholders like '[Your Name]', '[Your Agency]', or '[Company Name]'.

BUSINESS:
{reply.get("business_name") or "Unknown"}

LEAD DATA:
{json.dumps(lead_data, ensure_ascii=False, indent=2)}

ORIGINAL EMAIL:
{reply.get("original_message", "")}

CUSTOMER REPLY:
{reply.get("reply_body", "")}

Return ONLY valid JSON in this exact structure:

{{
  "intent": "positive_interest | question | neutral | negative | unsubscribe | other",
  "positive_lead": true,
  "reason": "short explanation",
  "response": "professional response draft"
}}

Set positive_lead=true ONLY if the customer clearly expresses interest
in receiving the service, discussing the service, pricing, a call,
a meeting, or next steps.
"""

    url = (
        "https://generativelanguage.googleapis.com/v1beta/"
        f"models/{model}:generateContent"
        f"?key={api_key}"
    )

    response = requests.post(
        url,
        json={
            "contents": [
                {
                    "parts": [
                        {
                            "text": prompt
                        }
                    ]
                }
            ],
            "generationConfig": {
                "temperature": 0.2,
                "responseMimeType": "application/json"
            }
        },
        timeout=60
    )

    response.raise_for_status()

    data = response.json()

    text = (
        data["candidates"][0]["content"]["parts"][0]["text"]
    ).strip()

    # Gemini can occasionally wrap JSON in ```json
    text = re.sub(
        r"^```json\s*|\s*```$",
        "",
        text,
        flags=re.I
    ).strip()

    result = json.loads(text)

    intent = result.get(
        "intent",
        "other"
    )

    positive = bool(
        result.get("positive_lead", False)
    )

    # Strongly enforce positive-lead state.
    if intent not in {
        "positive_interest",
        "question",
        "neutral",
        "negative",
        "unsubscribe",
        "other"
    }:
        intent = "other"

    status = (
        "Positive Lead"
        if positive
        else "AI Draft Ready"
    )

    updated = update_reply(
        reply["id"],
        {
            "status": status,
            "intent": intent,
            "ai_draft": result.get(
                "response",
                ""
            ),
            "ai_reason": result.get(
                "reason",
                ""
            ),
            "positive_lead": positive
        }
    )

    return updated


# ============================================================
# Reply sending
# ============================================================

def send_reply(reply_id, response_text, sender_email=None, sender_password=None):
    """
    Sends an approved response as a new email in the
    same logical conversation.
    """

    response_text = (
        response_text or ""
    ).strip()

    if not response_text:
        return {
            "success": False,
            "error": "Response cannot be empty."
        }

    reply = find_reply(reply_id)

    if not reply:
        return {
            "success": False,
            "error": "Reply record not found."
        }

    sender_email = sender_email or os.getenv(
        "EMAIL_ADDRESS",
        ""
    ).strip()

    sender_password = sender_password or os.getenv(
        "EMAIL_APP_PASSWORD",
        ""
    ).strip()

    if not sender_email or not sender_password:
        return {
            "success": False,
            "error": "Gmail credentials are missing."
        }

    recipient = (
        reply.get("sender_email")
        or ""
    ).strip()

    if not recipient:
        return {
            "success": False,
            "error": "Reply sender email is missing."
        }

    subject = reply.get(
        "original_subject",
        ""
    ).strip()

    if not subject.lower().startswith("re:"):
        subject = "Re: " + subject

    msg = MIMEMultipart()
    msg["From"] = sender_email
    msg["To"] = recipient
    msg["Subject"] = subject

    # Maintain Gmail conversation/thread semantics.
    original_message_id = normalize_message_id(
        reply.get("email_message_id")
        or reply.get("original_message_id")
    )

    if original_message_id:
        msg["In-Reply-To"] = f"<{original_message_id}>"
        msg["References"] = f"<{original_message_id}>"

    msg.attach(
        MIMEText(
            response_text,
            "plain",
            "utf-8"
        )
    )

    try:
        server = smtplib.SMTP(
            "smtp.gmail.com",
            587,
            timeout=30
        )

        server.starttls()

        server.login(
            sender_email,
            sender_password
        )

        server.sendmail(
            sender_email,
            recipient,
            msg.as_string()
        )

        server.quit()

    except Exception as e:
        return {
            "success": False,
            "error": str(e)
        }

    updated = update_reply(
        reply_id,
        {
            "status": "Replied",
            "final_response": response_text,
            "replied_at": datetime.now().isoformat()
        }
    )

    return {
        "success": True,
        "reply": updated
    }
