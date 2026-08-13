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


def generate_email_pitch(business_name, stars, review_text, reviewer_name, website, email=None, prompt_instructions=None):
    """
    Queries Gemini API to write a personalized outreach email based on a negative Google Maps review,
    or a professional ORM pitch if review details are not available.
    """
    if not GEMINI_API_KEY:
        return {
            "inferred_business_name": "N/A",
            "subject": f"Feedback regarding your Google reviews - {business_name}" if business_name != "N/A" else "Question regarding your business online presence",
            "body": f"Hi Team at {business_name},\n\nWe noticed some negative reviews on your Google listing and wanted to offer our assistance."
        }

    # Clean review text for prompt safety and readability
    clean_review = review_text.strip() if review_text else ""
    if not clean_review or clean_review == "(Fetched reviews mein negative review nahi mila)":
        clean_review = "(No specific review comment left, just low rating)"

    # Determine if it's review-based or email-only
    has_review = (stars and stars != "N/A")

    if has_review:
        prompt = f"""
    You are a professional Online Reputation Management (ORM) specialist.
    Write a highly personalized cold outreach email to a business owner based on a negative review they received.
    
    Business Name: {business_name}
    Negative Review Rating: {stars} stars
    Reviewer Name: {reviewer_name}
    Review Comments: "{clean_review}"
    Business Website: {website}
    Recipient Email: {email or 'N/A'}
    
    The email must:
    1. Be friendly, empathetic, and professional.
    2. Reference their business name and the specific negative review details (the reviewer's comment/rating) as a hook.
    3. Clearly explain how negative reviews impact their local search ranking and customer conversion rate (trust score).
    4. Offer a helpful solution, such as replying to reviews professionally, resolving issues to request rating updates, or setting up a review generation funnel to bury negative reviews.
    5. End with a soft call-to-action (CTA) inviting them to reply or schedule a brief chat.
    6. Ensure the tone is consultative and helpful, NOT pushy, salesy, or spammy. Do NOT sound like an automated template.
    7. Sign off as 'Reputation Specialist' from 'US agents'. Do NOT use any placeholder, bracketed text, or empty values like '[Your Name]', '[Your Agency]', or '[Company Name]'.
    """
    else:
        prompt = f"""
    You are a professional Online Reputation Management (ORM) specialist.
    Write a highly personalized cold outreach email to a business owner.
    
    Recipient Email: {email or 'N/A'}
    Business Name: {business_name}
    Business Website: {website}
    
    The email must:
    1. Be friendly, empathetic, and professional.
    2. Analyze the recipient's email address and domain (if not a generic email like gmail.com/yahoo.com) to infer/identify the business name (e.g. info@london-dentistry.co.uk -> 'London Dentistry'). If you can identify it, address them with their business name. If it's a generic email or you can't infer it, address them professionally as 'Business Owner'.
    3. Offer helpful reputation management and online growth services (such as getting more Google reviews, ranking higher on local search, and managing customer trust).
    4. End with a soft call-to-action (CTA) inviting them to reply or schedule a brief chat.
    5. Ensure the tone is consultative and helpful, NOT pushy, salesy, or spammy. Do NOT sound like an automated template.
    6. Sign off as 'Reputation Specialist' from 'US agents'. Do NOT use any placeholder, bracketed text, or empty values like '[Your Name]', '[Your Agency]', or '[Company Name]'.
    """

    if prompt_instructions:
        prompt += f"""
    
    CRITICAL: In addition, you must strictly follow these instructions when writing the email:
    {prompt_instructions}
    """

    prompt += f"""
    
    Return the response ONLY as a JSON object matching this schema:
    {{
        "inferred_business_name": "The business name you inferred from the email/domain or the provided business name (return 'N/A' if unable to infer)",
        "subject": "A compelling, personalized email subject line",
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
            "inferred_business_name": data.get("inferred_business_name", "N/A").strip(),
            "subject": data.get("subject", "").strip(),
            "body": data.get("body", "").strip()
        }
    except Exception as e:
        print(f"Gemini API Error for {business_name}: {e}")
        # Fallback draft
        if has_review:
            return {
                "inferred_business_name": business_name,
                "subject": f"Quick question regarding reviews for {business_name}",
                "body": f"Hi Team at {business_name},\n\nWe noticed a recent negative review left by {reviewer_name} rating you {stars} stars. Negative feedback can affect your business online. We help local businesses manage their Google reviews and reputation. Let us know if you'd like to discuss this.\n\nBest regards,\nReputation Specialist\nUS agents"
            }
        else:
            return {
                "inferred_business_name": "N/A",
                "subject": f"Improving online reputation for your business",
                "body": f"Hi Team,\n\nWe specialize in helping local businesses improve their online rating and manage Google reviews. Having a strong online reputation is key to attracting customers.\n\nLet us know if you'd like to discuss how we can help.\n\nBest regards,\nReputation Specialist\nUS agents"
            }


def generate_drafts_for_leads_async(leads, prompt_instructions=None):
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
            website=lead.get("website", "N/A"),
            email=lead.get("email"),
            prompt_instructions=prompt_instructions
        )
        # If business name is N/A but Gemini inferred it, use the inferred name
        biz_name = lead.get("business_name", "N/A")
        if biz_name == "N/A" and pitch.get("inferred_business_name") and pitch["inferred_business_name"] != "N/A":
            biz_name = pitch["inferred_business_name"]

        return {
            "email": lead.get("email"),
            "business_name": biz_name,
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

