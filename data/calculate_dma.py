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
    print("Loading CSV files...")
    nifty500 = get_nifty500_symbols()

    dfs = []
    for fname in ["nifty500_2000days.csv"]:
        if os.path.exists(fname):
            print(f"  Loading {fname}...")
            dfs.append(pd.read_csv(fname))
        else:
            print(f"  Not found: {fname}")

    if not dfs:
        print("No CSV files found!")
        return

    df = pd.concat(dfs, ignore_index=True)
    df["date"]  = pd.to_datetime(df["date"])
    df["close"] = df["close"].astype(float)
    df          = df.drop_duplicates(subset=["symbol", "date"])
    df          = df[df["symbol"].isin(nifty500)]

    print(f"Rows:       {len(df):,}")
    print(f"Symbols:    {df['symbol'].nunique()}")
    print(f"Date range: {df['date'].min().date()} to {df['date'].max().date()}")

    print("\nPivoting...")
    pivot  = df.pivot_table(index="date", columns="symbol", values="close")
    dma200 = pivot.rolling(window=200, min_periods=100).mean()
    above  = (pivot > dma200)

    print("Building breadth results...")
    results = []
    for dt in above.index:
        row         = above.loc[dt].dropna()
        above_count = int(row.sum())
        below_count = int((~row).sum())
        total       = above_count + below_count
        if total < 10:
            continue
        results.append({
            "date":         dt.date().isoformat(),
            "index_name":   "NIFTY 500",
            "above_200dma": above_count,
            "below_200dma": below_count,
            "total_stocks": total,
            "pct_above":    round((above_count / total) * 100, 2)
        })

    print(f"Breadth rows: {len(results)}")

    print(f"\nOldest 5:")
    for r in results[:5]:
        print(f"  {r['date']}  above={r['above_200dma']}  {r['pct_above']}%")

    print(f"\nLatest 5:")
    for r in results[-5:]:
        print(f"  {r['date']}  above={r['above_200dma']}  {r['pct_above']}%")

    print(f"\nStoring to Supabase...")
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