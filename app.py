"""
app.py
-------
Flask backend — serves the UI and coordinates scans, campaigns, and replies
using user-specific credentials.
"""

from flask import Flask, render_template, request, jsonify, send_from_directory, redirect, flash
import os
import traceback
import smtplib
import uuid
from apify_client import ApifyClient
from werkzeug.security import generate_password_hash, check_password_hash
from flask_login import LoginManager, login_user, logout_user, login_required, current_user

# Local modules
import agent_logic
import email_agent
import whatsapp_agent
import reply_agent
import ai_helper
from models import db, User, GmailAccount, ApifyToken
from crypto_utils import encrypt_value, decrypt_value, ensure_keys_in_env

app = Flask(__name__)

# Ensure keys are loaded in .env and reload them
ensure_keys_in_env()

app.config['SECRET_KEY'] = os.getenv("SECRET_KEY", "default_secret_key")
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///database.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

# Initialize DB and LoginManager
db.init_app(app)
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = "login"

with app.app_context():
    db.create_all()
    # Auto-migrate SQLite if token_type is missing
    from sqlalchemy import text
    try:
        db.session.execute(text("SELECT token_type FROM apify_token LIMIT 1"))
    except Exception:
        db.session.rollback()
        try:
            db.session.execute(text("ALTER TABLE apify_token ADD COLUMN token_type VARCHAR(50) DEFAULT 'maps'"))
            db.session.commit()
            print("Database migrated successfully: added token_type column to apify_token.")
        except Exception as migrate_err:
            print(f"Migration error: {migrate_err}")

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))


# ---------- Verification Helpers ----------

def test_gmail_login(email, app_password):
    try:
        server = smtplib.SMTP("smtp.gmail.com", 587, timeout=15)
        server.starttls()
        server.login(email, app_password)
        server.quit()
        return True, None
    except Exception as e:
        return False, str(e)


def test_apify_token(token):
    try:
        client = ApifyClient(token)
        client.user().get()
        return True, None
    except Exception as e:
        return False, str(e)


# ---------- Masking Helpers ----------

def mask_email(email):
    if not email or "@" not in email:
        return ""
    name, domain = email.split("@", 1)
    if len(name) <= 1:
        return f"{name}***@{domain}"
    return f"{name[0]}***{name[-1]}@{domain}"


def mask_token(token):
    if not token:
        return ""
    if len(token) <= 8:
        return "****"
    if token.startswith("apify_api_"):
        rest = token[len("apify_api_"):]
        if len(rest) <= 4:
            return "apify_api_****"
        return f"apify_api_****{rest[-4:]}"
    return f"{token[:4]}****{token[-4:]}"


# ---------- Authentication Routes ----------

@app.route("/signup", methods=["GET", "POST"])
def signup():
    if current_user.is_authenticated:
        return redirect("/")
    if request.method == "POST":
        email = request.form.get("email", "").strip()
        password = request.form.get("password", "").strip()
        gmail_address = request.form.get("gmail_address", "").strip()
        gmail_app_password = request.form.get("gmail_app_password", "").strip()

        # Check user exists
        if User.query.filter_by(email=email).first():
            return render_template(
                "signup.html",
                general_error="Email already registered.",
                email=email,
                gmail_address=gmail_address
            )

        # Validate Gmail SMTP
        smtp_ok, smtp_err = test_gmail_login(gmail_address, gmail_app_password)
        if not smtp_ok:
            return render_template(
                "signup.html",
                smtp_error=smtp_err,
                email=email,
                gmail_address=gmail_address
            )

        # Save to DB
        hashed = generate_password_hash(password)
        user = User(email=email, password_hash=hashed)
        db.session.add(user)
        db.session.flush()  # populate user.id

        enc_gmail_pass = encrypt_value(gmail_app_password)
        gmail_acc = GmailAccount(
            user_id=user.id,
            email=gmail_address,
            encrypted_app_password=enc_gmail_pass,
            is_default=True
        )

        db.session.add(gmail_acc)
        db.session.commit()

        login_user(user, remember=True)
        return redirect("/")

    return render_template("signup.html")


