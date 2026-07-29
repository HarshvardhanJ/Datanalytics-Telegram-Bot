import os
import uuid
import json
import logging
from collections import defaultdict, deque

import httpx
from fastapi import FastAPI, Request
from fastapi.responses import PlainTextResponse, FileResponse

from agent import run_agent
from logger import log_event, LOG_PATH

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("bot")

TELEGRAM_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
TELEGRAM_API = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}"
PUBLIC_LOG_URL = os.environ["PUBLIC_LOG_URL"]  # e.g. https://your-host/logs/run.jsonl
WEBHOOK_SECRET = os.environ.get("TELEGRAM_WEBHOOK_SECRET", "")

app = FastAPI()

# short rolling history per chat, so multi-turn questions have context
HISTORY: dict[int, deque] = defaultdict(lambda: deque(maxlen=10))


def send_telegram_message(chat_id: int, text: str):
    with httpx.Client(timeout=30) as client:
        client.post(f"{TELEGRAM_API}/sendMessage", json={
            "chat_id": chat_id,
            "text": text,
        })


@app.get("/")
def health():
    return {"status": "ok"}


@app.get("/logs/run.jsonl")
def get_log():
    if not os.path.exists(LOG_PATH):
        open(LOG_PATH, "a").close()
    return FileResponse(LOG_PATH, media_type="application/jsonl")


@app.post("/webhook")
async def webhook(request: Request):
    if WEBHOOK_SECRET:
        if request.headers.get("X-Telegram-Bot-Api-Secret-Token") != WEBHOOK_SECRET:
            return PlainTextResponse("forbidden", status_code=403)

    update = await request.json()
    message = update.get("message") or update.get("edited_message")
    if not message or "text" not in message:
        return {"ok": True}

    chat_id = message["chat"]["id"]
    text = message["text"]
    run_id = str(uuid.uuid4())

    HISTORY[chat_id].append(text)
    history_list = list(HISTORY[chat_id])

    log.info("chat=%s run=%s incoming=%r", chat_id, run_id, text[:200])

    try:
        answer_obj = run_agent(chat_id, history_list, run_id)
    except Exception as e:
        log.exception("agent failed")
        answer_obj = {"answer": None, "error": str(e)}
        log_event({"run_id": run_id, "chat_id": chat_id, "event": "error",
                   "error": str(e)})

    if isinstance(answer_obj, dict) and "answer" in answer_obj:
        reply = {**answer_obj, "log_url": PUBLIC_LOG_URL}
    else:
        reply = {"answer": answer_obj, "log_url": PUBLIC_LOG_URL}

    reply_text = json.dumps(reply, ensure_ascii=False)
    log_event({"run_id": run_id, "chat_id": chat_id, "event": "reply_sent",
               "reply": reply})
    send_telegram_message(chat_id, reply_text)

    return {"ok": True}
