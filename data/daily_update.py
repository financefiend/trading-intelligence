import pandas as pd
from kiteconnect import KiteConnect
from supabase import create_client
from datetime import date, timedelta, datetime
import os, json, time
from dotenv import load_dotenv

load_dotenv()

sb   = create_client(os.getenv("SUPABASE_URL"), os.getenv("SUPABASE_KEY"))
kite = KiteConnect(api_key=os.getenv("KITE_API_KEY"))
kite.set_access_token(os.getenv("KITE_ACCESS_TOKEN"))

INSTRUMENTS_FILE = "nse_instruments.json"


# ─── HELPERS ──────────────────────────────────────────────────────────────────
def get_nifty500_symbols():
    r = sb.table("index_composition")\
        .select("symbol")\
        .eq("index_name", "NIFTY 500")\
        .eq("is_current", True)\
        .execute()
    symbols = {row["symbol"] for row in r.data}
    print(f"Tracking {len(symbols)} Nifty 500 symbols")
    return symbols


def get_instruments():
    if os.path.exists(INSTRUMENTS_FILE):
        with open(INSTRUMENTS_FILE) as f:
            return json.load(f)
    print("Downloading instruments from Kite...")
    time.sleep(2)
    instruments = kite.instruments("NSE")
    with open(INSTRUMENTS_FILE, "w") as f:
        json.dump(instruments, f)
    print(f"Cached {len(instruments)} instruments")
    return instruments


def get_token(symbol, instruments):
    for inst in instruments:
        if inst["tradingsymbol"] == symbol and inst["instrument_type"] == "EQ":
            return inst["instrument_token"]
    return None


# ─── STEP 1: FETCH MISSING DATA FROM KITE ────────────────────────────────────
def fetch_from_kite(symbols, instruments):
    # Find last stored date in ohlcv
    r = sb.table("ohlcv")\
        .select("ts")\
        .eq("timeframe", "1d")\
        .order("ts", desc=True)\
        .limit(1)\
        .execute()

    if r.data:
        last_date = date.fromisoformat(r.data[0]["ts"][:10])
        from_date = last_date - timedelta(days=5)  # go back 5 days to catch gaps
        print(f"Last stored date: {last_date}")
    else:
        from_date = date.today() - timedelta(days=7)
        print("No existing data — fetching last 7 days")

    to_date = date.today()
    print(f"Fetching: {from_date} to {to_date}\n")

    rows   = []
    failed = []

    for i, symbol in enumerate(list(symbols)):
        token = get_token(symbol, instruments)

        if not token:
            failed.append(symbol)
            continue

        try:
            candles = kite.historical_data(
                instrument_token = token,
                from_date        = from_date,
                to_date          = to_date,
                interval         = "day",
                continuous       = False,
                oi               = False
            )

            if not candles:
                failed.append(symbol)
                continue

            for c in candles:
                rows.append({
                    "symbol":    symbol,
                    "timeframe": "1d",
                    "ts":        str(c["date"])[:10],
                    "open":      round(float(c["open"]),  2),
                    "high":      round(float(c["high"]),  2),
                    "low":       round(float(c["low"]),   2),
                    "close":     round(float(c["close"]), 2),
                    "volume":    int(c["volume"]),
                    "exchange":  "NSE"
                })

            if (i + 1) % 50 == 0:
                print(f"  [{i+1}/{len(symbols)}] fetched...")

        except Exception as e:
            err = str(e)
            if "Too many" in err or "rate" in err.lower():
                print(f"  Rate limit — sleeping 5s")
                time.sleep(5)
            failed.append(symbol)

        time.sleep(0.4)

    print(f"\nFetched {len(rows)} total rows")
    print(f"Failed:  {len(failed)} symbols")
    return rows, to_date


# ─── STEP 2: UPDATE OHLCV ────────────────────────────────────────────────────
def update_ohlcv(rows):
    if not rows:
        return 0
    stored = 0
    for i in range(0, len(rows), 500):
        sb.table("ohlcv").upsert(
            rows[i:i+500],
            on_conflict="symbol,timeframe,ts"
        ).execute()
        stored += len(rows[i:i+500])
    print(f"Stored {stored} rows to ohlcv")
    return stored


