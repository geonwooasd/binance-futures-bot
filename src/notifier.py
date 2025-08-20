import os, json, urllib.request
from dotenv import load_dotenv
load_dotenv()
WEBHOOK = os.getenv("DISCORD_WEBHOOK")

def notify(msg: str):
    print(msg)
    if not WEBHOOK:
        return
    try:
        data = json.dumps({"content": msg}).encode("utf-8")
        req = urllib.request.Request(WEBHOOK, data=data, headers={"Content-Type":"application/json"})
        urllib.request.urlopen(req, timeout=5)
    except Exception as e:
        print(f"[notify error] {e}")
