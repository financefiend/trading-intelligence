import requests
import zipfile
import pandas as pd
from supabase import create_client
from datetime import date, timedelta
import os, time, io
from dotenv import load_dotenv

load_dotenv()
sb = create_client(os.getenv("SUPABASE_URL"), os.getenv("SUPABASE_KEY"))

HEADERS = {
    "User-Agent":      "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept":          "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.5",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection":      "keep-alive",
}

def get_symbols():
    r = sb.table("index_composition")\
        .select("symbol")\
        .eq("is_current", True)\
        .execute()
    symbols = {row["symbol"] for row in r.data}
    print(f"Tracking {len(symbols)} symbols")
    return symbols

def make_session():
    session = requests.Session()
    session.headers.update(HEADERS)
    try:
        session.get("https://www.nseindia.com", timeout=15)
        time.sleep(1)
        session.get("https://www.nseindia.com/all-reports", timeout=15)
        time.sleep(1)
    except Exception as e:
        print(f"  Session warning: {e}")
    return session

def get_url(dt):
    cutoff = date(2024, 7, 8)
    if dt >= cutoff:
        return (
            f"https://nsearchives.nseindia.com/content/cm/"
            f"BhavCopy_NSE_CM_0_0_0_{dt.strftime('%Y%m%d')}_F_0000.csv.zip"
        )
    else:
        mon = dt.strftime("%b").upper()
        return (
            f"https://archives.nseindia.com/content/historical/EQUITIES/"
            f"{dt.year}/{mon}/cm{dt.strftime('%d')}{mon}{dt.year}bhav.csv.zip"
        )

def download_bhavcopy(dt, session):
    url = get_url(dt)
    try:
        r = session.get(url, timeout=30)
        if r.status_code == 200 and len(r.content) > 1000 and b"PK" in r.content[:4]:
            return r.content, url
        elif r.status_code in (401, 403):
            return None, "session_expired"
    except Exception:
        pass
    return None, None

def parse_bhavcopy(content, dt, symbols):
    try:
        with zipfile.ZipFile(io.BytesIO(content)) as z:
            csv_name = z.namelist()[0]
            with z.open(csv_name) as f:
                df = pd.read_csv(f)

        df.columns = df.columns.str.strip().str.upper()

        if "TCKRSYMB" in df.columns:
            df = df.rename(columns={
                "TCKRSYMB":    "SYMBOL",
                "SCTYSRS":     "SERIES",
                "OPNPRIC":     "OPEN",
                "HGHPRIC":     "HIGH",
                "LWPRIC":      "LOW",
                "CLSPRIC":     "CLOSE",
                "TTLTRADGVOL": "VOLUME",
            })
        else:
            df = df.rename(columns={
                "OPEN_PRICE":  "OPEN",
                "HIGH_PRICE":  "HIGH",
                "LOW_PRICE":   "LOW",
                "CLOSE_PRICE": "CLOSE",
                "TTL_TRD_QNTY": "VOLUME",
                "TOTTRDQTY":   "VOLUME",
            })

        if "SERIES" in df.columns:
            df = df[df["SERIES"].str.strip() == "EQ"]

        df = df[df["SYMBOL"].isin(symbols)]

        if df.empty:
            return []

        rows = []
        date_str = dt.isoformat()
        for _, row in df.iterrows():
            try:
                rows.append({
                    "symbol":    str(row["SYMBOL"]).strip(),
                    "timeframe": "1d",
                    "ts":        date_str,
                    "open":      round(float(row["OPEN"]),  2),
                    "high":      round(float(row["HIGH"]),  2),
                    "low":       round(float(row["LOW"]),   2),
                    "close":     round(float(row["CLOSE"]), 2),
                    "volume":    int(float(row.get("VOLUME", 0))),
                    "exchange":  "NSE"
                })
            except Exception:
                continue
        return rows

    except Exception as e:
        print(f"  Parse error: {e}")
        return []

def store_rows(rows):
    if not rows:
        return 0
    for i in range(0, len(rows), 500):
        sb.table("ohlcv").upsert(
            rows[i:i+500],
            on_conflict="symbol,timeframe,ts"
        ).execute()
    return len(rows)

def get_processed_dates():
    r = sb.table("ohlcv")\
        .select("ts")\
        .eq("timeframe", "1d")\
        .order("ts", desc=True)\
        .limit(5000)\
        .execute()
    return {row["ts"][:10] for row in r.data}

def run(start_date=date(2025, 3, 28)):
    symbols   = get_symbols()
    processed = get_processed_dates()
    end_dt    = date.today()

    all_dates = []
    current = start_date
    while current <= end_dt:
        if current.weekday() < 5:
            if current.isoformat() not in processed:
                all_dates.append(current)
        current += timedelta(days=1)

    print(f"\n{'='*55}")
    print(f"  NSE Bhavcopy Fetcher")
    print(f"  From: {start_date} to {end_dt}")
    print(f"  Days to fetch: {len(all_dates)}")
    print(f"{'='*55}\n")

    session      = make_session()
    total_rows   = 0
    success_days = 0
    skipped      = 0

    for i, dt in enumerate(all_dates):
        content, url = download_bhavcopy(dt, session)

        if url == "session_expired":
            print("  Refreshing session...")
            session = make_session()
            content, url = download_bhavcopy(dt, session)

        if not content:
            skipped += 1
            continue

        rows = parse_bhavcopy(content, dt, symbols)

        if rows:
            stored        = store_rows(rows)
            total_rows   += stored
            success_days += 1
            print(f"  [{i+1}/{len(all_dates)}] {dt}  {stored:>4} rows stored")
        else:
            skipped += 1

        if (i + 1) % 100 == 0:
            session = make_session()

        time.sleep(0.5)

    print(f"\n{'='*55}")
    print(f"  Days stored:  {success_days}")
    print(f"  Total rows:   {total_rows:,}")
    print(f"  Skipped:      {skipped}")
    print(f"{'='*55}")

    sb.table("job_logs").insert({
        "job_name": "fetch_bhavcopy",
        "status":   "success",
        "message":  f"{total_rows:,} rows, {success_days} days"
    }).execute()


if __name__ == "__main__":
    symbols = get_symbols()
    session = make_session()

    test_date = date(2025, 4, 17)
    content, url = download_bhavcopy(test_date, session)

    with zipfile.ZipFile(io.BytesIO(content)) as z:
        with z.open(z.namelist()[0]) as f:
            df = pd.read_csv(f)

    df.columns = df.columns.str.strip().str.upper()
    df = df.rename(columns={"TCKRSYMB": "SYMBOL", "SCTYSRS": "SERIES"})
    df = df[df["SERIES"].str.strip() == "EQ"]

    bhavcopy_symbols = set(df["SYMBOL"].str.strip())

    missing = symbols - bhavcopy_symbols
    print(f"\nIn our DB but NOT in bhavcopy ({len(missing)}):")
    for s in sorted(missing):
        print(f"  {s}")

    extra = bhavcopy_symbols - symbols
    print(f"\nIn bhavcopy but NOT in our DB (sample 20):")
    for s in sorted(list(extra)[:20]):
        print(f"  {s}")