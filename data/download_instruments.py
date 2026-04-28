from kiteconnect import KiteConnect, KiteTicker
from datetime import date, timedelta
from supabase import create_client
import os, json, time, csv
from dotenv import load_dotenv

load_dotenv()

kite = KiteConnect(api_key=os.getenv("KITE_API_KEY"))
kite.set_access_token(os.getenv("KITE_ACCESS_TOKEN"))
sb   = create_client(os.getenv("SUPABASE_URL"), os.getenv("SUPABASE_KEY"))

INSTRUMENTS_FILE = "nse_instruments.json"

# ─── INSTRUMENTS CACHE ────────────────────────────────────────────────────────
def get_instruments():
    if os.path.exists(INSTRUMENTS_FILE):
        print("Loading instruments from cache...")
        with open(INSTRUMENTS_FILE) as f:
            return json.load(f)
    print("Downloading from Kite (one time)...")
    time.sleep(2)
    instruments = kite.instruments("NSE")
    with open(INSTRUMENTS_FILE, "w") as f:
        json.dump(instruments, f)
    print(f"Cached {len(instruments)} instruments")
    return instruments

def get_token(symbol, instruments):
    for inst in instruments:
        if (inst["tradingsymbol"] == symbol and
                inst["instrument_type"] == "EQ"):
            return inst["instrument_token"]
    return None

def get_our_symbols():
    import pandas as pd
    df = pd.read_excel("symbol_mapping.xlsx")
    df.columns = df.columns.str.strip()
    symbols = df["symbol"].dropna().str.strip().tolist()
    print(f"Loaded {len(symbols)} symbols from symbol_mapping.xlsx")
    return symbols

# ─── TEST — SINGLE SYMBOL ─────────────────────────────────────────────────────
def test_single(symbol="RELIANCE"):
    instruments = get_instruments()
    token       = get_token(symbol, instruments)

    if not token:
        print(f"Token not found for {symbol}")
        return

    print(f"\nToken for {symbol}: {token}")
    candles = kite.historical_data(
        instrument_token = token,
        from_date        = date.today() - timedelta(days=7),
        to_date          = date.today(),
        interval         = "day"
    )

    print(f"\n{'DATE':<15} {'OPEN':>8} {'HIGH':>8} {'LOW':>8} {'CLOSE':>8} {'VOLUME':>12}")
    print("-" * 65)

    rows = []
    for c in candles:
        ts = str(c["date"])[:10]
        print(f"{ts:<15} {c['open']:>8} {c['high']:>8} {c['low']:>8} {c['close']:>8} {c['volume']:>12}")
        rows.append({
            "symbol":    symbol,
            "timeframe": "1d",
            "date":      ts,
            "open":      round(float(c["open"]),  2),
            "high":      round(float(c["high"]),  2),
            "low":       round(float(c["low"]),   2),
            "close":     round(float(c["close"]), 2),
            "volume":    int(c["volume"]),
        })

    filename = f"{symbol}_test.csv"
    with open(filename, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=rows[0].keys())
        writer.writeheader()
        writer.writerows(rows)
    print(f"\nSaved {len(rows)} rows to {filename}")

# ─── FETCH ALL — CHUNKED BY DATE RANGE ───────────────────────────────────────
def fetch_all_to_csv(chunk=0, chunk_size=2000):
    """
    chunk=0 → today going back 2000 days        (most recent)
    chunk=1 → 2000-4000 days back
    chunk=2 → 4000-6000 days back
    etc.

    Kite allows max 2000 days per call.
    """
    instruments = get_instruments()
    symbols     = get_our_symbols()

    to_date   = date.today() - timedelta(days = chunk * chunk_size)
    from_date = to_date - timedelta(days = chunk_size)

    print(f"\n{'='*55}")
    print(f"  Chunk {chunk}: {from_date} → {to_date}")
    print(f"  Symbols: {len(symbols)}")
    print(f"{'='*55}\n")

    all_rows = []
    failed   = []

    for i, symbol in enumerate(symbols):
        token = get_token(symbol, instruments)

        if not token:
            print(f"  [{i+1}/{len(symbols)}] {symbol:<20} NO TOKEN")
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
                print(f"  [{i+1}/{len(symbols)}] {symbol:<20} NO DATA")
                failed.append(symbol)
                time.sleep(0.4)
                continue

            for c in candles:
                ts = str(c["date"])[:10]
                all_rows.append({
                    "symbol":    symbol,
                    "timeframe": "1d",
                    "date":      ts,
                    "open":      round(float(c["open"]),  2),
                    "high":      round(float(c["high"]),  2),
                    "low":       round(float(c["low"]),   2),
                    "close":     round(float(c["close"]), 2),
                    "volume":    int(c["volume"]),
                })

            print(f"  [{i+1}/{len(symbols)}] {symbol:<20} {len(candles)} rows ✓")

        except Exception as e:
            err = str(e)
            if "Too many" in err or "rate" in err.lower():
                print(f"  [{i+1}/{len(symbols)}] {symbol:<20} RATE LIMIT — sleeping 10s")
                time.sleep(10)
                failed.append(symbol)
            else:
                print(f"  [{i+1}/{len(symbols)}] {symbol:<20} ERROR: {err[:50]}")
                failed.append(symbol)

        # Checkpoint every 50 symbols
        if (i + 1) % 50 == 0 and all_rows:
            cp = f"ohlcv_chunk{chunk}_checkpoint_{i+1}.csv"
            with open(cp, "w", newline="") as f:
                writer = csv.DictWriter(f, fieldnames=all_rows[0].keys())
                writer.writeheader()
                writer.writerows(all_rows)
            print(f"\n  Checkpoint: {cp} ({len(all_rows)} rows)\n")

        time.sleep(0.4)

    # Save final
    final = f"ohlcv_chunk{chunk}.csv"
    if all_rows:
        with open(final, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=all_rows[0].keys())
            writer.writeheader()
            writer.writerows(all_rows)

    print(f"\n{'='*55}")
    print(f"  DONE — Chunk {chunk}")
    print(f"  Rows:    {len(all_rows):,}")
    print(f"  Failed:  {len(failed)}")
    print(f"  File:    {final}")
    if failed:
        print(f"  Failed:  {failed[:10]}")
    print(f"{'='*55}")


# ─── MAIN ─────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import sys
    mode = sys.argv[1] if len(sys.argv) > 1 else "test"

    if mode == "test":
        # Single symbol test
        test_single("RELIANCE")

    elif mode == "chunk0":
        # Days 0-2000 (most recent — already done as ohlcv_all_500.csv)
        fetch_all_to_csv(chunk=0)

    elif mode == "chunk1":
        # Days 2000-4000
        fetch_all_to_csv(chunk=1)

    elif mode == "chunk2":
        # Days 4000-6000
        fetch_all_to_csv(chunk=2)

    elif mode == "chunk3":
        # Days 6000-8000
        fetch_all_to_csv(chunk=3)