from kiteconnect import KiteConnect, KiteTicker
from datetime import date, timedelta
from supabase import create_client
import os, json, time, csv
from dotenv import load_dotenv

load_dotenv()

kite = KiteConnect(api_key=os.getenv("KITE_API_KEY"))
kite.set_access_token(os.getenv("KITE_ACCESS_TOKEN"))

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


def get_nifty500_symbols():
    sb = create_client(os.getenv("SUPABASE_URL"), os.getenv("SUPABASE_KEY"))
    r  = sb.table("index_composition")\
           .select("symbol")\
           .eq("index_name", "NIFTY 500")\
           .eq("is_current", True)\
           .execute()
    symbols = [row["symbol"] for row in r.data]
    print(f"Loaded {len(symbols)} Nifty 500 symbols from Supabase")
    return symbols


# ─── TEST — SINGLE SYMBOL ─────────────────────────────────────────────────────
def test_single(symbol="RELIANCE"):
    instruments = get_instruments()
    token       = get_token(symbol, instruments)

    if not token:
        print(f"Token not found for {symbol}")
        return

    print(f"Token for {symbol}: {token}")
    candles = kite.historical_data(
        instrument_token = token,
        from_date        = date.today() - timedelta(days=7),
        to_date          = date.today(),
        interval         = "day"
    )

    rows = []
    print(f"\n{'DATE':<15} {'OPEN':>8} {'HIGH':>8} {'LOW':>8} {'CLOSE':>8} {'VOLUME':>12}")
    print("-" * 65)
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

    with open(f"{symbol}_test.csv", "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=rows[0].keys())
        writer.writeheader()
        writer.writerows(rows)
    print(f"\nSaved to {symbol}_test.csv")


# ─── FETCH NIFTY 500 — 2000 DAYS ─────────────────────────────────────────────
def fetch_nifty500(days=2000):
    symbols     = get_nifty500_symbols()
    instruments = get_instruments()

    to_date   = date.today()
    from_date = to_date - timedelta(days=days)

    print(f"\n{'='*55}")
    print(f"  Nifty 500 Historical Fetch")
    print(f"  Range:   {from_date} to {to_date}")
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
                all_rows.append({
                    "symbol":    symbol,
                    "timeframe": "1d",
                    "date":      str(c["date"])[:10],
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
            cp = f"nifty500_checkpoint_{i+1}.csv"
            with open(cp, "w", newline="") as f:
                writer = csv.DictWriter(f, fieldnames=all_rows[0].keys())
                writer.writeheader()
                writer.writerows(all_rows)
            print(f"\n  Checkpoint: {cp} ({len(all_rows):,} rows)\n")

        time.sleep(0.4)

    # Save final
    final = "nifty500_2000days.csv"
    if all_rows:
        with open(final, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=all_rows[0].keys())
            writer.writeheader()
            writer.writerows(all_rows)

    print(f"\n{'='*55}")
    print(f"  DONE")
    print(f"  Rows:   {len(all_rows):,}")
    print(f"  Failed: {len(failed)}")
    print(f"  File:   {final}")
    if failed:
        print(f"  Failed symbols: {failed[:20]}")
    print(f"{'='*55}")


# ─── MAIN ─────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import sys
    mode = sys.argv[1] if len(sys.argv) > 1 else "test"

    if mode == "test":
        test_single("RELIANCE")

    elif mode == "nifty500":
        fetch_nifty500(days=2000)