"""
agent_logic.py
----------------
Negative Reviews Finder Agent — CORE LOGIC ONLY.
Koi UI/terminal code yahan nahi hai — ye functions app.py (ya kisi
bhi UI) se import ho kar use honge.
"""

import os
import re
from datetime import datetime
from urllib.parse import urlparse
from apify_client import ApifyClient
import pandas as pd
import xlsxwriter
from dotenv import load_dotenv

load_dotenv()
API_TOKEN = os.getenv("APIFY_API_TOKEN")

OUTPUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "outputs")
os.makedirs(OUTPUT_DIR, exist_ok=True)


def get_client(api_token=None):
    token = api_token or API_TOKEN
    if not token:
        raise RuntimeError(
            "APIFY_API_TOKEN nahi mila .env file mein. "
            "Check karo .env file mein ye line hai: APIFY_API_TOKEN=your_token_here"
        )
    return ApifyClient(token)


def fetch_businesses_basic(location, category, max_businesses, api_token=None):
    """
    PHASE 1: Sirf business info + rating fetch karta hai (reviews NAHI) — fast.
    Isse pehle rating filter apply karte hain, phir sirf qualifying
    businesses ke liye reviews mangwate hain (Phase 2).
    """
    client = get_client(api_token)

    run_input = {
        "searchStringsArray": [category],
        "locationQuery": location,
        "maxCrawledPlacesPerSearch": max_businesses,
        "maxReviews": 0,
        "language": "en",
    }

    run = client.actor("compass/crawler-google-places").call(run_input=run_input)
    dataset_id = run.get("defaultDatasetId") if isinstance(run, dict) else run.default_dataset_id
    items = list(client.dataset(dataset_id).iterate_items())
    return items


def fetch_reviews_for_businesses(businesses, max_reviews, api_token=None):
    """
    PHASE 2: Sirf filtered (rating < threshold) businesses ke liye reviews
    fetch karta hai — 'lowestRanking' sort use karta hai taake sabse buri
    reviews pehle milen (negative reviews milne ke chances zyada honge).
    """
    if not businesses:
        return businesses

    client = get_client(api_token)

    start_urls = [{"url": biz["url"]} for biz in businesses if biz.get("url")]
    if not start_urls:
        return businesses

    run_input = {
        "startUrls": start_urls,
        "maxReviews": max_reviews,
        "reviewsSort": "lowestRanking",
        "language": "en",
    }

    run = client.actor("compass/crawler-google-places").call(run_input=run_input)
    dataset_id = run.get("defaultDatasetId") if isinstance(run, dict) else run.default_dataset_id
    review_items = list(client.dataset(dataset_id).iterate_items())

    # placeId se match kar ke reviews wapis original business dict mein daalo
    reviews_by_place = {item.get("placeId"): item.get("reviews", []) for item in review_items if item.get("placeId")}
    reviews_by_url = {item.get("url"): item.get("reviews", []) for item in review_items if item.get("url")}

    for biz in businesses:
        pid = biz.get("placeId")
        if pid and pid in reviews_by_place:
            biz["reviews"] = reviews_by_place[pid]
        elif biz.get("url") in reviews_by_url:
            biz["reviews"] = reviews_by_url[biz["url"]]
        else:
            biz["reviews"] = []

    return businesses


def filter_by_rating(businesses, rating_threshold):
    """Sirf rating < threshold wale businesses rakhta hai."""
    return [
        biz for biz in businesses
        if biz.get("totalScore") is not None and biz.get("totalScore") < rating_threshold
    ]


def normalize_domain(url):
    """URL se clean domain nikalta hai (matching ke liye) — e.g. https://www.abc.com/ -> abc.com"""
    if not url:
        return None
    try:
        netloc = urlparse(url).netloc or urlparse("http://" + url).netloc
        return netloc.lower().replace("www.", "").rstrip("/")
    except Exception:
        return None


def fetch_emails_for_websites(website_urls, api_token=None):
    """
    Contact Details Scraper actor (vdrmota/contact-info-scraper) ko website URLs
    bhejta hai, domain -> email ka mapping return karta hai.
    """
    if not website_urls:
        return {}

    client = get_client(api_token)

    run_input = {
        "startUrls": [{"url": u} for u in website_urls],
        "maxRequestsPerStartUrl": 10,
        "maxDepth": 3,
    }

    run = client.actor("vdrmota/contact-info-scraper").call(run_input=run_input)
    dataset_id = run.get("defaultDatasetId") if isinstance(run, dict) else run.default_dataset_id
    items = list(client.dataset(dataset_id).iterate_items())

    email_map = {}
    for item in items:
        domain = item.get("domain")
        emails = item.get("emails") or []
        if domain and emails:
            # pehli valid email le lo (jo %20 wagera junk se saaf ho)
            clean_email = next((e for e in emails if "@" in e and " " not in e and "%20" not in e), None)
            if clean_email:
                email_map[domain.lower().replace("www.", "")] = clean_email

    return email_map


