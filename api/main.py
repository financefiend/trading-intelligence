from fastapi import FastAPI
from supabase import create_client
import os
from dotenv import load_dotenv
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

load_dotenv()

app = FastAPI(title="Trading Intelligence API")
app.mount("/dashboards", StaticFiles(directory="dashboards"), name="dashboards")
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
def get_dma_breadth(index_name: str = "NIFTY 500"):
    all_rows = []
    offset   = 0
    limit    = 1000

    while True:
        result = supabase.table("dma_breadth")\
            .select("date,above_200dma,below_200dma,total_stocks,pct_above")\
            .eq("index_name", index_name)\
            .order("date", desc=True)\
            .range(offset, offset + limit - 1)\
            .execute()

        if not result.data:
            break

        all_rows.extend(result.data)
        offset += limit

        if len(result.data) < limit:
            break

    # Reverse so chart goes oldest → newest left to right
    return list(reversed(all_rows))

@app.get("/dashboard")
def dashboard():
    return FileResponse("dashboards/index.html")