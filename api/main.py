from fastapi import FastAPI
from supabase import create_client
import os
from dotenv import load_dotenv
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from datetime import datetime, timedelta
import os

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

@app.post("/update-token")
def update_token(token: str, secret: str):
    if secret != os.getenv("UPDATE_SECRET"):
        raise HTTPException(status_code=403, detail="Invalid secret")
    os.environ["KITE_ACCESS_TOKEN"] = token
    supabase.table("kite_session").insert({
        "access_token": token,
        "is_valid":     True,
        "expires_at":   (datetime.now() + timedelta(hours=20)).isoformat()
    }).execute()
    return {"status": "token updated successfully"}

@app.post("/run/daily-update")
def trigger_daily_update():
    import subprocess
    try:
        subprocess.Popen(["python", "data/daily_update.py"])
        return {"status": "started", "job": "daily_update"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    
    