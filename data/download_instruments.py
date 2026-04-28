from kiteconnect import KiteConnect, KiteTicker
from datetime import date, timedelta
from supabase import create_client
import os, json, time, threading
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

# ─── WEBSOCKET — LIVE DATA ────────────────────────────────────────────────────
live_ticks = {}   # symbol → latest tick

def start_websocket(tokens_to_symbols):
    """
    Streams live tick data for all our symbols.
    Stores latest price in live_ticks dict.
    Runs in background thread.
    """
    ticker = KiteTicker(
        os.getenv("KITE_API_KEY"),
        os.getenv("KITE_ACCESS_TOKEN")
    )

    tokens = list(tokens_to_symbols.keys())

    def on_ticks(ws, ticks):
        for tick in ticks:
            token  = tick["instrument_token"]
            symbol = tokens_to_symbols.get(token, str(token))
            live_ticks[symbol] = {
                "symbol":    symbol,
                "ltp":       tick.get("last_price"),
                "open":      tick.get("ohlc", {}).get("open"),
                "high":      tick.get("ohlc", {}).get("high"),
                "low":       tick.get("ohlc", {}).get("low"),
                "close":     tick.get("ohlc", {}).get("close"),
                "volume":    tick.get("volume_traded", 0),
                "timestamp": str(tick.get("timestamp", ""))
            }

    def on_connect(ws, response):
        print(f"WebSocket connected. Subscribing to {len(tokens)} tokens...")
        ws.subscribe(tokens)
        ws.set_mode(ws.MODE_QUOTE, tokens)

    def on_close(ws, code, reason):
        print(f"WebSocket closed: {code} {reason}")

    def on_error(ws, code, reason):
        print(f"WebSocket error: {code} {reason}")

    ticker.on_ticks   = on_ticks
    ticker.on_connect = on_connect
    ticker.on_close   = on_close
    ticker.on_error   = on_error

    print("Starting WebSocket in background...")
    ticker.connect(threaded=True)
    return ticker

# ─── REST — HISTORICAL DATA (200 days, once) ─────────────────────────────────
def fetch_historical_all(symbols, instruments, days=200):
    """
    Fetches last N days of daily OHLCV for all symbols.
    Rate limited to 3 req/sec — safe for Kite.
    Stores to Supabase.
    """
    to_date   = date.today()
    from_date = to_date - timedelta(days=days)

    print(f"\n{'='*55}")
    print(f"  Historical Fetch: {from_date} to {to_date}")
    print(f"  Symbols: {len(symbols)}")
    print(f"{'='*55}\n")

    total  = 0
    failed = []

    for i, symbol in enumerate(symbols):
        token = get_token(symbol, instruments)

        if not token:
            failed.append(symbol)
            print(f"  [{i+1}/{len(symbols)}] {symbol:<20} NO TOKEN")
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

            rows = []
            for c in candles:
                ts = c["date"]
                if hasattr(ts, "date"):
                    ts = ts.date().isoformat()
                else:
                    ts = str(ts)[:10]

                rows.append({
                    "symbol":    symbol,
                    "timeframe": "1d",
                    "ts":        ts,
                    "open":      round(float(c["open"]),  2),
                    "high":      round(float(c["high"]),  2),
                    "low":       round(float(c["low"]),   2),
                    "close":     round(float(c["close"]), 2),
                    "volume":    int(c["volume"]),
                    "exchange":  "NSE"
                })

            # Upsert in chunks
            for j in range(0, len(rows), 500):
                sb.table("ohlcv").upsert(
                    rows[j:j+500],
                    on_conflict="symbol,timeframe,ts"
                ).execute()

            total += len(rows)
            print(f"  [{i+1}/{len(symbols)}] {symbol:<20} {len(rows)} rows")

        except Exception as e:
            err = str(e)
            if "Too many" in err or "rate" in err.lower():
                print(f"  Rate limit hit — sleeping 5s...")
                time.sleep(5)
                failed.append(symbol)
            else:
                print(f"  [{i+1}/{len(symbols)}] {symbol:<20} ERROR: {err[:60]}")
                failed.append(symbol)

        time.sleep(0.4)   # 2.5 req/sec — safely under 3/sec limit

    print(f"\n{'='*55}")
    print(f"  Done. Total rows: {total:,}")
    print(f"  Failed: {len(failed)} → {failed[:10]}")
    print(f"{'='*55}")

    sb.table("job_logs").insert({
        "job_name": "fetch_kite_historical",
        "status":   "success",
        "message":  f"{total:,} rows stored"
    }).execute()


# ─── TEST — SINGLE SYMBOL ─────────────────────────────────────────────────────
def test_single(symbol="RELIANCE"):
    instruments = get_instruments()
    token       = get_token(symbol, instruments)

    if not token:
        print(f"Token not found for {symbol}")
        return

    print(f"\nToken for {symbol}: {token}")
    print(f"Fetching last 7 days...")

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
            "ts":        ts,
            "open":      round(float(c["open"]),  2),
            "high":      round(float(c["high"]),  2),
            "low":       round(float(c["low"]),   2),
            "close":     round(float(c["close"]), 2),
            "volume":    int(c["volume"]),
        })

    # Save to local CSV
    import csv
    filename = f"{symbol}_test.csv"
    with open(filename, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=rows[0].keys())
        writer.writeheader()
        writer.writerows(rows)

    print(f"\nSaved {len(rows)} rows to {filename}")

# ─── MAIN ─────────────────────────────────────────────────────────────────────
def fetch_all_to_csv(days=200):
    instruments = get_instruments()
    symbols     = get_our_symbols()

    print(f"\n{'='*55}")
    print(f"  Fetching {days} days for {len(symbols)} symbols")
    print(f"  Saving to local CSV files")
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
                from_date        = date.today() - timedelta(days=days),
                to_date          = date.today(),
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

        # Save checkpoint every 50 symbols
        if (i + 1) % 50 == 0:
            import csv
            checkpoint_file = f"ohlcv_checkpoint_{i+1}.csv"
            with open(checkpoint_file, "w", newline="") as f:
                writer = csv.DictWriter(f, fieldnames=all_rows[0].keys())
                writer.writeheader()
                writer.writerows(all_rows)
            print(f"\n  Checkpoint saved: {checkpoint_file} ({len(all_rows)} rows)\n")

        time.sleep(0.4)   # 2.5 req/sec — safely under Kite's 3/sec limit

    # Save final CSV
    import csv
    final_file = "ohlcv_all_500.csv"
    with open(final_file, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=all_rows[0].keys())
        writer.writeheader()
        writer.writerows(all_rows)

    print(f"\n{'='*55}")
    print(f"  DONE")
    print(f"  Total rows:    {len(all_rows):,}")
    print(f"  Failed:        {len(failed)} symbols")
    print(f"  Saved to:      {final_file}")
    if failed:
        print(f"  Failed list:   {failed[:20]}")
    print(f"{'='*55}")


if __name__ == "__main__":
    import sys
    mode = sys.argv[1] if len(sys.argv) > 1 else "test"

    if mode == "test":
        test_single("RELIANCE")
    elif mode == "all":
        fetch_all_to_csv(days=200)
    elif mode == "live":
        pass  # WebSocket mode — add later