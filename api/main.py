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