def attach_contact_info(businesses, api_token=None):
    """
    Har business ke liye email dhoondta hai (agar website hai), phone bhi rakhta hai.
    Jin businesses ki NA email milti hai NA phone hai, unhe list se hata deta hai.
    Returns: (kept_businesses, dropped_count)
    """
    website_urls = list({biz["website"] for biz in businesses if biz.get("website")})
    email_map = fetch_emails_for_websites(website_urls, api_token)

    kept = []
    dropped_count = 0

    for biz in businesses:
        domain = normalize_domain(biz.get("website"))
        email = email_map.get(domain) if domain else None
        phone = biz.get("phone")

        if not email and not phone:
            dropped_count += 1
            continue

        biz["_resolved_email"] = email or "N/A"
        kept.append(biz)

    return kept, dropped_count


def build_review_rows(businesses, negative_star_max):
    """Har business ki EK row banata hai — sirf pehla mila negative review."""
    results = []

    for biz in businesses:
        biz_name = biz.get("title", "N/A")
        address = biz.get("address", "N/A")
        phone = biz.get("phone") or "N/A"
        email = biz.get("_resolved_email", "N/A")
        website = biz.get("website") or "N/A"
        rating = biz.get("totalScore")
        biz_url = biz.get("url", "N/A")
        reviews = biz.get("reviews", []) or []

        # Sirf PEHLA qualifying negative review dhoondo, phir ruk jao
        matched_review = None
        for rev in reviews:
            stars = rev.get("stars")
            if stars is not None and stars <= negative_star_max:
                matched_review = rev
                break  # <-- yehi wo "ruk jao" wala hissa hai

        if matched_review:
            results.append({
                "Business Name": biz_name,
                "Address": address,
                "Phone": phone,
                "Email": email,
                "Website": website,
                "Business Rating": rating,
                "Reviewer Name": matched_review.get("name", "N/A"),
                "Review Stars": matched_review.get("stars"),
                "Review Text": matched_review.get("text", ""),
                "Review Date": matched_review.get("publishedAtDate", "N/A"),
                "Review Link": matched_review.get("reviewUrl", "N/A"),
                "Business Maps Link": biz_url,
            })
        else:
            results.append({
                "Business Name": biz_name,
                "Address": address,
                "Phone": phone,
                "Email": email,
                "Website": website,
                "Business Rating": rating,
                "Reviewer Name": "N/A",
                "Review Stars": "N/A",
                "Review Text": "(Fetched reviews mein negative review nahi mila)",
                "Review Date": "N/A",
                "Review Link": "N/A",
                "Business Maps Link": biz_url,
            })

    return results


def build_filename(location, category, user_id=None):
    """Search ke hisaab se filename banata hai, duplicate hone par _1, _2 laga deta hai."""
    safe_location = re.sub(r'[^a-zA-Z0-9]+', '_', location).strip('_')
    safe_category = re.sub(r'[^a-zA-Z0-9]+', '_', category).strip('_')
    base_name = f"{safe_category}_{safe_location}"
    if user_id:
        base_name = f"user_{user_id}_{base_name}"

    filename = f"{base_name}.xlsx"
    counter = 1
    while os.path.exists(os.path.join(OUTPUT_DIR, filename)):
        filename = f"{base_name}_{counter}.xlsx"
        counter += 1

    return filename


