"""Append-only JSONL run logger. One JSON object per line, served publicly via app.py."""
import json
import os
import threading
from datetime import datetime, timezone

LOG_PATH = os.environ.get("LOG_PATH", "logs/run.jsonl")
_lock = threading.Lock()

os.makedirs(os.path.dirname(LOG_PATH) or ".", exist_ok=True)


def log_event(event: dict):
    event = {"ts": datetime.now(timezone.utc).isoformat(), **event}
    line = json.dumps(event, ensure_ascii=False, default=str)
    with _lock:
        with open(LOG_PATH, "a", encoding="utf-8") as f:
            f.write(line + "\n")
