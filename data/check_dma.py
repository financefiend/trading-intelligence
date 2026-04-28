from supabase import create_client
import os
from dotenv import load_dotenv
load_dotenv()

sb = create_client(os.getenv("SUPABASE_URL"), os.getenv("SUPABASE_KEY"))

# Check total rows
r = sb.table("dma_breadth").select("id", count="exact").execute()
print(f"Total dma_breadth rows: {r.count}")

# Check oldest dates
r2 = sb.table("dma_breadth")\
    .select("date,above_200dma,below_200dma,total_stocks,pct_above")\
    .eq("index_name", "NIFTY 500")\
    .order("date", desc=False)\
    .limit(10)\
    .execute()

print(f"\n{'DATE':<15} {'ABOVE':>8} {'BELOW':>8} {'TOTAL':>8} {'%ABOVE':>8}")
print("-" * 50)
for row in r2.data:
    print(f"{row['date']:<15} {row['above_200dma']:>8} {row['below_200dma']:>8} {row['total_stocks']:>8} {row['pct_above']:>7}%")