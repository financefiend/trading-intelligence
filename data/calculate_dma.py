import pandas as pd
from supabase import create_client
import os
from dotenv import load_dotenv

load_dotenv()
sb = create_client(os.getenv("SUPABASE_URL"), os.getenv("SUPABASE_KEY"))

def get_nifty500_symbols():
    r = sb.table("index_composition")\
        .select("symbol")\
        .eq("index_name", "NIFTY 500")\
        .eq("is_current", True)\
        .execute()
    symbols = {row["symbol"] for row in r.data}
    print(f"Nifty 500 symbols: {len(symbols)}")
    return symbols

def run():
    print(f"\n{'='*55}")
    print(f"  200 DMA Breadth Calculator — Nifty 500")
    print(f"{'='*55}\n")

    nifty500 = get_nifty500_symbols()

    print("Loading nifty500_2000days.csv...")
    df = pd.read_csv("nifty500_2000days.csv")
    df["date"]  = pd.to_datetime(df["date"])
    df["close"] = df["close"].astype(float)
    df          = df.drop_duplicates(subset=["symbol", "date"])
    df          = df[df["symbol"].isin(nifty500)]

    print(f"Rows:       {len(df):,}")
    print(f"Symbols:    {df['symbol'].nunique()}")
    print(f"Date range: {df['date'].min().date()} to {df['date'].max().date()}")

    # Calculate 200 SMA per symbol (same as dma_stocks_today.py)
    print("\nCalculating 200 SMA per symbol...")
    all_dates = {}   # date → {above: n, below: n}

    for symbol, grp in df.groupby("symbol"):
        grp           = grp.sort_values("date").copy()
        grp["sma200"] = grp["close"].rolling(200, min_periods=200).mean()
        grp           = grp.dropna(subset=["sma200"])

        for _, row in grp.iterrows():
            dt    = row["date"].date().isoformat()
            above = row["close"] > row["sma200"]

            if dt not in all_dates:
                all_dates[dt] = {"above": 0, "below": 0}

            if above:
                all_dates[dt]["above"] += 1
            else:
                all_dates[dt]["below"] += 1

    # Build results
    results = []
    for dt in sorted(all_dates.keys()):
        above_count = all_dates[dt]["above"]
        below_count = all_dates[dt]["below"]
        total       = above_count + below_count

        if total < 10:
            continue

        results.append({
            "date":         dt,
            "index_name":   "NIFTY 500",
            "above_200dma": above_count,
            "below_200dma": below_count,
            "total_stocks": total,
            "pct_above":    round((above_count / total) * 100, 2)
        })

    print(f"Breadth rows: {len(results)}")

    print(f"\nLatest 5:")
    print(f"{'DATE':<15} {'ABOVE':>8} {'BELOW':>8} {'TOTAL':>8} {'%ABOVE':>8}")
    print("-" * 50)
    for r in results[-5:]:
        print(f"{r['date']:<15} {r['above_200dma']:>8} {r['below_200dma']:>8} {r['total_stocks']:>8} {r['pct_above']:>7}%")

    # Store to Supabase
    print(f"\nStoring {len(results)} rows...")
    stored = 0
    for i in range(0, len(results), 500):
        sb.table("dma_breadth").upsert(
            results[i:i+500],
            on_conflict="date,index_name"
        ).execute()
        stored += len(results[i:i+500])
        print(f"  Stored {stored}/{len(results)}")

    print(f"\nDone. {stored} rows stored.")
    
if __name__ == "__main__":
    print("Starting...")
    run()