def export_to_excel(results, filename):
    """
    Excel file banata hai (clickable review links ke sath), outputs/ folder mein.
    Business-level columns (Name, Address, Phone, Email, Rating, Maps Link) ko
    merge kar deta hai jab ek business ke multiple review-rows hon, taake
    same data baar baar repeat na ho.
    """
    filepath = os.path.join(OUTPUT_DIR, filename)

    if not results:
        return None

    df = pd.DataFrame(results)

    workbook = xlsxwriter.Workbook(filepath)
    worksheet = workbook.add_worksheet("Negative Reviews")

    # Formats
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

    left_wrap_format = workbook.add_format({
        'align': 'left',
        'valign': 'vcenter',
        'text_wrap': True
    })

    wrap_left_format = workbook.add_format({
        'align': 'left',
        'valign': 'vcenter',
        'text_wrap': True
    })

    hyperlink_format = workbook.add_format({
        'font_color': 'blue',
        'underline': 1,
        'align': 'center',
        'valign': 'vcenter'
    })

    headers = list(df.columns)

    # Write Header Row
    worksheet.set_row(0, 26)
    for col_idx, header in enumerate(headers):
        worksheet.write(0, col_idx, header, header_format)

    # Columns to center-align
    center_cols = {"Business Rating", "Review Stars", "Review Date", "Review Link", "Business Maps Link"}
    # Hyperlink columns mapping to anchor texts
    link_cols = {"Review Link": "View Link", "Business Maps Link": "Open Map", "Website": "Visit Website"}

    max_lens = [len(str(h)) for h in headers]

    # Write Data Rows (individual cells initially)
    for r_idx, (_, row) in enumerate(df.iterrows(), start=1):
        # Calculate dynamic row height based on Review Text character length
        review_text_val = row.get("Review Text", "")
        text_length = len(str(review_text_val)) if review_text_val else 0
        chars_per_line = 60
        num_lines = max(1, (text_length // chars_per_line) + 1)
        row_height = min(num_lines * 15, 200)
        worksheet.set_row(r_idx, row_height)

        for c_idx, col_name in enumerate(headers):
            val = row[col_name]

            # Determine display_val and val_to_write
            if val is None or (isinstance(val, float) and pd.isna(val)):
                val_to_write = ""
                display_val = ""
            else:
                val_to_write = val
                display_val = str(val)

            # Determine alignment format
            if col_name in center_cols:
                cell_format = center_format
            elif col_name == "Review Text":
                cell_format = wrap_left_format
            else:
                cell_format = left_format

            # Write value
            if col_name in link_cols:
                if val_to_write and isinstance(val_to_write, str) and val_to_write.startswith("http"):
                    anchor_text = link_cols[col_name]
                    clean_url = val_to_write.replace('"', '%22')
                    formula = f'=HYPERLINK("{clean_url}", "{anchor_text}")'
                    worksheet.write_formula(r_idx, c_idx, formula, hyperlink_format, anchor_text)
                    display_val = anchor_text
                else:
                    worksheet.write(r_idx, c_idx, val_to_write, cell_format)
            else:
                worksheet.write(r_idx, c_idx, val_to_write, cell_format)

            max_lens[c_idx] = max(max_lens[c_idx], len(display_val))

    # ---- Merge business-level columns (remove redundancy) ----
    business_level_cols = ["Business Name", "Address", "Phone", "Email", "Website", "Business Rating", "Business Maps Link"]
    if "Business Name" in headers:
        name_col_idx = headers.index("Business Name")
        max_row = len(df)
        row_ptr = 1 # 1-indexed for data row (0 is header)

        while row_ptr <= max_row:
            start = row_ptr
            name_val = df.iloc[row_ptr - 1]["Business Name"]
            end = row_ptr
            while end + 1 <= max_row and df.iloc[end]["Business Name"] == name_val:
                end += 1

            if end > start:
                for col_name in business_level_cols:
                    if col_name in headers:
                        col_idx = headers.index(col_name)
                        top_val = df.iloc[start - 1][col_name]

                        # Clean value
                        if top_val is None or (isinstance(top_val, float) and pd.isna(top_val)):
                            top_val = ""

                        # Format to apply
                        if col_name == "Business Rating":
                            fmt = center_format
                        elif col_name == "Business Maps Link" or col_name == "Website":
                            fmt = hyperlink_format
                        else:
                            fmt = left_wrap_format

                        # Write as formula if Hyperlink
                        if col_name == "Business Maps Link" and top_val and isinstance(top_val, str) and top_val.startswith("http"):
                            anchor_text = "Open Map"
                            clean_url = top_val.replace('"', '%22')
                            formula = f'=HYPERLINK("{clean_url}", "{anchor_text}")'
                            worksheet.merge_range(start, col_idx, end, col_idx, formula, fmt)
                        elif col_name == "Website" and top_val and isinstance(top_val, str) and top_val.startswith("http"):
                            anchor_text = "Visit Website"
                            clean_url = top_val.replace('"', '%22')
                            formula = f'=HYPERLINK("{clean_url}", "{anchor_text}")'
                            worksheet.merge_range(start, col_idx, end, col_idx, formula, fmt)
                        else:
                            worksheet.merge_range(start, col_idx, end, col_idx, top_val, fmt)

            row_ptr = end + 1

    # Auto-Fit Column Widths (No Text Cropping), excluding Review Text which has a fixed width
    for col_idx, col_name in enumerate(headers):
        if col_name == "Review Text":
            worksheet.set_column(col_idx, col_idx, 60)
        else:
            worksheet.set_column(col_idx, col_idx, max_lens[col_idx] + 3)

    workbook.close()
    return filepath


def export_to_pdf(results, filename):
    """
    Excel jaisa hi data PDF mein — table format mein, negative reviews
    ki list. Har business ek section/row jaisa dikhega.
    """
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.units import mm

    filepath = os.path.join(OUTPUT_DIR, filename)

    if not results:
        return None

    styles = getSampleStyleSheet()
    cell_style = ParagraphStyle('cell', parent=styles['Normal'], fontSize=8, leading=10)
    header_style = ParagraphStyle('header', parent=styles['Normal'], fontSize=9, 
                                    textColor=colors.white, fontName='Helvetica-Bold')

    doc = SimpleDocTemplate(filepath, pagesize=landscape(A4),
                             leftMargin=15*mm, rightMargin=15*mm,
                             topMargin=15*mm, bottomMargin=15*mm)

    headers = list(results[0].keys())
    
    table_data = [[Paragraph(str(h), header_style) for h in headers]]
    for row in results:
        row_cells = []
        for h in headers:
            val = row.get(h, "")
            val_str = "" if val is None or (isinstance(val, float) and pd.isna(val)) else str(val)
            
            # Format URLs to short clickable links to prevent ReportLab crashes on long words
            if h == "Review Link" and val_str.startswith("http"):
                val_str = f'<a href="{val_str}" color="blue"><u>Open review</u></a>'
            elif h == "Business Maps Link" and val_str.startswith("http"):
                val_str = f'<a href="{val_str}" color="blue"><u>Open Map</u></a>'
            elif h == "Website" and val_str.startswith("http"):
                val_str = f'<a href="{val_str}" color="blue"><u>Visit Website</u></a>'
            elif h == "Review Text" and len(val_str) > 500:
                val_str = val_str[:500] + "..."
                
            row_cells.append(Paragraph(val_str, cell_style))
        table_data.append(row_cells)

    # Column widths layout weights
    col_weights = {
        "Business Name": 0.10,
        "Address": 0.14,
        "Phone": 0.08,
        "Email": 0.10,
        "Website": 0.08,
        "Business Rating": 0.05,
        "Reviewer Name": 0.08,
        "Review Stars": 0.05,
        "Review Text": 0.20,
        "Review Date": 0.06,
        "Review Link": 0.06,
        "Business Maps Link": 0.06
    }
    
    available_width = landscape(A4)[0] - 30*mm
    weights = [col_weights.get(h, 0.08) for h in headers]
    total_weight = sum(weights)
    col_widths = [(w / total_weight) * available_width for w in weights]

    table = Table(table_data, colWidths=col_widths, repeatRows=1)
    table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#1D232C')),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#F5F5F5')]),
    ]))

    doc.build([table])
    return filepath