@app.route("/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        return redirect("/")
    if request.method == "POST":
        email = request.form.get("email", "").strip()
        password = request.form.get("password", "").strip()
        
        user = User.query.filter_by(email=email).first()
        if user and check_password_hash(user.password_hash, password):
            login_user(user, remember=True)
            return redirect("/")
        else:
            return render_template(
                "login.html",
                error="Invalid login email or password.",
                email=email
            )
    return render_template("login.html")


@app.route("/logout")
@login_required
def logout():
    logout_user()
    return redirect("/login")


# ---------- Settings Route ----------

@app.route("/settings", methods=["GET", "POST"])
@login_required
def settings():
    if request.method == "POST":
        action = request.form.get("action")
        if action == "update_apify":
            maps_token = request.form.get("maps_apify_token", "").strip()
            contact_token = request.form.get("contact_apify_token", "").strip()
            
            updated_any = False
            
            if maps_token:
                ok, err = test_apify_token(maps_token)
                if ok:
                    ApifyToken.query.filter_by(user_id=current_user.id, token_type="maps").update({ApifyToken.is_default: False})
                    ApifyToken.query.filter_by(user_id=current_user.id, token_type=None).update({ApifyToken.is_default: False})
                    ApifyToken.query.filter_by(user_id=current_user.id, token_type="").update({ApifyToken.is_default: False})
                    
                    new_maps = ApifyToken(
                        user_id=current_user.id,
                        encrypted_token=encrypt_value(maps_token),
                        token_type="maps",
                        is_default=True
                    )
                    db.session.add(new_maps)
                    updated_any = True
                else:
                    flash(f"Failed to update Maps Token: {err}", "danger")
                    return redirect("/settings")
                    
            if contact_token:
                ok, err = test_apify_token(contact_token)
                if ok:
                    ApifyToken.query.filter_by(user_id=current_user.id, token_type="contact").update({ApifyToken.is_default: False})
                    
                    new_contact = ApifyToken(
                        user_id=current_user.id,
                        encrypted_token=encrypt_value(contact_token),
                        token_type="contact",
                        is_default=True
                    )
                    db.session.add(new_contact)
                    updated_any = True
                else:
                    flash(f"Failed to update Email Finder Token: {err}", "danger")
                    return redirect("/settings")
                    
            if updated_any:
                db.session.commit()
                flash("Apify API Token(s) updated successfully!", "success")
            else:
                flash("No tokens were entered to update.", "info")

        elif action == "add_gmail":
            new_email = request.form.get("gmail_address", "").strip()
            new_password = request.form.get("gmail_app_password", "").strip()
            ok, err = test_gmail_login(new_email, new_password)
            if ok:
                existing = GmailAccount.query.filter_by(user_id=current_user.id, email=new_email).first()
                if existing:
                    existing.encrypted_app_password = encrypt_value(new_password)
                else:
                    is_def = (GmailAccount.query.filter_by(user_id=current_user.id).count() == 0)
                    new_acc = GmailAccount(
                        user_id=current_user.id,
                        email=new_email,
                        encrypted_app_password=encrypt_value(new_password),
                        is_default=is_def
                    )
                    db.session.add(new_acc)
                db.session.commit()
                flash("Gmail account connected successfully!", "success")
            else:
                flash(f"Failed to connect Gmail account: {err}", "danger")

        elif action == "set_default_gmail":
            acc_id = request.form.get("account_id")
            acc = GmailAccount.query.filter_by(id=acc_id, user_id=current_user.id).first()
            if acc:
                GmailAccount.query.filter_by(user_id=current_user.id).update({GmailAccount.is_default: False})
                acc.is_default = True
                db.session.commit()
                flash(f"Default sender set to {acc.email}.", "success")

        elif action == "delete_gmail":
            acc_id = request.form.get("account_id")
            acc = GmailAccount.query.filter_by(id=acc_id, user_id=current_user.id).first()
            if acc:
                count = GmailAccount.query.filter_by(user_id=current_user.id).count()
                if count <= 1:
                    flash("You must keep at least one Gmail account connected.", "danger")
                else:
                    was_default = acc.is_default
                    db.session.delete(acc)
                    db.session.commit()
                    if was_default:
                        other = GmailAccount.query.filter_by(user_id=current_user.id).first()
                        if other:
                            other.is_default = True
                            db.session.commit()
                    flash("Gmail account disconnected.", "success")

        return redirect("/settings")

    default_gmail = GmailAccount.query.filter_by(user_id=current_user.id, is_default=True).first()
    
    # Query maps and contact default tokens
    apify_maps = ApifyToken.query.filter_by(user_id=current_user.id, token_type="maps", is_default=True).first()
    if not apify_maps:
        # Fallback to legacy is_default=True
        apify_maps = ApifyToken.query.filter_by(user_id=current_user.id, is_default=True).first()
        
    apify_contact = ApifyToken.query.filter_by(user_id=current_user.id, token_type="contact", is_default=True).first()
    
    gmail_accounts = GmailAccount.query.filter_by(user_id=current_user.id).all()

    maps_token_decrypted = decrypt_value(apify_maps.encrypted_token) if apify_maps else ""
    contact_token_decrypted = decrypt_value(apify_contact.encrypted_token) if apify_contact else ""

    default_email_masked = mask_email(default_gmail.email) if default_gmail else None
    default_token_maps_masked = mask_token(maps_token_decrypted) if maps_token_decrypted else None
    default_token_contact_masked = mask_token(contact_token_decrypted) if contact_token_decrypted else None

    return render_template(
        "settings.html",
        gmail_accounts=gmail_accounts,
        default_email_masked=default_email_masked,
        default_token_maps_masked=default_token_maps_masked,
        default_token_contact_masked=default_token_contact_masked
    )


# ---------- Core Studio Routes ----------

@app.route("/")
@login_required
def home():
    return render_template("index.html")


@app.route("/scan", methods=["POST"])
@login_required
def scan():
    data = request.get_json()

    location = data.get("location", "").strip()
    category = data.get("category", "").strip()
    max_businesses = int(data.get("max_businesses", 10))
    max_reviews = int(data.get("max_reviews", 10))
    rating_threshold = float(data.get("rating_threshold", 4.5))
    negative_star_max = int(data.get("negative_star_max", 3))

    if not location or not category:
        return jsonify({"error": "Location aur category dono zaroori hain."}), 400

    try:
        apify_maps = ApifyToken.query.filter_by(user_id=current_user.id, token_type="maps", is_default=True).first()
        if not apify_maps:
            apify_maps = ApifyToken.query.filter_by(user_id=current_user.id, is_default=True).first()
            
        if not apify_maps:
            return jsonify({"error": "No active Google Maps Apify token configured. Please configure it in Settings."}), 400
        
        api_token = decrypt_value(apify_maps.encrypted_token)

        scan_id = agent_logic.start_scan_job(
            location, category, max_businesses, max_reviews,
            rating_threshold, negative_star_max,
            api_token=api_token, user_id=current_user.id
        )
        return jsonify({
            "success": True,
            "scan_id": scan_id
        })
    except Exception as e:
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500


@app.route("/scan/status/<scan_id>")
@login_required
def scan_status(scan_id):
    try:
        status = agent_logic.get_scan_status(scan_id)
        if not status:
            return jsonify({"error": "Scan not found."}), 404
        return jsonify(status)
    except Exception as e:
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500


@app.route("/business-search/run", methods=["POST"])
@login_required
def business_search_run():
    data = request.get_json()
    business_name = data.get("business_name", "").strip()
    location = data.get("location", "").strip()
    max_reviews_limit = int(data.get("max_reviews_limit", 20))
    negative_star_max = int(data.get("negative_star_max", 3))

    if not business_name or not location:
        return jsonify({"error": "Business name aur location dono zaroori hain."}), 400

    try:
        apify_maps = ApifyToken.query.filter_by(user_id=current_user.id, token_type="maps", is_default=True).first()
        if not apify_maps:
            apify_maps = ApifyToken.query.filter_by(user_id=current_user.id, is_default=True).first()
            
        if not apify_maps:
            return jsonify({"error": "No active Google Maps Apify token configured. Please configure it in Settings."}), 400
        
        api_token = decrypt_value(apify_maps.encrypted_token)

        job_id = agent_logic.start_business_search_job(
            business_name, location, max_reviews_limit, negative_star_max, api_token=api_token, user_id=current_user.id
        )
        return jsonify({"job_id": job_id})
    except Exception as e:
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500


@app.route("/business-search/status/<job_id>")
@login_required
def business_search_status(job_id):
    try:
        status = agent_logic.get_business_search_status(job_id)
        if not status:
            return jsonify({"error": "Job not found."}), 404
        return jsonify(status)
    except Exception as e:
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500


@app.route("/download/<filename>")
@login_required
def download(filename):
    # Security block: prevent cross-user file download
    if not filename.startswith(f"user_{current_user.id}_"):
        return jsonify({"error": "Unauthorized file access."}), 403
    return send_from_directory(agent_logic.OUTPUT_DIR, filename, as_attachment=True)


# ---------- Email Agent Routes ----------

@app.route("/email-agent")
@login_required
def email_agent_home():
    return render_template("email_agent.html")


@app.route("/email-agent/files")
@login_required
def email_agent_files():
    try:
        files = email_agent.get_available_files(user_id=current_user.id)
        return jsonify(files)
    except Exception as e:
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500


@app.route("/email-agent/upload", methods=["POST"])
@login_required
def email_agent_upload():
    if "file" not in request.files:
        return jsonify({"success": False, "error": "No file uploaded."}), 400
    file = request.files["file"]
    if file.filename == "":
        return jsonify({"success": False, "error": "No file selected."}), 400
    if not file.filename.endswith(".xlsx"):
        return jsonify({"success": False, "error": "Only .xlsx Excel files are allowed."}), 400
        
    try:
        # Validate that the file has an 'Email' column
        import pandas as pd
        df = pd.read_excel(file)
        if "Email" not in df.columns:
            return jsonify({"success": False, "error": "Excel file is missing the required 'Email' column."}), 400
            
        from werkzeug.utils import secure_filename
        filename = secure_filename(file.filename)
        
        # Segment filename per user
        filename = f"user_{current_user.id}_{filename}"
        
        # Avoid overwriting existing files
        base, ext = os.path.splitext(filename)
        counter = 1
        final_filename = filename
        while os.path.exists(os.path.join(agent_logic.OUTPUT_DIR, final_filename)):
            final_filename = f"{base}_{counter}{ext}"
            counter += 1
            
        # Reset file stream position
        file.seek(0)
        file.save(os.path.join(agent_logic.OUTPUT_DIR, final_filename))
        
        # Extract emails count to return
        leads = email_agent.extract_leads_from_excel(final_filename)
        return jsonify({"success": True, "filename": final_filename, "valid_email_count": len(leads)})
    except Exception as e:
        traceback.print_exc()
        return jsonify({"success": False, "error": f"Failed to process Excel file: {str(e)}"}), 500


@app.route("/email-agent/generate-drafts", methods=["POST"])
@login_required
def email_agent_generate_drafts():
    data = request.get_json() or {}
    file_name = data.get("file_name", "").strip()
    
    if not file_name:
        return jsonify({"success": False, "error": "Excel file select karna zaroori hai."}), 400
        
    try:
        # Security validation: make sure file belongs to the user
        if file_name != "manual" and not file_name.startswith(f"user_{current_user.id}_"):
            return jsonify({"success": False, "error": "Unauthorized file access."}), 403

        leads = email_agent.extract_leads_from_excel(file_name)
        if not leads:
            return jsonify({"success": False, "error": "Selected file has no valid leads."}), 400
            
        # Generate custom drafts in parallel
        drafts = ai_helper.generate_drafts_for_leads_async(leads)
        return jsonify({"success": True, "drafts": drafts})
    except Exception as e:
        traceback.print_exc()
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/email-agent/send", methods=["POST"])
@login_required
def email_agent_send():
    data = request.get_json() or {}
    file_name = data.get("file_name", "").strip()
    subject = data.get("subject", "").strip()
    message = data.get("message", "").strip()
    sender_name = data.get("sender_name", "").strip()
    manual_emails = data.get("manual_emails", [])
    drafts = data.get("drafts", [])

    if not file_name:
        return jsonify({"success": False, "error": "File selection or sending mode is required."}), 400

    if file_name != "ai_drafts" and not subject:
        return jsonify({"success": False, "error": "Subject line cannot be empty."}), 400

    if file_name != "ai_drafts" and not message:
        return jsonify({"success": False, "error": "Message body cannot be empty."}), 400

    # Security check: if loading from file, verify owner
    if file_name not in ["manual", "ai_drafts"] and not file_name.startswith(f"user_{current_user.id}_"):
        return jsonify({"success": False, "error": "Unauthorized file access."}), 403

    try:
        default_gmail = GmailAccount.query.filter_by(user_id=current_user.id, is_default=True).first()
        if not default_gmail:
            return jsonify({"success": False, "error": "No default Gmail account configured. Connect one in Settings."}), 400

        sender_email = default_gmail.email
        sender_password = decrypt_value(default_gmail.encrypted_app_password)

        leads = []
        if file_name == "manual":
            for email in manual_emails:
                email_str = email.strip()
                if email_agent.is_valid_email(email_str):
                    leads.append({
                        "email": email_str,
                        "business_name": "N/A",
                        "website": "N/A",
                        "reviewer_name": "N/A",
                        "review_stars": "N/A",
                        "review_text": "",
                        "review_date": "N/A",
                        "review_link": "N/A",
                        "business_maps_link": "N/A"
                    })
            display_file_name = "Manual Entry"
        elif file_name == "ai_drafts":
            for d in drafts:
                leads.append({
                    "email": d.get("email", "").strip(),
                    "business_name": d.get("business_name", "N/A"),
                    "subject": d.get("subject", "").strip(),
                    "body": d.get("body", "").strip(),
                    "website": "N/A",
                    "reviewer_name": "N/A",
                    "review_stars": "N/A",
                    "review_text": "",
                    "review_date": "N/A",
                    "review_link": "N/A",
                    "business_maps_link": "N/A"
                })
            display_file_name = "AI Pre-generated Drafts"
            subject = "AI Campaign"
            message = "AI Campaign"
        else:
            leads = email_agent.extract_leads_from_excel(file_name)
            display_file_name = file_name

        if not leads:
            return jsonify({"success": False, "error": "No valid recipients found to send emails to."}), 400

        campaign_id = email_agent.start_campaign_send(
            leads, subject, message, sender_name, display_file_name,
            sender_email=sender_email, sender_password=sender_password,
            user_id=current_user.id
        )

        return jsonify({
            "success": True,
            "campaign_id": campaign_id,
            "total": len(leads)
        })

    except Exception as e:
        traceback.print_exc()
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/email-agent/status/<campaign_id>")
@login_required
def email_agent_campaign_status(campaign_id):
    try:
        status = email_agent.get_campaign_status(campaign_id)
        if not status:
            return jsonify({"error": "Campaign not found."}), 404
        # Security check: verify owner
        if status.get("user_id") != current_user.id:
            return jsonify({"error": "Unauthorized campaign status access."}), 403
        return jsonify(status)
    except Exception as e:
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500


@app.route("/email-agent/history")
@login_required
def email_agent_history():
    try:
        history = email_agent.get_campaign_history(user_id=current_user.id)
        return jsonify(history)
    except Exception as e:
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500


# ---------- WhatsApp Agent Routes ----------

@app.route("/whatsapp-agent")
@login_required
def whatsapp_agent_home():
    return render_template("whatsapp_agent.html")


@app.route("/whatsapp-agent/files")
@login_required
def whatsapp_agent_files():
    try:
        files = whatsapp_agent.get_available_files(user_id=current_user.id)
        return jsonify(files)
    except Exception as e:
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500


@app.route("/whatsapp-agent/send", methods=["POST"])
@login_required
def whatsapp_agent_send():
    data = request.get_json() or {}
    file_name = data.get("file_name", "").strip()
    message_template = data.get("message_template", "").strip()
    min_delay = int(data.get("min_delay", 20))
    max_delay = int(data.get("max_delay", 40))
    daily_limit_enabled = bool(data.get("daily_limit_enabled", False))
    daily_limit = int(data.get("daily_limit", 150))
    drafts = data.get("drafts", None)

    if not file_name:
        return jsonify({"success": False, "error": "Output report file select karna zaroori hai."}), 400

    if not message_template and not drafts:
        return jsonify({"success": False, "error": "Message template cannot be empty."}), 400

    # Security check: verify file owner
    if not file_name.startswith(f"user_{current_user.id}_"):
        return jsonify({"success": False, "error": "Unauthorized file access."}), 403

    try:
        campaign_id = whatsapp_agent.start_campaign_send(
            file_name=file_name,
            message_template=message_template,
            min_delay=min_delay,
            max_delay=max_delay,
            daily_limit_enabled=daily_limit_enabled,
            daily_limit=daily_limit,
            drafts=drafts,
            user_id=current_user.id
        )
        return jsonify({"success": True, "campaign_id": campaign_id})
    except Exception as e:
        traceback.print_exc()
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/whatsapp-agent/status/<campaign_id>")
@login_required
def whatsapp_agent_status(campaign_id):
    try:
        status = whatsapp_agent.get_campaign_status(campaign_id)
        if not status:
            return jsonify({"error": "Campaign not found."}), 404
        # Security: check campaign owner
        if status.get("user_id") != current_user.id:
            return jsonify({"error": "Unauthorized campaign status access."}), 403
        return jsonify(status)
    except Exception as e:
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500


@app.route("/whatsapp-agent/resume/<campaign_id>", methods=["POST"])
@login_required
def whatsapp_agent_resume(campaign_id):
    try:
        # Security check: verify campaign owner from active campaigns
        status = whatsapp_agent.get_campaign_status(campaign_id)
        if not status:
            return jsonify({"error": "Campaign not found."}), 404
        if status.get("user_id") != current_user.id:
            return jsonify({"error": "Unauthorized campaign access."}), 403

        data = request.get_json() or {}
        resumed_id = whatsapp_agent.resume_campaign(campaign_id, data)
        return jsonify({"success": True, "campaign_id": resumed_id})
    except Exception as e:
        traceback.print_exc()
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/whatsapp-agent/preview-leads", methods=["POST"])
@login_required
def whatsapp_agent_preview_leads():
    try:
        data = request.get_json() or {}
        file_name = data.get("file_name", "").strip()
        message_template = data.get("message_template", "").strip()

        if not file_name:
            return jsonify({"success": False, "error": "File name is required."}), 400

        # Security: check file owner
        if not file_name.startswith(f"user_{current_user.id}_"):
            return jsonify({"success": False, "error": "Unauthorized file access."}), 403

        leads = whatsapp_agent.generate_preview_leads(file_name, message_template)
        return jsonify({"success": True, "leads": leads})
    except Exception as e:
        traceback.print_exc()
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/whatsapp-agent/history")
@login_required
def whatsapp_agent_history():
    try:
        history = whatsapp_agent.get_campaign_history(user_id=current_user.id)
        return jsonify(history)
    except Exception as e:
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500


# ---------- Combined Outreach Report Route ----------

@app.route("/outreach-report/download")
@login_required
def download_combined_outreach_report():
    try:
        import outreach_report
        filename = outreach_report.export_combined_report_to_excel(user_id=current_user.id)
        return send_from_directory(agent_logic.OUTPUT_DIR, filename, as_attachment=True)
    except Exception as e:
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500


# ============================================================
# Reply Assistant Routes
# ============================================================

@app.route("/email-agent/replies")
@login_required
def email_agent_replies():
    try:
        replies = reply_agent.get_replies(user_id=current_user.id)
        return jsonify(replies)
    except Exception as e:
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500


@app.route("/email-agent/replies/check", methods=["POST"])
@login_required
def email_agent_check_replies():
    try:
        default_gmail = GmailAccount.query.filter_by(user_id=current_user.id, is_default=True).first()
        if not default_gmail:
            return jsonify({"success": False, "error": "No default Gmail account configured. Connect one in Settings."}), 400

        sender_email = default_gmail.email
        sender_password = decrypt_value(default_gmail.encrypted_app_password)

        result = reply_agent.check_for_replies(
            email_address=sender_email,
            password=sender_password,
            user_id=current_user.id
        )

        if not result.get("success"):
            return jsonify(result), 400

        # Automatically generate Gemini drafts for newly detected replies.
        analyzed = []
        for reply in result.get("replies", []):
            try:
                updated = reply_agent.analyze_reply_with_gemini(reply)
                if updated:
                    analyzed.append(updated)
            except Exception as ai_error:
                reply_agent.update_reply(
                    reply["id"],
                    {
                        "status": "New",
                        "ai_error": str(ai_error)
                    }
                )
                analyzed.append(reply)

        return jsonify({
            "success": True,
            "new_replies": len(analyzed),
            "replies": analyzed
        })

    except Exception as e:
        traceback.print_exc()
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/email-agent/replies/<reply_id>")
@login_required
def email_agent_reply_detail(reply_id):
    try:
        reply = reply_agent.find_reply(reply_id)
        if not reply:
            return jsonify({"success": False, "error": "Reply not found."}), 404
        # Security: check owner
        if reply.get("user_id") != current_user.id:
            return jsonify({"success": False, "error": "Unauthorized reply access."}), 403
        return jsonify({"success": True, "reply": reply})
    except Exception as e:
        traceback.print_exc()
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/email-agent/replies/<reply_id>/analyze", methods=["POST"])
@login_required
def email_agent_analyze_reply(reply_id):
    try:
        reply = reply_agent.find_reply(reply_id)
        if not reply:
            return jsonify({"success": False, "error": "Reply not found."}), 404
        # Security: check owner
        if reply.get("user_id") != current_user.id:
            return jsonify({"success": False, "error": "Unauthorized reply access."}), 403

        updated = reply_agent.analyze_reply_with_gemini(reply)
        return jsonify({"success": True, "reply": updated})
    except Exception as e:
        traceback.print_exc()
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/email-agent/replies/<reply_id>/send", methods=["POST"])
@login_required
def email_agent_send_reply(reply_id):
    try:
        reply = reply_agent.find_reply(reply_id)
        if not reply:
            return jsonify({"success": False, "error": "Reply not found."}), 404
        # Security: check owner
        if reply.get("user_id") != current_user.id:
            return jsonify({"success": False, "error": "Unauthorized reply access."}), 403

        default_gmail = GmailAccount.query.filter_by(user_id=current_user.id, is_default=True).first()
        if not default_gmail:
            return jsonify({"success": False, "error": "No default Gmail account configured. Connect one in Settings."}), 400

        sender_email = default_gmail.email
        sender_password = decrypt_value(default_gmail.encrypted_app_password)

        data = request.get_json() or {}
        response_text = data.get("response", "").strip()

        result = reply_agent.send_reply(
            reply_id,
            response_text,
            sender_email=sender_email,
            sender_password=sender_password
        )

        if not result.get("success"):
            return jsonify(result), 400

        return jsonify(result)

    except Exception as e:
        traceback.print_exc()
        return jsonify({"success": False, "error": str(e)}), 500


if __name__ == "__main__":
    app.run(debug=True, port=5000)
