import pandas as pd
import os
from supabase import create_client
from dotenv import load_dotenv

load_dotenv()
sb = create_client(os.getenv("SUPABASE_URL"), os.getenv("SUPABASE_KEY"))

def run():
    # Load fresh data
    print("Loading nifty500_2000days.csv...")
    df = pd.read_csv("nifty500_2000days.csv")
    df["date"]  = pd.to_datetime(df["date"])
    df["close"] = df["close"].astype(float)
    df          = df.drop_duplicates(subset=["symbol","date"])

    # Get Nifty 500 symbols
    r = sb.table("index_composition")\
        .select("symbol,company_name")\
        .eq("index_name", "NIFTY 500")\
        .eq("is_current", True)\
        .execute()
    nifty500   = {row["symbol"]: row["company_name"] for row in r.data}
    df         = df[df["symbol"].isin(nifty500)]

    # Calculate 200 SMA per stock
    print("Calculating 200 SMA...")
    results = []

    for symbol, grp in df.groupby("symbol"):
        grp         = grp.sort_values("date").copy()
        grp["sma200"] = grp["close"].rolling(200, min_periods=200).mean()
        latest      = grp.iloc[-1]

        if pd.isna(latest["sma200"]):
            continue

        above    = latest["close"] > latest["sma200"]
        diff_pct = round((latest["close"] - latest["sma200"]) / latest["sma200"] * 100, 2)

        results.append({
            "symbol":       symbol,
            "company":      nifty500.get(symbol, ""),
            "date":         str(latest["date"])[:10],
            "close":        round(latest["close"], 2),
            "sma200":       round(latest["sma200"], 2),
            "diff_pct":     diff_pct,
            "status":       "ABOVE" if above else "BELOW"
        })

    df_result = pd.DataFrame(results)
    above_df  = df_result[df_result["status"] == "ABOVE"].sort_values("diff_pct", ascending=False)
    below_df  = df_result[df_result["status"] == "BELOW"].sort_values("diff_pct")

    print(f"\nTotal stocks: {len(df_result)}")
    print(f"Above SMA200: {len(above_df)}")
    print(f"Below SMA200: {len(below_df)}")

    print(f"\nTop 20 ABOVE SMA200:")
    print(f"{'SYMBOL':<15} {'CLOSE':>8} {'SMA200':>8} {'DIFF%':>8}  COMPANY")
    print("-" * 70)
    for _, r in above_df.head(20).iterrows():
        print(f"{r['symbol']:<15} {r['close']:>8} {r['sma200']:>8} {r['diff_pct']:>7}%  {r['company'][:30]}")

    print(f"\nTop 20 BELOW SMA200:")
    print(f"{'SYMBOL':<15} {'CLOSE':>8} {'SMA200':>8} {'DIFF%':>8}  COMPANY")
    print("-" * 70)
    for _, r in below_df.head(20).iterrows():
        print(f"{r['symbol']:<15} {r['close']:>8} {r['sma200']:>8} {r['diff_pct']:>7}%  {r['company'][:30]}")

    # Save to Excel
    with pd.ExcelWriter("dma_stocks_today.xlsx") as writer:
        above_df.to_excel(writer, sheet_name="Above SMA200", index=False)
        below_df.to_excel(writer, sheet_name="Below SMA200", index=False)

    print(f"\nSaved to dma_stocks_today.xlsx")
    print(f"  Sheet 1: Above SMA200 ({len(above_df)} stocks)")
    print(f"  Sheet 2: Below SMA200 ({len(below_df)} stocks)")

if __name__ == "__main__":
    run()