active_scans = {}


def run_agent_worker(scan_id, location, category, max_businesses, max_reviews, rating_threshold, negative_star_max, api_token=None, user_id=None):
    scan_entry = active_scans[scan_id]
    try:
        # Load maps and contact tokens from the database if user_id is provided
        maps_token = api_token
        contact_token = api_token
        
        if user_id:
            from app import app
            with app.app_context():
                from models import ApifyToken
                from crypto_utils import decrypt_value
                
                # Fetch Maps Token
                maps_rec = ApifyToken.query.filter_by(user_id=user_id, token_type="maps", is_default=True).first()
                if not maps_rec:
                    maps_rec = ApifyToken.query.filter_by(user_id=user_id, is_default=True).first()
                if maps_rec:
                    maps_token = decrypt_value(maps_rec.encrypted_token)
                    
                # Fetch Contact Token
                contact_rec = ApifyToken.query.filter_by(user_id=user_id, token_type="contact", is_default=True).first()
                if contact_rec:
                    contact_token = decrypt_value(contact_rec.encrypted_token)
                else:
                    contact_token = maps_token
                
        # Ensure we have fallback tokens
        if not maps_token:
            maps_token = api_token
        if not contact_token:
            contact_token = maps_token or api_token

        scan_entry["message"] = "Starting Google Places search..."
        businesses = fetch_businesses_basic(location, category, max_businesses, maps_token)
        scan_entry["total_scanned"] = len(businesses)
        
        scan_entry["message"] = f"Filtering ratings below {rating_threshold}..."
        rating_filtered = filter_by_rating(businesses, rating_threshold)
        
        if not rating_filtered:
            scan_entry["status"] = "completed"
            scan_entry["message"] = "Finished. No businesses met the rating threshold."
            return
            
        scan_entry["message"] = f"Scraping reviews for {len(rating_filtered)} flagged businesses..."
        effective_max_reviews = max(max_reviews, 30)
        with_reviews = fetch_reviews_for_businesses(rating_filtered, effective_max_reviews, maps_token)
        
        scan_entry["message"] = "Searching websites for email addresses..."
        kept_businesses, dropped_count = attach_contact_info(with_reviews, contact_token)
        scan_entry["dropped_no_contact"] = dropped_count
        
        scan_entry["message"] = "Processing negative reviews and mapping templates..."
        results = build_review_rows(kept_businesses, negative_star_max)
        scan_entry["flagged_count"] = len(set(r["Business Name"] for r in results))
        
        filename = None
        pdf_filename = None
        if results:
            scan_entry["message"] = "Generating Excel and PDF reports..."
            filename = build_filename(location, category, user_id)
            export_to_excel(results, filename)
            pdf_filename = filename.replace(".xlsx", ".pdf")
            export_to_pdf(results, pdf_filename)
            
        scan_entry["results"] = results
        scan_entry["filename"] = filename
        scan_entry["pdf_filename"] = pdf_filename
        scan_entry["status"] = "completed"
        scan_entry["message"] = "Scan completed successfully!"
    except Exception as e:
        import traceback
        traceback.print_exc()
        scan_entry["status"] = "failed"
        scan_entry["error"] = str(e)
        scan_entry["message"] = f"Scan failed: {str(e)}"


