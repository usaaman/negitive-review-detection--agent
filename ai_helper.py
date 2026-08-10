import os
import json
import re
import google.generativeai as genai
import concurrent.futures
from dotenv import load_dotenv

load_dotenv()
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

if GEMINI_API_KEY:
    genai.configure(api_key=GEMINI_API_KEY)


def generate_email_pitch(business_name, stars, review_text, reviewer_name, website):
    """
    Queries Gemini API to write a personalized outreach email based on a negative Google Maps review.
    """
    if not GEMINI_API_KEY:
        return {
            "subject": f"Feedback regarding your Google reviews - {business_name}",
            "body": f"Hi Team at {business_name},\n\nWe noticed some negative reviews on your Google listing and wanted to offer our assistance."
        }

    # Clean review text for prompt safety and readability
    clean_review = review_text.strip() if review_text else ""
    if not clean_review or clean_review == "(Fetched reviews mein negative review nahi mila)":
        clean_review = "(No specific review comment left, just low rating)"

    prompt = f"""
    You are a professional Online Reputation Management (ORM) specialist.
    Write a highly personalized cold outreach email to a business owner based on a negative review they received.
    
    Business Name: {business_name}
    Negative Review Rating: {stars} stars
    Reviewer Name: {reviewer_name}
    Review Comments: "{clean_review}"
    Business Website: {website}
    
    The email must:
    1. Be friendly, empathetic, and professional.
    2. Reference their business name and the specific negative review details (the reviewer's comment/rating) as a hook.
    3. Clearly explain how negative reviews impact their local search ranking and customer conversion rate (trust score).
    4. Offer a helpful solution, such as replying to reviews professionally, resolving issues to request rating updates, or setting up a review generation funnel to bury negative reviews.
    5. End with a soft call-to-action (CTA) inviting them to reply or schedule a brief chat.
    6. Ensure the tone is consultative and helpful, NOT pushy, salesy, or spammy. Do NOT sound like an automated template.
    7. Use placeholder sign-off (e.g., "[Your Name]", "[Your Agency]") so it can be signed off.
    
    Return the response ONLY as a JSON object matching this schema:
    {{
        "subject": "A compelling, personalized email subject line referencing their business or the review",
        "body": "The complete personalized email body formatted with clean spacing and newlines."
    }}
    """

    try:
        model = genai.GenerativeModel("gemini-flash-latest")
        response = model.generate_content(
            prompt,
            generation_config={"response_mime_type": "application/json"}
        )
        data = json.loads(response.text)
        return {
            "subject": data.get("subject", "").strip(),
            "body": data.get("body", "").strip()
        }
    except Exception as e:
        print(f"Gemini API Error for {business_name}: {e}")
        # Fallback draft
        return {
            "subject": f"Quick question regarding reviews for {business_name}",
            "body": f"Hi Team at {business_name},\n\nWe noticed a recent negative review left by {reviewer_name} rating you {stars} stars. Negative feedback can affect your business online. We help local businesses manage their Google reviews and reputation. Let us know if you'd like to discuss this.\n\nBest regards,\n[Your Name]"
        }


def generate_drafts_for_leads_async(leads):
    """
    Generates AI drafts for a list of leads concurrently.
    """
    results = []

    def process_lead(lead):
        pitch = generate_email_pitch(
            business_name=lead.get("business_name", "N/A"),
            stars=lead.get("review_stars", "N/A"),
            review_text=lead.get("review_text", ""),
            reviewer_name=lead.get("reviewer_name", "N/A"),
            website=lead.get("website", "N/A")
        )
        return {
            "email": lead.get("email"),
            "business_name": lead.get("business_name", "N/A"),
            "subject": pitch["subject"],
            "body": pitch["body"]
        }

    with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
        futures = {executor.submit(process_lead, lead): lead for lead in leads}
        for future in concurrent.futures.as_completed(futures):
            try:
                data = future.result()
                results.append(data)
            except Exception as e:
                print(f"Thread execution error: {e}")

    # Sort results to match original leads order if possible
    email_to_draft = {r["email"]: r for r in results}
    sorted_results = []
    for lead in leads:
        em = lead.get("email")
        if em in email_to_draft:
            sorted_results.append(email_to_draft[em])

    return sorted_results
