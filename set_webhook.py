"""
Run once after deploying, to point Telegram at your bot:

    TELEGRAM_BOT_TOKEN=... python set_webhook.py https://your-app.onrender.com/webhook [secret]
"""
import sys
import os
import httpx

token = os.environ["TELEGRAM_BOT_TOKEN"]
url = sys.argv[1]
secret = sys.argv[2] if len(sys.argv) > 2 else None

payload = {"url": url}
if secret:
    payload["secret_token"] = secret

r = httpx.post(f"https://api.telegram.org/bot{token}/setWebhook", json=payload)
print(r.status_code, r.text)

r2 = httpx.get(f"https://api.telegram.org/bot{token}/getWebhookInfo")
print(r2.status_code, r2.text)