# ─── STEP 3: UPDATE DMA BREADTH FOR MISSING DATES ────────────────────────────
def update_dma_breadth_range(symbols, from_date, to_date):
    print(f"Calculating DMA breadth from {from_date} to {to_date}...")

    # Find which dates already exist in dma_breadth
    r = sb.table("dma_breadth")\
        .select("date")\
        .eq("index_name", "NIFTY 500")\
        .gte("date", from_date.isoformat())\
        .lte("date", to_date.isoformat())\
        .execute()

    existing_dates = {row["date"] for row in r.data}

    # Find all weekdays in range that are missing
    missing_dates = []
    current = from_date
    while current <= to_date:
        if current.weekday() < 5 and current.isoformat() not in existing_dates:
            missing_dates.append(current)
        current += timedelta(days=1)

    print(f"Missing dates to calculate: {len(missing_dates)}")

    if not missing_dates:
        print("All dates already calculated — nothing to do")
        return

    for dt in missing_dates:
        above_count = 0
        below_count = 0
        processed   = 0

        for symbol in symbols:
            try:
                r = sb.table("ohlcv")\
                    .select("ts,close")\
                    .eq("symbol", symbol)\
                    .eq("timeframe", "1d")\
                    .lte("ts", dt.isoformat())\
                    .order("ts", desc=True)\
                    .limit(250)\
                    .execute()

                if not r.data or len(r.data) < 200:
                    continue

                df           = pd.DataFrame(r.data)
                df["close"]  = df["close"].astype(float)
                df           = df.sort_values("ts")
                df["sma200"] = df["close"].rolling(200, min_periods=200).mean()

                latest = df.iloc[-1]
                if pd.isna(latest["sma200"]):
                    continue

                if latest["close"] > latest["sma200"]:
                    above_count += 1
                else:
                    below_count += 1

                processed += 1

            except Exception:
                continue

        total     = above_count + below_count
        pct_above = round((above_count / total) * 100, 2) if total > 0 else 0

        sb.table("dma_breadth").upsert({
            "date":         dt.isoformat(),
            "index_name":   "NIFTY 500",
            "above_200dma": above_count,
            "below_200dma": below_count,
            "total_stocks": total,
            "pct_above":    pct_above
        }, on_conflict="date,index_name").execute()

        print(f"  {dt} → above={above_count} below={below_count} ({pct_above}%)")


# ─── MAIN ─────────────────────────────────────────────────────────────────────
def run():
    print(f"\n{'='*55}")
    print(f"  Daily Update — {datetime.now().strftime('%d %b %Y %H:%M')}")
    print(f"{'='*55}\n")

    symbols     = get_nifty500_symbols()
    instruments = get_instruments()

    # Step 1: Fetch missing data from Kite
    print("Step 1: Fetching missing data from Kite...")
    rows, to_date = fetch_from_kite(symbols, instruments)

    if not rows:
        print("No new data fetched — already up to date")
        sb.table("job_logs").insert({
            "job_name": "daily_update",
            "status":   "success",
            "message":  "Already up to date"
        }).execute()
        return

    # Step 2: Update ohlcv table
    print("\nStep 2: Updating ohlcv table...")
    update_ohlcv(rows)

    # Step 3: Update DMA breadth for all missing dates
    print("\nStep 3: Updating DMA breadth...")
    dates_in_rows = sorted({row["ts"] for row in rows})
    from_date     = date.fromisoformat(dates_in_rows[0])
    update_dma_breadth_range(symbols, from_date, to_date)

    print(f"\n{'='*55}")
    print(f"  Done — updated through {to_date}")
    print(f"{'='*55}\n")

    sb.table("job_logs").insert({
        "job_name": "daily_update",
        "status":   "success",
        "message":  f"{len(rows)} rows fetched, breadth updated to {to_date}"
    }).execute()


if __name__ == "__main__":
    run()