from fastapi import FastAPI
from supabase import create_client
import os
from dotenv import load_dotenv

load_dotenv()

app = FastAPI(title="Trading Intelligence API")
supabase = create_client(os.getenv("SUPABASE_URL"), os.getenv("SUPABASE_KEY"))

@app.get("/")
def root():
    return {"status": "running", "service": "Trading Intelligence Platform"}

@app.get("/health")
def health():
    return {"status": "ok"}

@app.get("/api/news")
def get_news(limit: int = 40):
    result = supabase.table("news_articles")\
        .select("*")\
        .order("fetched_at", desc=True)\
        .limit(limit)\
        .execute()
    return result.data

@app.get("/api/dma-breadth")
def get_dma_breadth(index_name: str = "NIFTY 500", days: int = 365):
    from datetime import date, timedelta
    cutoff = (date.today() - timedelta(days=days)).isoformat()
    result = supabase.table("dma_breadth")\
        .select("date,above_200dma,below_200dma,total_stocks,pct_above")\
        .eq("index_name", index_name)\
        .gte("date", cutoff)\
        .order("date")\
        .execute()
    return result.data