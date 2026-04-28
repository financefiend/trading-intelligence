import requests
import pdfplumber
import pandas as pd
from supabase import create_client
from datetime import datetime, date, timedelta
import os, time, io, re
from dotenv import load_dotenv

load_dotenv()
supabase = create_client(os.getenv("SUPABASE_URL"), os.getenv("SUPABASE_KEY"))

# ─── ALL KNOWN REBALANCING PRESS RELEASE DATES ───────────────────────────────
# Format: (effective_date, [candidate_pdf_dates_to_try])
# We try multiple candidate dates around the expected announcement window

REBALANCING_EVENTS = [
    # 2020
    ("2020-03-27", ["23032020", "13032020", "06032020"]),
    ("2020-09-25", ["21082020", "28082020", "14082020"]),
    # 2021  
    ("2021-03-26", ["19022021", "12022021", "26022021", "05032021"]),
    ("2021-09-30", ["20082021", "27082021", "13082021", "06082021"]),
    # 2022
    ("2022-03-31", ["18022022", "25022022", "11022022", "04032022"]),
    ("2022-09-30", ["19082022", "26082022", "12082022", "02092022"]),
    # 2023
    ("2023-03-31", ["17022023", "24022023", "10022023", "03032023"]),
    ("2023-09-29", ["18082023", "25082023", "11082023", "01092023"]),
    # 2024
    ("2024-03-28", ["28022024", "21022024", "14022024"]),
    ("2024-09-27", ["23082024", "16082024", "09082024"]),
    # 2025
    ("2025-03-28", ["21022025", "14022025", "28022025"]),
    ("2025-09-26", ["22082025", "15082025", "29082025"]),
]

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Referer":    "https://www.niftyindices.com"
}


# ─── DOWNLOAD PDF ─────────────────────────────────────────────────────────────
def download_pdf(date_str):
    """Try to download press release PDF for a given date string DDMMYYYY"""
    url = f"https://www.niftyindices.com/Press_Release/ind_prs{date_str}.pdf"
    try:
        resp = requests.get(url, headers=HEADERS, timeout=30)
        if resp.status_code == 200 and b"%PDF" in resp.content[:10]:
            print(f"    Found PDF: ind_prs{date_str}.pdf ({len(resp.content)//1024}KB)")
            return resp.content, url
    except Exception as e:
        pass
    return None, None


# ─── PARSE NIFTY 500 CHANGES FROM PDF ─────────────────────────────────────────
def parse_nifty500_changes(pdf_bytes):
    """
    Extract Nifty 500 additions and deletions from press release PDF.
    Returns (added_symbols, removed_symbols)
    """
    added   = []
    removed = []

    try:
        with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
            full_text = ""
            for page in pdf.pages:
                full_text += page.extract_text() or ""

        # Find Nifty 500 section
        # Pattern: look for "Nifty 500" section with inclusion/exclusion tables
        lines = full_text.split("\n")

        in_nifty500 = False
        in_inclusion = False
        in_exclusion = False

        for i, line in enumerate(lines):
            line_clean = line.strip()

            # Detect Nifty 500 section start
            if "nifty 500" in line_clean.lower() and (
                "inclusion" in line_clean.lower() or
                "exclusion" in line_clean.lower() or
                "replacement" in line_clean.lower() or
                i < len(lines) - 1 and "inclusion" in lines[i+1].lower()
            ):
                in_nifty500 = True

            # Detect end of Nifty 500 section (next index starts)
            if in_nifty500 and any(idx in line_clean for idx in [
                "Nifty 100", "Nifty 50 ", "Nifty Next 50",
                "Nifty Midcap", "Nifty Smallcap", "Nifty Bank"
            ]) and "500" not in line_clean:
                in_nifty500 = False
                in_inclusion = False
                in_exclusion = False

            if not in_nifty500:
                continue

            # Detect inclusion/exclusion subsections
            if "inclusion" in line_clean.lower():
                in_inclusion = True
                in_exclusion = False
                continue
            if "exclusion" in line_clean.lower():
                in_exclusion = True
                in_inclusion = False
                continue

            # Extract ticker symbols (format: SYMBOL or (SYMBOL))
            # NSE symbols are in brackets or after company name
            symbol_match = re.findall(r'\(([A-Z0-9\-&]+)\)', line_clean)
            if symbol_match:
                for sym in symbol_match:
                    if 2 <= len(sym) <= 20:
                        if in_inclusion:
                            added.append(sym)
                        elif in_exclusion:
                            removed.append(sym)

    except Exception as e:
        print(f"    Parse error: {e}")

    return list(set(added)), list(set(removed))