def start_scan_job(location, category, max_businesses, max_reviews, rating_threshold, negative_star_max, api_token=None, user_id=None):
    import uuid
    import threading
    scan_id = str(uuid.uuid4())
    active_scans[scan_id] = {
        "status": "running",
        "message": "Initializing scanner...",
        "total_scanned": 0,
        "flagged_count": 0,
        "dropped_no_contact": 0,
        "results": [],
        "filename": None,
        "error": None
    }
    
    thread = threading.Thread(
        target=run_agent_worker,
        args=(scan_id, location, category, max_businesses, max_reviews, rating_threshold, negative_star_max, api_token, user_id)
    )
    thread.daemon = True
    thread.start()
    return scan_id


def get_scan_status(scan_id):
    return active_scans.get(scan_id)


def run_agent(location, category, max_businesses, max_reviews, rating_threshold, negative_star_max, api_token=None, user_id=None):
    """
    Poora pipeline ek function mein — UI (app.py) sirf isko call karega.
    2-phase approach: pehle sirf ratings check karo (fast), phir sirf
    qualifying businesses ke reviews fetch karo (lowestRanking sort se).
    Returns: dict with 'results', 'filename', 'total_scanned', 'flagged_count', 'dropped_no_contact'
    """
    businesses = fetch_businesses_basic(location, category, max_businesses, api_token)
    rating_filtered = filter_by_rating(businesses, rating_threshold)

    if not rating_filtered:
        # Koi business threshold se kam rating wala mila hi nahi — turant return,
        # reviews/email fetch karne ki zaroorat nahi (time/cost bachao)
        return {
            "results": [],
            "filename": None,
            "total_scanned": len(businesses),
            "flagged_count": 0,
            "dropped_no_contact": 0,
        }

    effective_max_reviews = max(max_reviews, 30)
    with_reviews = fetch_reviews_for_businesses(rating_filtered, effective_max_reviews, api_token)
    kept_businesses, dropped_count = attach_contact_info(with_reviews, api_token)
    results = build_review_rows(kept_businesses, negative_star_max)

    filename = None
    pdf_filename = None
    if results:
        filename = build_filename(location, category, user_id)
        export_to_excel(results, filename)
        pdf_filename = filename.replace(".xlsx", ".pdf")
        export_to_pdf(results, pdf_filename)

    return {
        "results": results,
        "filename": filename,
        "pdf_filename": pdf_filename,
        "total_scanned": len(businesses),
        "flagged_count": len(set(r["Business Name"] for r in results)),
        "dropped_no_contact": dropped_count,
    }


active_business_searches = {}


