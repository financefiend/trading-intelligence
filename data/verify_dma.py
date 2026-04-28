import pandas as pd
import os

def run():
    for f in ["ohlcv_chunk1.csv", "ohlcv_all_500.csv"]:
        if os.path.exists(f):
            df = pd.read_csv(f)
            df = df[df["symbol"] == "RELIANCE"]
            df["date"] = pd.to_datetime(df["date"])
            print(f"\n{f}:")
            print(f"  RELIANCE rows: {len(df)}")
            print(f"  From: {df['date'].min().date()}")
            print(f"  To:   {df['date'].max().date()}")

if __name__ == "__main__":
    run()