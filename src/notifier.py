import os, json, urllib.request, urllib.error
from dotenv import load_dotenv

load_dotenv()
WEBHOOK = os.getenv("DISCORD_WEBHOOK")

UA = "Mozilla/5.0 (compatible; trading-bot/1.0; +https://github.com/geonwooasd/binance-futures-bot)"

def _post(url: str, payload: dict):
    if not url:
        print("[notify] no webhook configured")
        return
    sep = "&" if "?" in url else "?"
    target = f"{url}{sep}wait=true"
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        target,
        data=data,
        headers={"Content-Type": "application/json", "User-Agent": UA},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=8) as r:
            if r.status not in (200, 204):
                print(f"[notify warn] status {r.status}")
    except urllib.error.HTTPError as e:
        try:
            body = e.read().decode("utf-8", "ignore")
        except Exception:
            body = ""
        print(f"[notify error] HTTP {e.code}: {body[:300]}")
    except Exception as e:
        print(f"[notify error] {e}")

def notify(msg: str):
    print(msg)
    _post(WEBHOOK, {"content": msg})