def search_specific_business(business_name, location, max_reviews_limit, negative_star_max=3, api_token=None):
    """
    Ek specific business (naam + location se) dhoondta hai, uske SAARE
    negative reviews nikalta hai (max_reviews_limit tak) — har review
    apni alag row banata hai (is baar 1-review-per-business wala rule
    NAHI lagta, kyunki user ne khud specific business choose kiya hai
    aur uske saare negative reviews dekhna chahta hai).
    """
    client = get_client(api_token)

    # Business dhoondo (search se, 1 result kaafi hai)
    search_input = {
        "searchStringsArray": [business_name],
        "locationQuery": location,
        "maxCrawledPlacesPerSearch": 1,
        "maxReviews": 0,
        "language": "en",
    }
    run = client.actor("compass/crawler-google-places").call(run_input=search_input)
    dataset_id = run.get("defaultDatasetId") if isinstance(run, dict) else run.default_dataset_id
    found = list(client.dataset(dataset_id).iterate_items())

    if not found:
        return {"found": False, "business": None, "reviews": []}

    biz = found[0]

    # Ab isi business ke saare reviews mangwao (lowestRanking sort, jitni
    # limit di gayi hai)
    reviews_input = {
        "startUrls": [{"url": biz["url"]}],
        "maxReviews": max_reviews_limit,
        "reviewsSort": "lowestRanking",
        "language": "en",
    }
    run2 = client.actor("compass/crawler-google-places").call(run_input=reviews_input)
    dataset_id2 = run2.get("defaultDatasetId") if isinstance(run2, dict) else run2.default_dataset_id
    review_items = list(client.dataset(dataset_id2).iterate_items())

    all_reviews = review_items[0].get("reviews", []) if review_items else []

    # Sirf negative reviews (configurable threshold)
    negative_reviews = [r for r in all_reviews if r.get("stars") is not None and r.get("stars") <= negative_star_max]

    return {
        "found": True,
        "business": {
            "name": biz.get("title", "N/A"),
            "address": biz.get("address", "N/A"),
            "phone": biz.get("phone", "N/A"),
            "website": biz.get("website", "N/A"),
            "rating": biz.get("totalScore"),
            "maps_link": biz.get("url", "N/A"),
        },
        "reviews": [
            {
                "reviewer_name": r.get("name", "N/A"),
                "stars": r.get("stars"),
                "text": r.get("text", ""),
                "date": r.get("publishedAtDate", "N/A"),
                "review_link": r.get("reviewUrl", "N/A"),
            }
            for r in negative_reviews
        ],
    }


