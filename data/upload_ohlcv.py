import pandas as pd
from supabase import create_client
import os
from dotenv import load_dotenv

load_dotenv()
sb = create_client(os.getenv("SUPABASE_URL"), os.getenv("SUPABASE_KEY"))

def run():
    print("Loading CSV...")
    df = pd.read_csv("nifty500_2000days.csv")
 
    # Rename date → ts to match Supabase schema
    df = df.rename(columns={"date": "ts"})

    # Add exchange column
    df["exchange"] = "NSE"

    total = len(df)
    print(f"Total rows to upload: {total:,}")

    rows    = df.to_dict("records")
    stored  = 0
    errors  = 0
    chunk   = 500

    for i in range(0, total, chunk):
        batch = rows[i:i+chunk]
        try:
            sb.table("ohlcv").upsert(
                batch,
                on_conflict="symbol,timeframe,ts"
            ).execute()
            stored += len(batch)
            print(f"  Uploaded {stored:,}/{total:,}")
        except Exception as e:
            print(f"  ERROR at chunk {i}: {e}")
            errors += 1

    print(f"\n{'='*50}")
    print(f"  Done. Stored: {stored:,}")
    print(f"  Errors: {errors}")
    print(f"{'='*50}")

if __name__ == "__main__":
    print("Starting...")
    run()