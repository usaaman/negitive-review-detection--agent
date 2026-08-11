"""
app.py
-------
Flask backend — UI serve karta hai aur agent_logic.py ke functions
ko call karta hai jab user "Run Scan" dabaye.
"""

from flask import Flask, render_template, request, jsonify, send_from_directory
import agent_logic
import email_agent
import whatsapp_agent
import reply_agent
import ai_helper
import traceback


app = Flask(__name__)


@app.route("/")
def home():
    return render_template("index.html")


@app.route("/scan", methods=["POST"])
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
        scan_id = agent_logic.start_scan_job(
            location, category, max_businesses, max_reviews,
            rating_threshold, negative_star_max
        )
        return jsonify({
            "success": True,
            "scan_id": scan_id
        })
    except Exception as e:
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500


@app.route("/scan/status/<scan_id>")
def scan_status(scan_id):
    try:
        status = agent_logic.get_scan_status(scan_id)
        if not status:
            return jsonify({"error": "Scan not found."}), 404
        return jsonify(status)
    except Exception as e:
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500



@app.route("/download/<filename>")
def download(filename):
    return send_from_directory(agent_logic.OUTPUT_DIR, filename, as_attachment=True)


# ---------- Email Agent Routes ----------

@app.route("/email-agent")
def email_agent_home():
    return render_template("email_agent.html")


@app.route("/email-agent/files")
def email_agent_files():
    try:
        files = email_agent.get_available_files()
        return jsonify(files)
    except Exception as e:
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500


