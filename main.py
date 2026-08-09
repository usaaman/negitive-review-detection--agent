"""
Negative Reviews Finder Agent
------------------------------
Ye script Google Maps se businesses dhoondta hai, jin ki rating
kam hai (default <4.5) unko filter karta hai, aur unke negative
reviews (direct review link ke sath) nikaal kar ek Excel file
mein save karta hai.
"""

import os
import sys
from apify_client import ApifyClient
import pandas as pd
import xlsxwriter
from dotenv import load_dotenv

# ---------- Step 1: Load API token from .env file ----------
load_dotenv()
API_TOKEN = os.getenv("APIFY_API_TOKEN")

if not API_TOKEN:
    print("ERROR: APIFY_API_TOKEN nahi mila .env file mein.")
    print("Check karo .env file mein ye line hai: APIFY_API_TOKEN=your_token_here")
    sys.exit(1)

client = ApifyClient(API_TOKEN)


# ---------- Step 2: Get inputs from user ----------
def get_inputs():
    print("=" * 50)
    print("NEGATIVE REVIEWS FINDER AGENT")
    print("=" * 50)

    location = input("Location (jaise: Karachi, Pakistan): ").strip()
    category = input("Business category (jaise: restaurants): ").strip()

    max_businesses = input("Kitne businesses chahiye? (jaise: 10): ").strip()
    max_businesses = int(max_businesses) if max_businesses else 10

    max_reviews = input("Har business ke kitne reviews check karne hain? (jaise: 10): ").strip()
    max_reviews = int(max_reviews) if max_reviews else 10

    rating_threshold = input("Rating threshold (isse kam rating wale filter honge, default 4.5): ").strip()
    rating_threshold = float(rating_threshold) if rating_threshold else 4.5

    negative_star_max = input("Negative review kya maana jaye? (kitne star tak, default 3): ").strip()
    negative_star_max = int(negative_star_max) if negative_star_max else 3

    return location, category, max_businesses, max_reviews, rating_threshold, negative_star_max


# ---------- Step 3: Call Apify actor to get businesses + reviews ----------
def fetch_businesses_with_reviews(location, category, max_businesses, max_reviews):
    print("\n[1/3] Apify se businesses aur reviews mangwa rahe hain...")

    run_input = {
        "searchStringsArray": [category],
        "locationQuery": location,
        "maxCrawledPlacesPerSearch": max_businesses,
        "maxReviews": max_reviews,
        "reviewsSort": "newest",
        "language": "en",
    }

    run = client.actor("compass/crawler-google-places").call(run_input=run_input)

    # Naye apify-client version mein 'run' ek object hoti hai, dict nahi
    dataset_id = run.get("defaultDatasetId") if isinstance(run, dict) else run.default_dataset_id
    items = list(client.dataset(dataset_id).iterate_items())
    print(f"    -> {len(items)} businesses mile.")
    return items


# ---------- Step 4: Filter businesses by rating, extract negative reviews ----------
def filter_negative_reviews(businesses, rating_threshold, negative_star_max):
    print(f"\n[2/3] Rating < {rating_threshold} wale businesses filter kar rahe hain...")

    results = []

    for biz in businesses:
        rating = biz.get("totalScore")
        if rating is None or rating >= rating_threshold:
            continue  # skip businesses with good rating

        biz_name = biz.get("title", "N/A")
        address = biz.get("address", "N/A")
        phone = biz.get("phone", "N/A")
        biz_url = biz.get("url", "N/A")
        reviews = biz.get("reviews", []) or []

        found_negative = False

        for rev in reviews:
            stars = rev.get("stars")
            if stars is None or stars > negative_star_max:
                continue  # skip positive reviews

            found_negative = True
            results.append({
                "Business Name": biz_name,
                "Address": address,
                "Phone": phone,
                "Business Rating": rating,
                "Reviewer Name": rev.get("name", "N/A"),
                "Review Stars": stars,
                "Review Text": rev.get("text", ""),
                "Review Date": rev.get("publishedAtDate", "N/A"),
                "Review Link": rev.get("reviewUrl", "N/A"),
                "Business Maps Link": biz_url,
            })

        if not found_negative:
            # business rating kam hai lekin fetched reviews mein negative nahi mila
            results.append({
                "Business Name": biz_name,
                "Address": address,
                "Phone": phone,
                "Business Rating": rating,
                "Reviewer Name": "N/A",
                "Review Stars": "N/A",
                "Review Text": "(Fetched reviews mein negative review nahi mila)",
                "Review Date": "N/A",
                "Review Link": "N/A",
                "Business Maps Link": biz_url,
            })

    print(f"    -> {len(results)} rows (negative reviews + no-negative-found businesses) mile.")
    return results


# ---------- Step 5: Export to Excel with clickable review links ----------
def export_to_excel(results, filename="negative_reviews_output.xlsx"):
    print(f"\n[3/3] Excel file bana rahe hain: {filename}")

    if not results:
        print("    -> Koi data nahi mila filter ke baad. Excel nahi banayi.")
        return

    df = pd.DataFrame(results)

    workbook = xlsxwriter.Workbook(filename)
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
    link_cols = {"Review Link": "View Link", "Business Maps Link": "Open Map"}

    max_lens = [len(str(h)) for h in headers]

    # Write Data Rows
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

    # Auto-Fit Column Widths (No Text Cropping)
    for col_idx in range(len(headers)):
        worksheet.set_column(col_idx, col_idx, max_lens[col_idx] + 3)

    workbook.close()
    print(f"    -> Done! File save ho gayi: {filename}")


# ---------- Main ----------
if __name__ == "__main__":
    location, category, max_businesses, max_reviews, rating_threshold, negative_star_max = get_inputs()

    businesses = fetch_businesses_with_reviews(location, category, max_businesses, max_reviews)
    results = filter_negative_reviews(businesses, rating_threshold, negative_star_max)
    export_to_excel(results)

    print("\n" + "=" * 50)
    print("COMPLETE! Excel file check karo apne folder mein.")
    print("=" * 50)