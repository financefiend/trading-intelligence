import requests
import os
from dotenv import load_dotenv

load_dotenv()

def update():
    token  = os.getenv("KITE_ACCESS_TOKEN")
    secret = os.getenv("UPDATE_SECRET")
    url    = "https://trading-intelligence-production.up.railway.app/update-token"

    if not token:
        print("ERROR: KITE_ACCESS_TOKEN not in .env")
        return

    if not secret:
        print("ERROR: UPDATE_SECRET not in .env")
        return

    r = requests.post(url, params={"token": token, "secret": secret})
    print(f"Status:   {r.status_code}")
    print(f"Response: {r.json()}")

if __name__ == "__main__":
    update()