def export_specific_to_excel(business_info, reviews, filename):
    """
    Specific Business Search ke liye Excel Report banata hai.
    Header section mein Business name, Address, Phone, Rating, aur Links hote hain.
    Neeche negative reviews ki list table format mein aati hai.
    """
    filepath = os.path.join(OUTPUT_DIR, filename)
    workbook = xlsxwriter.Workbook(filepath)
    worksheet = workbook.add_worksheet("Business Report")

    # Formats
    title_format = workbook.add_format({
        'bold': True,
        'size': 14,
        'font_color': '#121826',
        'valign': 'vcenter'
    })
    
    label_format = workbook.add_format({
        'bold': True,
        'size': 10,
        'valign': 'vcenter'
    })
    
    value_format = workbook.add_format({
        'size': 10,
        'valign': 'vcenter'
    })
    
    header_format = workbook.add_format({
        'bold': True,
        'bg_color': '#1D232C',
        'font_color': 'white',
        'align': 'left',
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

    wrap_format = workbook.add_format({
        'align': 'left',
        'valign': 'vcenter',
        'text_wrap': True
    })

    hyperlink_format = workbook.add_format({
        'font_color': 'blue',
        'underline': 1,
        'valign': 'vcenter'
    })

    # Write Business Info Card at the top
    worksheet.write(0, 0, business_info.get("name", "N/A"), title_format)
    worksheet.set_row(0, 30)

    info_rows = [
        ("Address", business_info.get("address", "N/A")),
        ("Phone", business_info.get("phone", "N/A")),
        ("Rating", f"{business_info.get('rating', 'N/A')} ★" if business_info.get('rating') else "—"),
        ("Website", business_info.get("website", "N/A")),
        ("View on Maps", business_info.get("maps_link", "N/A")),
    ]

    for i, (label, val) in enumerate(info_rows, start=1):
        worksheet.write(i, 0, f"{label}:", label_format)
        
        # Check if hyperlink
        if label in ["Website", "View on Maps"] and val and isinstance(val, str) and val.startswith("http"):
            clean_url = val.replace('"', '%22')
            formula = f'=HYPERLINK("{clean_url}", "{val}")'
            worksheet.write_formula(i, 1, formula, hyperlink_format, val)
        else:
            worksheet.write(i, 1, val if val else "", value_format)
        worksheet.set_row(i, 18)

    # Write Table Headers (at Row 8, index 7)
    start_table_row = 7
    worksheet.write(start_table_row, 0, "Reviewer Name", header_format)
    worksheet.write(start_table_row, 1, "Stars", header_format)
    worksheet.write(start_table_row, 2, "Review Text", header_format)
    worksheet.write(start_table_row, 3, "Date", header_format)
    worksheet.write(start_table_row, 4, "Review Link", header_format)
    worksheet.set_row(start_table_row, 24)

    # Write Review Rows
    for r_idx, rev in enumerate(reviews, start=start_table_row + 1):
        reviewer = rev.get("reviewer_name", "N/A")
        stars = rev.get("stars", "N/A")
        stars_str = f"{stars} ★" if stars != "N/A" else "—"
        text = rev.get("text", "")
        date = rev.get("date", "N/A")
        link = rev.get("review_link", "N/A")

        worksheet.write(r_idx, 0, reviewer, left_format)
        worksheet.write(r_idx, 1, stars_str, center_format)
        worksheet.write(r_idx, 2, text, wrap_format)
        worksheet.write(r_idx, 3, date, center_format)

        if link and isinstance(link, str) and link.startswith("http"):
            clean_url = link.replace('"', '%22')
            formula = f'=HYPERLINK("{clean_url}", "Open review")'
            worksheet.write_formula(r_idx, 4, formula, hyperlink_format, "Open review")
        else:
            worksheet.write(r_idx, 4, "—", center_format)

        # Calculate dynamic row height for Excel reviews
        text_length = len(str(text)) if text else 0
        chars_per_line = 60
        num_lines = max(1, (text_length // chars_per_line) + 1)
        row_height = min(num_lines * 15, 200)
        worksheet.set_row(r_idx, row_height)

    # Set column widths
    worksheet.set_column(0, 0, 25) # Label / Reviewer
    worksheet.set_column(1, 1, 15) # Stars
    worksheet.set_column(2, 2, 60) # Review Text (fixed width)
    worksheet.set_column(3, 3, 20) # Date
    worksheet.set_column(4, 4, 15) # Review Link

    workbook.close()
    return filepath


def export_specific_to_pdf(business_info, reviews, filename):
    """
    Specific Business Search ke liye PDF Report banata hai.
    Symmetric layout: Business details card top par, spacer, and negative reviews table below.
    """
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.units import mm

    filepath = os.path.join(OUTPUT_DIR, filename)

    styles = getSampleStyleSheet()
    
    # Custom styles
    title_style = ParagraphStyle('title', parent=styles['Heading1'], fontSize=16, leading=20, textColor=colors.HexColor('#121826'))
    label_style = ParagraphStyle('label', parent=styles['Normal'], fontSize=9, leading=12, fontName='Helvetica-Bold')
    value_style = ParagraphStyle('value', parent=styles['Normal'], fontSize=9, leading=12)
    link_style = ParagraphStyle('link', parent=styles['Normal'], fontSize=9, leading=12, textColor=colors.blue, underline=True)
    
    cell_style = ParagraphStyle('cell', parent=styles['Normal'], fontSize=8, leading=10)
    header_style = ParagraphStyle('header', parent=styles['Normal'], fontSize=9, 
                                    textColor=colors.white, fontName='Helvetica-Bold')

    doc = SimpleDocTemplate(filepath, pagesize=landscape(A4),
                             leftMargin=15*mm, rightMargin=15*mm,
                             topMargin=15*mm, bottomMargin=15*mm)

    story = []

    # 1. Business Info Header Title
    name = business_info.get("name", "N/A")
    story.append(Paragraph(name, title_style))
    story.append(Spacer(1, 4*mm))

    # Layout business details card in a 2x2 or 3x2 grid table
    website = business_info.get("website", "N/A")
    maps_link = business_info.get("maps_link", "N/A")
    
    website_p = Paragraph(f'<a href="{website}">Visit Website</a>', link_style) if website and isinstance(website, str) and website.startswith("http") else Paragraph("—", value_style)
    maps_p = Paragraph(f'<a href="{maps_link}">View on Maps</a>', link_style) if maps_link and isinstance(maps_link, str) and maps_link.startswith("http") else Paragraph("—", value_style)

    rating_val = business_info.get('rating', 'N/A')
    rating_str = f"{rating_val} ★" if rating_val and rating_val != "N/A" else "—"

    info_data = [
        [Paragraph("Address:", label_style), Paragraph(business_info.get("address", "N/A"), value_style), Paragraph("Links:", label_style), website_p],
        [Paragraph("Phone:", label_style), Paragraph(business_info.get("phone", "N/A"), value_style), Paragraph("", label_style), maps_p],
        [Paragraph("Rating:", label_style), Paragraph(rating_str, value_style), Paragraph("", label_style), Paragraph("", value_style)]
    ]
    
    info_table = Table(info_data, colWidths=[20*mm, 120*mm, 15*mm, 60*mm])
    info_table.setStyle(TableStyle([
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 1*mm),
        ('TOPPADDING', (0, 0), (-1, -1), 1*mm),
    ]))
    
    story.append(info_table)
    story.append(Spacer(1, 8*mm))

    # 2. Reviews Section Table Header
    story.append(Paragraph("Negative Reviews (Stars &le; 3)", ParagraphStyle('section_h', parent=styles['Heading2'], fontSize=12, leading=14, textColor=colors.HexColor('#EF4444'))))
    story.append(Spacer(1, 4*mm))

    # Headers for reviews table
    headers = ["Reviewer Name", "Stars", "Review Text", "Date", "Review Link"]
    table_data = [[Paragraph(h, header_style) for h in headers]]
    
    for r in reviews:
        stars_val = r.get("stars", "N/A")
        stars_str = f"{stars_val} ★" if stars_val != "N/A" and stars_val is not None else "—"
        
        link_val = r.get("review_link", "N/A")
        link_p = Paragraph(f'<a href="{link_val}">Open review</a>', link_style) if link_val and isinstance(link_val, str) and link_val.startswith("http") else Paragraph("—", value_style)
        
        text_val = r.get("text", "")
        if len(text_val) > 500:
            text_val = text_val[:500] + "..."

        table_data.append([
            Paragraph(r.get("reviewer_name", "N/A"), cell_style),
            Paragraph(stars_str, cell_style),
            Paragraph(text_val, cell_style),
            Paragraph(r.get("date", "N/A"), cell_style),
            link_p
        ])

    available_width = landscape(A4)[0] - 30*mm
    col_widths = [available_width * 0.15, available_width * 0.08, available_width * 0.52, available_width * 0.15, available_width * 0.10]
    
    table = Table(table_data, colWidths=col_widths, repeatRows=1)
    table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#1D232C')),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#F5F5F5')]),
    ]))

    story.append(table)
    doc.build(story)
    return filepath