# ─── PARSE USING TABLE EXTRACTION ─────────────────────────────────────────────
def parse_nifty500_tables(pdf_bytes):
    """
    Alternative parser using table extraction.
    Press releases have structured tables for each index.
    """
    added   = []
    removed = []

    try:
        with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
            for page in pdf.pages:
                text = page.extract_text() or ""

                # Check if this page has Nifty 500 content
                if "nifty 500" not in text.lower() and "nifty500" not in text.lower():
                    continue

                tables = page.extract_tables()
                for table in tables:
                    for row in table:
                        if not row:
                            continue
                        row_text = " ".join([str(c or "") for c in row])

                        # Look for rows with NSE symbols (in brackets)
                        symbols = re.findall(r'\(([A-Z0-9\-&]{2,20})\)', row_text)
                        for sym in symbols:
                            # Check context for inclusion/exclusion
                            if any(w in row_text.lower() for w in
                                   ["includ", "replac", "addition", "new"]):
                                added.append(sym)
                            elif any(w in row_text.lower() for w in
                                     ["exclud", "delet", "remov"]):
                                removed.append(sym)

    except Exception as e:
        print(f"    Table parse error: {e}")

    return list(set(added)), list(set(removed))


# ─── STORE REBALANCING EVENT ───────────────────────────────────────────────────
def store_rebalancing(effective_date, added, removed, source_url):
    if not added and not removed:
        return

    try:
        supabase.table("index_rebalancing").upsert({
            "index_name":     "NIFTY 500",
            "effective_date": effective_date,
            "added":          added,
            "removed":        removed,
            "source_url":     source_url,
            "circular_ref":   f"niftyindices_pressrelease_{effective_date}"
        }, on_conflict="index_name,effective_date").execute()
        print(f"    Stored: +{len(added)} added, -{len(removed)} removed")
    except Exception as e:
        print(f"    Store error: {e}")


def update_composition(effective_date, added, removed):
    """Update index_composition based on rebalancing event"""
    today = date.today().isoformat()

    # Mark removed stocks as no longer current
    for symbol in removed:
        try:
            supabase.table("index_composition")\
                .update({
                    "effective_to": effective_date,
                    "is_current":   False
                })\
                .eq("index_name", "NIFTY 500")\
                .eq("symbol", symbol)\
                .is_("effective_to", "null")\
                .execute()
        except Exception as e:
            pass

    # Add new stocks
    for symbol in added:
        try:
            supabase.table("index_composition").upsert({
                "index_name":     "NIFTY 500",
                "symbol":         symbol,
                "company_name":   symbol,
                "effective_from": effective_date,
                "effective_to":   None,
                "is_current":     True
            }, on_conflict="index_name,symbol,effective_from").execute()
        except Exception as e:
            pass


# ─── MAIN ─────────────────────────────────────────────────────────────────────
def run():
    print(f"\n{'='*55}")
    print(f"  Nifty 500 Composition Gap Filler")
    print(f"  Source: niftyindices.com Press Releases")
    print(f"  Covering: Aug 2020 → Present")
    print(f"{'='*55}")

    successful = 0
    failed     = []

    for effective_date, candidate_dates in REBALANCING_EVENTS:
        # Skip future dates
        if effective_date > date.today().isoformat():
            continue

        print(f"\n  Rebalancing: {effective_date}")
        pdf_bytes = None
        source_url = None

        # Try each candidate date
        for date_str in candidate_dates:
            pdf_bytes, source_url = download_pdf(date_str)
            if pdf_bytes:
                break
            time.sleep(0.5)

        if not pdf_bytes:
            print(f"    No PDF found — trying text search")
            failed.append(effective_date)
            continue

        # Parse the PDF
        added, removed = parse_nifty500_changes(pdf_bytes)

        # Fallback to table parser if text parser got nothing
        if not added and not removed:
            added, removed = parse_nifty500_tables(pdf_bytes)

        if added or removed:
            print(f"    Parsed: +{len(added)} additions, -{len(removed)} removals")
            store_rebalancing(effective_date, added, removed, source_url)
            update_composition(effective_date, added, removed)
            successful += 1
        else:
            print(f"    PDF found but couldn't parse Nifty 500 changes")
            # Save PDF locally for manual inspection
            with open(f"debug_pr_{effective_date}.pdf", "wb") as f:
                f.write(pdf_bytes)
            print(f"    Saved to debug_pr_{effective_date}.pdf for manual check")
            failed.append(effective_date)

        time.sleep(2)

    print(f"\n{'='*55}")
    print(f"  Successful: {successful}")
    print(f"  Failed/Missing: {len(failed)}")
    if failed:
        print(f"  Failed dates: {failed}")
    print(f"{'='*55}\n")


# ─── VERIFICATION ─────────────────────────────────────────────────────────────
def verify_current_count():
    """Check how many current stocks we have vs expected 500"""
    result = supabase.table("index_composition")\
        .select("symbol", count="exact")\
        .eq("index_name", "NIFTY 500")\
        .eq("is_current", True)\
        .execute()

    print(f"\nCurrent Nifty 500 count in DB: {result.count}")
    print(f"Expected: 500")
    print(f"Gap: {500 - (result.count or 0)}")


if __name__ == "__main__":
    run()
    verify_current_count()