@app.route("/email-agent/upload", methods=["POST"])
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
        
        # Avoid overwriting existing files
        import os
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
def email_agent_generate_drafts():
    data = request.get_json() or {}
    file_name = data.get("file_name", "").strip()
    
    if not file_name:
        return jsonify({"success": False, "error": "Excel file select karna zaroori hai."}), 400
        
    try:
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

    try:
        leads = []
        if file_name == "manual":
            # Process manual emails
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
            # Process pre-generated AI drafts
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
            # Load leads from file
            leads = email_agent.extract_leads_from_excel(file_name)
            display_file_name = file_name

        if not leads:
            return jsonify({"success": False, "error": "No valid recipients found to send emails to."}), 400

        # Start asynchronous campaign send
        campaign_id = email_agent.start_campaign_send(
            leads, subject, message, sender_name, display_file_name
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
def email_agent_campaign_status(campaign_id):
    try:
        status = email_agent.get_campaign_status(campaign_id)
        if not status:
            return jsonify({"error": "Campaign not found."}), 404
        return jsonify(status)
    except Exception as e:
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500


@app.route("/email-agent/history")
def email_agent_history():
    try:
        history = email_agent.get_campaign_history()
        return jsonify(history)
    except Exception as e:
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500


# ---------- WhatsApp Agent Routes ----------

@app.route("/whatsapp-agent")
def whatsapp_agent_home():
    return render_template("whatsapp_agent.html")


@app.route("/whatsapp-agent/files")
def whatsapp_agent_files():
    try:
        files = whatsapp_agent.get_available_files()
        return jsonify(files)
    except Exception as e:
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500


@app.route("/whatsapp-agent/send", methods=["POST"])
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

    try:
        campaign_id = whatsapp_agent.start_campaign_send(
            file_name=file_name,
            message_template=message_template,
            min_delay=min_delay,
            max_delay=max_delay,
            daily_limit_enabled=daily_limit_enabled,
            daily_limit=daily_limit,
            drafts=drafts
        )
        return jsonify({"success": True, "campaign_id": campaign_id})
    except Exception as e:
        traceback.print_exc()
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/whatsapp-agent/status/<campaign_id>")
def whatsapp_agent_status(campaign_id):
    try:
        status = whatsapp_agent.get_campaign_status(campaign_id)
        if not status:
            return jsonify({"error": "Campaign not found."}), 404
        return jsonify(status)
    except Exception as e:
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500


@app.route("/whatsapp-agent/resume/<campaign_id>", methods=["POST"])
def whatsapp_agent_resume(campaign_id):
    try:
        data = request.get_json() or {}
        resumed_id = whatsapp_agent.resume_campaign(campaign_id, data)
        return jsonify({"success": True, "campaign_id": resumed_id})
    except Exception as e:
        traceback.print_exc()
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/whatsapp-agent/preview-leads", methods=["POST"])
def whatsapp_agent_preview_leads():
    try:
        data = request.get_json() or {}
        file_name = data.get("file_name", "").strip()
        message_template = data.get("message_template", "").strip()

        if not file_name:
            return jsonify({"success": False, "error": "File name is required."}), 400

        leads = whatsapp_agent.generate_preview_leads(file_name, message_template)
        return jsonify({"success": True, "leads": leads})
    except Exception as e:
        traceback.print_exc()
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/whatsapp-agent/history")
def whatsapp_agent_history():
    try:
        history = whatsapp_agent.get_campaign_history()
        return jsonify(history)
    except Exception as e:
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500


# ---------- Combined Outreach Report Route ----------

@app.route("/outreach-report/download")
def download_combined_outreach_report():
    try:
        import outreach_report
        filename = outreach_report.export_combined_report_to_excel()
        return send_from_directory(agent_logic.OUTPUT_DIR, filename, as_attachment=True)
    except Exception as e:
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500


# ============================================================
# Reply Assistant Routes
# ============================================================

@app.route("/email-agent/replies")
def email_agent_replies():
    try:
        replies = reply_agent.get_replies()
        return jsonify(replies)

    except Exception as e:
        traceback.print_exc()
        return jsonify({
            "error": str(e)
        }), 500


@app.route("/email-agent/replies/check", methods=["POST"])
def email_agent_check_replies():
    try:
        result = reply_agent.check_for_replies()

        if not result.get("success"):
            return jsonify(result), 400

        # Automatically generate Gemini drafts for newly
        # detected replies.
        analyzed = []

        for reply in result.get("replies", []):

            try:
                updated = reply_agent.analyze_reply_with_gemini(
                    reply
                )

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

        return jsonify({
            "success": False,
            "error": str(e)
        }), 500


@app.route("/email-agent/replies/<reply_id>")
def email_agent_reply_detail(reply_id):
    try:
        reply = reply_agent.find_reply(reply_id)

        if not reply:
            return jsonify({
                "success": False,
                "error": "Reply not found."
            }), 404

        return jsonify({
            "success": True,
            "reply": reply
        })

    except Exception as e:
        traceback.print_exc()

        return jsonify({
            "success": False,
            "error": str(e)
        }), 500


@app.route("/email-agent/replies/<reply_id>/analyze", methods=["POST"])
def email_agent_analyze_reply(reply_id):
    try:
        reply = reply_agent.find_reply(reply_id)

        if not reply:
            return jsonify({
                "success": False,
                "error": "Reply not found."
            }), 404

        updated = reply_agent.analyze_reply_with_gemini(
            reply
        )

        return jsonify({
            "success": True,
            "reply": updated
        })

    except Exception as e:
        traceback.print_exc()

        return jsonify({
            "success": False,
            "error": str(e)
        }), 500


@app.route("/email-agent/replies/<reply_id>/send", methods=["POST"])
def email_agent_send_reply(reply_id):
    try:
        data = request.get_json() or {}

        response_text = (
            data.get("response", "")
            .strip()
        )

        result = reply_agent.send_reply(
            reply_id,
            response_text
        )

        if not result.get("success"):
            return jsonify(result), 400

        return jsonify(result)

    except Exception as e:
        traceback.print_exc()

        return jsonify({
            "success": False,
            "error": str(e)
        }), 500


if __name__ == "__main__":

    app.run(debug=True, port=5000)
