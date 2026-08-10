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


def get_client():
    if not API_TOKEN:
        raise RuntimeError(
            "APIFY_API_TOKEN nahi mila .env file mein. "
            "Check karo .env file mein ye line hai: APIFY_API_TOKEN=your_token_here"
        )
    return ApifyClient(API_TOKEN)


def fetch_businesses_basic(location, category, max_businesses):
    """
    PHASE 1: Sirf business info + rating fetch karta hai (reviews NAHI) — fast.
    Isse pehle rating filter apply karte hain, phir sirf qualifying
    businesses ke liye reviews mangwate hain (Phase 2).
    """
    client = get_client()

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


def fetch_reviews_for_businesses(businesses, max_reviews):
    """
    PHASE 2: Sirf filtered (rating < threshold) businesses ke liye reviews
    fetch karta hai — 'lowestRanking' sort use karta hai taake sabse buri
    reviews pehle milen (negative reviews milne ke chances zyada honge).
    """
    if not businesses:
        return businesses

    client = get_client()

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


def fetch_emails_for_websites(website_urls):
    """
    Contact Details Scraper actor (vdrmota/contact-info-scraper) ko website URLs
    bhejta hai, domain -> email ka mapping return karta hai.
    """
    if not website_urls:
        return {}

    client = get_client()

    run_input = {
        "startUrls": [{"url": u} for u in website_urls],
        "maxRequestsPerStartUrl": 5,
        "maxDepth": 2,
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


def attach_contact_info(businesses):
    """
    Har business ke liye email dhoondta hai (agar website hai), phone bhi rakhta hai.
    Jin businesses ki NA email milti hai NA phone hai, unhe list se hata deta hai.
    Returns: (kept_businesses, dropped_count)
    """
    website_urls = list({biz["website"] for biz in businesses if biz.get("website")})
    email_map = fetch_emails_for_websites(website_urls)

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
    """Filtered businesses se negative-review rows banata hai (Email column ke sath)."""
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

        found_negative = False

        for rev in reviews:
            stars = rev.get("stars")
            if stars is None or stars > negative_star_max:
                continue

            found_negative = True
            results.append({
                "Business Name": biz_name,
                "Address": address,
                "Phone": phone,
                "Email": email,
                "Website": website,
                "Business Rating": rating,
                "Reviewer Name": rev.get("name", "N/A"),
                "Review Stars": stars,
                "Review Text": rev.get("text", ""),
                "Review Date": rev.get("publishedAtDate", "N/A"),
                "Review Link": rev.get("reviewUrl", "N/A"),
                "Business Maps Link": biz_url,
            })

        if not found_negative:
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


def build_filename(location, category):
    """Search ke hisaab se filename banata hai, duplicate hone par _1, _2 laga deta hai."""
    safe_location = re.sub(r'[^a-zA-Z0-9]+', '_', location).strip('_')
    safe_category = re.sub(r'[^a-zA-Z0-9]+', '_', category).strip('_')
    base_name = f"{safe_category}_{safe_location}"

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
        # Set standard row height so only the first line of wrapped text shows initially
        worksheet.set_row(r_idx, 20)

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

    # Auto-Fit Column Widths (No Text Cropping)
    for col_idx in range(len(headers)):
        worksheet.set_column(col_idx, col_idx, max_lens[col_idx] + 3)

    workbook.close()
    return filepath


active_scans = {}


def run_agent_worker(scan_id, location, category, max_businesses, max_reviews, rating_threshold, negative_star_max):
    scan_entry = active_scans[scan_id]
    try:
        scan_entry["message"] = "Starting Google Places search..."
        businesses = fetch_businesses_basic(location, category, max_businesses)
        scan_entry["total_scanned"] = len(businesses)
        
        scan_entry["message"] = f"Filtering ratings below {rating_threshold}..."
        rating_filtered = filter_by_rating(businesses, rating_threshold)
        
        if not rating_filtered:
            scan_entry["status"] = "completed"
            scan_entry["message"] = "Finished. No businesses met the rating threshold."
            return
            
        scan_entry["message"] = f"Scraping reviews for {len(rating_filtered)} flagged businesses..."
        with_reviews = fetch_reviews_for_businesses(rating_filtered, max_reviews)
        
        scan_entry["message"] = "Searching websites for email addresses..."
        kept_businesses, dropped_count = attach_contact_info(with_reviews)
        scan_entry["dropped_no_contact"] = dropped_count
        
        scan_entry["message"] = "Processing negative reviews and mapping templates..."
        results = build_review_rows(kept_businesses, negative_star_max)
        scan_entry["flagged_count"] = len(set(r["Business Name"] for r in results))
        
        filename = None
        if results:
            scan_entry["message"] = "Generating Excel report..."
            filename = build_filename(location, category)
            export_to_excel(results, filename)
            
        scan_entry["results"] = results
        scan_entry["filename"] = filename
        scan_entry["status"] = "completed"
        scan_entry["message"] = "Scan completed successfully!"
    except Exception as e:
        import traceback
        traceback.print_exc()
        scan_entry["status"] = "failed"
        scan_entry["error"] = str(e)
        scan_entry["message"] = f"Scan failed: {str(e)}"


def start_scan_job(location, category, max_businesses, max_reviews, rating_threshold, negative_star_max):
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
        args=(scan_id, location, category, max_businesses, max_reviews, rating_threshold, negative_star_max)
    )
    thread.daemon = True
    thread.start()
    return scan_id


def get_scan_status(scan_id):
    return active_scans.get(scan_id)


def run_agent(location, category, max_businesses, max_reviews, rating_threshold, negative_star_max):
    """
    Poora pipeline ek function mein — UI (app.py) sirf isko call karega.
    2-phase approach: pehle sirf ratings check karo (fast), phir sirf
    qualifying businesses ke reviews fetch karo (lowestRanking sort se).
    Returns: dict with 'results', 'filename', 'total_scanned', 'flagged_count', 'dropped_no_contact'
    """
    businesses = fetch_businesses_basic(location, category, max_businesses)
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

    with_reviews = fetch_reviews_for_businesses(rating_filtered, max_reviews)
    kept_businesses, dropped_count = attach_contact_info(with_reviews)
    results = build_review_rows(kept_businesses, negative_star_max)

    filename = None
    if results:
        filename = build_filename(location, category)
        export_to_excel(results, filename)

    return {
        "results": results,
        "filename": filename,
        "total_scanned": len(businesses),
        "flagged_count": len(set(r["Business Name"] for r in results)),
        "dropped_no_contact": dropped_count,
    }
