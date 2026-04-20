import feedparser
import hashlib
import requests
from supabase import create_client
from datetime import datetime
import os
from dotenv import load_dotenv

load_dotenv()

supabase = create_client(os.getenv("SUPABASE_URL"), os.getenv("SUPABASE_KEY"))

RSS_FEEDS = {
    "Economic Times": "https://economictimes.indiatimes.com/markets/rssfeeds/1977021501.cms",
    "Moneycontrol":   "https://www.moneycontrol.com/rss/results.xml",
    "Business Standard": "https://www.business-standard.com/rss/markets-106.rss",
    "LiveMint":       "https://www.livemint.com/rss/markets"
}

KEYWORDS = [
    "nse", "bse", "sensex", "nifty", "rbi", "sebi",
    "earnings", "results", "quarterly", "revenue",
    "crude", "tanker", "import", "export", "gdp",
    "rate", "inflation", "repo", "monetary policy"
]

def make_hash(text):
    return hashlib.md5(text.encode()).hexdigest()

def scrape_feeds():
    total_new = 0

    for source_name, feed_url in RSS_FEEDS.items():
        try:
            feed = feedparser.parse(feed_url)
            print(f"  {source_name}: {len(feed.entries)} articles found")

            for entry in feed.entries[:20]:
                headline = entry.get("title", "").strip()
                url      = entry.get("link",  "")

                if not headline:
                    continue

                article_hash = make_hash(headline + url)

                existing = supabase.table("news_articles")\
                    .select("id")\
                    .eq("article_hash", article_hash)\
                    .execute()

                if existing.data:
                    continue

                headline_lower  = headline.lower()
                found_keywords  = [k for k in KEYWORDS if k in headline_lower]

                published = None
                if hasattr(entry, "published_parsed") and entry.published_parsed:
                    try:
                        published = datetime(*entry.published_parsed[:6]).isoformat()
                    except:
                        pass

                supabase.table("news_articles").insert({
                    "source":       source_name,
                    "headline":     headline,
                    "url":          url,
                    "article_hash": article_hash,
                    "category":     "markets",
                    "published_at": published,
                    "keywords":     found_keywords
                }).execute()

                total_new += 1

        except Exception as e:
            print(f"  ERROR {source_name}: {e}")

            supabase.table("job_logs").insert({
                "job_name": "news_scraper",
                "status":   "error",
                "message":  str(e)
            }).execute()

    print(f"\n  Total new articles stored: {total_new}")

    supabase.table("job_logs").insert({
        "job_name": "news_scraper",
        "status":   "success",
        "message":  f"{total_new} new articles"
    }).execute()

if __name__ == "__main__":
    print(f"News scraper starting — {datetime.now().strftime('%H:%M')}")
    scrape_feeds()