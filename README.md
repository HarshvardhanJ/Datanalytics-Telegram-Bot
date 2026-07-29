# Data-Analyst Telegram Bot

An LLM agent, wired up as a Telegram bot, that answers data-analysis questions
(MOSPI and similar public datasets) and replies with a single JSON object:

```json
{"answer": <shape the question asked for>, "log_url": "https://your-host/logs/run.jsonl"}
```

## LLM backend — free by default

`LLM_PROVIDER` picks the backend (`agent.py` just dispatches to one of these):

- **`gemini` (default, free, no credit card)** — `agent_gemini.py`, using
  Google's Gemini API free tier (Gemini 2.5 Flash). Get a free key at
  https://aistudio.google.com/apikey. Free tier: no card required, function
  calling included, ~15 requests/min and up to ~1,500 requests/day — plenty
  for a grading run. Gemini's *built-in* Google Search grounding tool is
  **not** free ($14-35 per 1,000 queries), so instead the agent gets its own
  free `web_search` tool backed by DuckDuckGo (no key needed).
- **`anthropic` (paid)** — `agent_anthropic.py`, using Claude, if you'd rather
  pay for a Console API key.

Set `LLM_PROVIDER=gemini` and `GEMINI_API_KEY=...` in your `.env` / host env
vars, and you're done — no billing account needed anywhere in the stack.

## How it works

- **`app.py`** — FastAPI server. Exposes `POST /webhook` (Telegram sends messages
  here) and `GET /logs/run.jsonl` (serves the run log publicly).
- **`agent_gemini.py` / `agent_anthropic.py`** — the actual analyst. Runs a
  tool-use loop with:
  - `web_search` — free, DuckDuckGo-backed — to find the right MOSPI page /
    dataset / URL.
  - `run_python` — executes python (pandas/numpy/httpx preloaded) so the agent
    can `pd.read_csv(url)` and actually compute answers instead of guessing.
  - `fetch_url` — grabs raw HTML/CSV/JSON to inspect before parsing.
  Once the model has a final answer, we extract the JSON object from its last
  message (robust to code fences / stray text).
- **`tools.py`** — the sandboxed tool implementations, shared by both backends.
- **`logger.py`** — appends one JSON line per event (start, each tool call,
  final answer, reply sent) to `logs/run.jsonl`.
- Conversation history: the bot keeps the last 10 messages per chat in memory
  so multi-turn questions have context; it always answers the most recent
  message.

## 1. Local setup

```bash
git clone <your-repo-url>
cd telegram-data-analyst-bot
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # fill in the real values
```

You need:
- `TELEGRAM_BOT_TOKEN` — from [@BotFather](https://t.me/BotFather): `/newbot`,
  pick a name ending in `bot`.
- `GEMINI_API_KEY` — free, no card, from https://aistudio.google.com/apikey
  (or `ANTHROPIC_API_KEY` + `LLM_PROVIDER=anthropic` if you'd rather pay for Claude).
- `PUBLIC_LOG_URL` — the public URL your log will live at once deployed
  (see step 3); must match `<your-host>/logs/run.jsonl`.

Run it locally:

```bash
export $(cat .env | xargs)
uvicorn app:app --reload --port 8000
```

To receive real Telegram messages locally you need a public tunnel, e.g.:

```bash
ngrok http 8000
python set_webhook.py https://<your-ngrok-id>.ngrok-free.app/webhook
```

Then message your bot on Telegram and watch the terminal / `logs/run.jsonl`.

## 2. Test against the grading harness

Clone the grading repo and point it at your bot per its README:
https://github.com/Jivraj-18/tds-p1-t2-2026-telegram-bot

Add your own questions to `evals/questions.json` there to sanity-check before
the real grading run.

## 3. Deploy (Render.com, free tier — swap for Railway/Fly.io if you prefer)

1. Push this repo to GitHub (public).
2. On [render.com](https://render.com) → **New +** → **Web Service** → connect
   your repo.
3. Environment: **Docker** (it will pick up the `Dockerfile` automatically).
4. Add environment variables in the Render dashboard:
   - `TELEGRAM_BOT_TOKEN`
   - `LLM_PROVIDER=gemini`
   - `GEMINI_API_KEY` (free key from https://aistudio.google.com/apikey)
   - `TELEGRAM_WEBHOOK_SECRET` (optional but recommended, any random string)
   - `PUBLIC_LOG_URL` = `https://<your-render-service>.onrender.com/logs/run.jsonl`
5. Deploy. Note the resulting service URL.
6. Register the webhook so Telegram forwards messages to you:
   ```bash
   TELEGRAM_BOT_TOKEN=... python set_webhook.py \
     https://<your-render-service>.onrender.com/webhook \
     <TELEGRAM_WEBHOOK_SECRET>
   ```
7. Message your bot on Telegram to confirm it replies with JSON, and check
   `https://<your-render-service>.onrender.com/logs/run.jsonl` loads with `wget`.

**Free-tier caveat:** Render's free web services spin down when idle and take
~30-60s to wake on the first request after inactivity, which can cause the
grader's first message to time out. Options: pick a low-cost always-on plan,
use a different always-on host (Railway, Fly.io, a small VPS), or add an
external uptime pinger (e.g. cron-job.org hitting `/` every 10 min) to keep it
warm during the grading window.

## 4. Registering your bot for grading

Submit, comma-separated:

```
https://github.com/<you>/telegram-data-analyst-bot, your_bot_username_bot
```

## Notes / design choices

- The log endpoint always exists (`GET /logs/run.jsonl`) even before any
  message has been processed, so `log_url` is `wget`-able immediately after
  deploy.
- `run_python`'s output is truncated to keep tool-result payloads small; the
  agent is instructed to `print()` only what it needs.
- If Claude's final reply isn't parseable JSON for any reason, the bot still
  replies with `{"answer": <raw text or error>, "log_url": ...}` rather than
  crashing, so you always get a scoreable (if occasionally wrong) response.
- `agent.py`'s `_extract_json_object` handles stray prose/code fences around
  the JSON, since models don't always follow "ONLY JSON" perfectly.
