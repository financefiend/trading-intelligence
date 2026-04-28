import xlrd
import pandas as pd
from supabase import create_client
from datetime import datetime, date
import os, time
from dotenv import load_dotenv

load_dotenv()

supabase = create_client(os.getenv("SUPABASE_URL"), os.getenv("SUPABASE_KEY"))

XLS_FILE = "IndexInclExcl.xls"

# Map sheet names to our standard index names
INDEX_MAP = {
    "Nifty 500":          "NIFTY 500",
    "Nifty 50":           "NIFTY 50",
    "Nifty Midcap 100":   "NIFTY MIDCAP 150",
    "Nifty Smallcap 100": "NIFTY SMALLCAP 250",
}

def parse_date(date_str):
    """Convert DD-MM-YYYY to YYYY-MM-DD"""
    try:
        return datetime.strptime(str(date_str).strip(), "%d-%m-%Y").strftime("%Y-%m-%d")
    except:
        try:
            return datetime.strptime(str(date_str).strip(), "%d/%m/%Y").strftime("%Y-%m-%d")
        except:
            return None

def load_sheet(wb, sheet_name, index_name):
    print(f"\n  Loading {index_name} from sheet '{sheet_name}'...")

    try:
        ws = wb.sheet_by_name(sheet_name)
    except:
        print(f"  Sheet not found — skipping")
        return 0

    print(f"  Rows: {ws.nrows}")

    inclusions  = {}   # symbol → earliest inclusion date
    exclusions  = {}   # symbol → exclusion date
    rebalancing = {}   # date → {added: [], removed: []}

    for i in range(1, ws.nrows):
        row = ws.row_values(i)

        if len(row) < 4:
            continue

        index_col   = str(row[0]).strip()
        event_date  = str(row[1]).strip()
        scrip_name  = str(row[2]).strip()
        description = str(row[3]).strip().lower()

        if not scrip_name or not event_date:
            continue

        parsed_date = parse_date(event_date)
        if not parsed_date:
            continue

        is_inclusion = "inclusion" in description
        is_exclusion = "exclusion" in description or "deletion" in description

        if is_inclusion:
            if scrip_name not in inclusions:
                inclusions[scrip_name] = parsed_date
            # Track rebalancing
            if parsed_date not in rebalancing:
                rebalancing[parsed_date] = {"added": [], "removed": []}
            rebalancing[parsed_date]["added"].append(scrip_name)

        elif is_exclusion:
            exclusions[scrip_name] = parsed_date
            if parsed_date not in rebalancing:
                rebalancing[parsed_date] = {"added": [], "removed": []}
            rebalancing[parsed_date]["removed"].append(scrip_name)

    print(f"  Inclusions: {len(inclusions)}  Exclusions: {len(exclusions)}")
    print(f"  Rebalancing events: {len(rebalancing)}")

    # Store compositions
    stored = 0
    today  = date.today().isoformat()

    for scrip_name, incl_date in inclusions.items():
        excl_date  = exclusions.get(scrip_name)
        is_current = excl_date is None

        try:
            supabase.table("index_composition").upsert({
                "index_name":     index_name,
                "symbol":         scrip_name,
                "company_name":   scrip_name,
                "effective_from": incl_date,
                "effective_to":   excl_date,
                "is_current":     is_current
            }, on_conflict="index_name,symbol,effective_from").execute()
            stored += 1
        except Exception as e:
            print(f"    Error storing {scrip_name}: {e}")

        if stored % 100 == 0:
            print(f"    Stored {stored}...")

    print(f"  Total stored: {stored}")

    # Store rebalancing events
    rb_stored = 0
    for event_date, changes in rebalancing.items():
        if not changes["added"] and not changes["removed"]:
            continue
        try:
            supabase.table("index_rebalancing").upsert({
                "index_name":     index_name,
                "effective_date": event_date,
                "added":          changes["added"],
                "removed":        changes["removed"],
                "source_url":     "archives.nseindia.com/content/indices/IndexInclExcl.xls",
                "circular_ref":   f"NSE_official_{event_date}"
            }, on_conflict="index_name,effective_date").execute()
            rb_stored += 1
        except Exception as e:
            pass

    print(f"  Rebalancing events stored: {rb_stored}")
    return stored


def run():
    print(f"\n{'='*55}")
    print(f"  NSE Index Historical Composition Loader")
    print(f"  Source: IndexInclExcl.xls (NSE Official)")
    print(f"  {datetime.now().strftime('%d %b %Y %H:%M')}")
    print(f"{'='*55}")

    try:
        wb = xlrd.open_workbook(XLS_FILE)
        print(f"  Sheets available: {wb.sheet_names()[:5]}...")
    except Exception as e:
        print(f"  ERROR opening file: {e}")
        return

    grand_total = 0
    for sheet_name, index_name in INDEX_MAP.items():
        count = load_sheet(wb, sheet_name, index_name)
        grand_total += count
        time.sleep(1)

    print(f"\n{'='*55}")
    print(f"  DONE. Total compositions stored: {grand_total}")
    print(f"{'='*55}\n")

    supabase.table("job_logs").insert({
        "job_name": "index_scraper",
        "status":   "success",
        "message":  f"{grand_total} compositions stored from NSE official XLS"
    }).execute()


if __name__ == "__main__":
    run()