def _run_business_search_worker(job_id, business_name, location, max_reviews_limit, negative_star_max, api_token, user_id=None):
    job_entry = active_business_searches[job_id]
    try:
        maps_token = api_token
        if user_id:
            from app import app
            with app.app_context():
                from models import ApifyToken
                from crypto_utils import decrypt_value
                maps_rec = ApifyToken.query.filter_by(user_id=user_id, token_type="maps", is_default=True).first()
                if not maps_rec:
                    maps_rec = ApifyToken.query.filter_by(user_id=user_id, is_default=True).first()
                if maps_rec:
                    maps_token = decrypt_value(maps_rec.encrypted_token)
                
        if not maps_token:
            maps_token = api_token
            
        result = search_specific_business(business_name, location, max_reviews_limit, negative_star_max, maps_token)
        
        filename = None
        pdf_filename = None
        
        if result["found"]:
            # Construct a safe filename based on business name and location
            safe_biz_name = re.sub(r'[^a-zA-Z0-9]+', '_', result["business"]["name"]).strip('_')
            safe_loc = re.sub(r'[^a-zA-Z0-9]+', '_', location).strip('_')
            base_name = f"specific_{safe_biz_name}_{safe_loc}"
            if user_id:
                base_name = f"user_{user_id}_{base_name}"
            
            filename = f"{base_name}.xlsx"
            counter = 1
            while os.path.exists(os.path.join(OUTPUT_DIR, filename)):
                filename = f"{base_name}_{counter}.xlsx"
                counter += 1
                
            export_specific_to_excel(result["business"], result["reviews"], filename)
            
            pdf_filename = filename.replace(".xlsx", ".pdf")
            export_specific_to_pdf(result["business"], result["reviews"], pdf_filename)
            
        job_entry["result"] = result
        job_entry["filename"] = filename
        job_entry["pdf_filename"] = pdf_filename
        job_entry["status"] = "completed"
        job_entry["message"] = "Search completed successfully!"
    except Exception as e:
        import traceback
        traceback.print_exc()
        job_entry["status"] = "failed"
        job_entry["message"] = str(e)


def start_business_search_job(business_name, location, max_reviews_limit, negative_star_max=3, api_token=None, user_id=None):
    import uuid
    import threading
    job_id = str(uuid.uuid4())
    active_business_searches[job_id] = {
        "job_id": job_id,
        "status": "running",
        "message": f"Searching for '{business_name}'...",
        "negative_star_max": negative_star_max,
        "result": None,
        "filename": None,
        "pdf_filename": None
    }
    thread = threading.Thread(
        target=_run_business_search_worker,
        args=(job_id, business_name, location, max_reviews_limit, negative_star_max, api_token, user_id)
    )
    thread.daemon = True
    thread.start()
    return job_id


def get_business_search_status(job_id):
    return active_business_searches.get(job_id)
