"""
Agent backed by AIPipe (https://aipipe.org) — an OpenAI-compatible proxy in front
of OpenRouter, using course-provided credits instead of a personal API key.
Same interface as agent_anthropic.run_agent / agent_gemini.run_agent.

AIPipe's endpoint speaks the standard OpenAI Chat Completions API, so this uses
plain OpenAI-style function calling — no custom thought-signature bookkeeping
required (unlike Gemini 3), and no separate paid key required (unlike Anthropic).
"""
import json
import os
import re

import openai
from openai import OpenAI

from tools import OPENAI_TOOL_SCHEMAS, dispatch_tool
from logger import log_event

# Default to a *free* OpenRouter model — ":free" variants are rate-limited, not
# billed, so they sidestep the credit/402 issues paid routes can hit through a
# shared course token. "openrouter/free" is OpenRouter's own auto-router: it
# picks a free model that supports whatever capabilities the request needs
# (here: tool calling), so we don't hardcode one specific free model ID that
# might get rotated out later.
MODEL = os.environ.get("AIPIPE_MODEL", "openrouter/free")

# If the primary model 402s / errors, try these free, tool-calling-capable
# models in order before giving up.
FALLBACK_MODELS = [
    "qwen/qwen3-coder:free",
    "meta-llama/llama-3.3-70b-instruct:free",
    "z-ai/glm-4.5-air:free",
]
MAX_TOOL_ITERS = 12

SYSTEM_PROMPT = """\
You are a meticulous data analyst answering questions sent over Telegram, many of \
which reference MOSPI (Ministry of Statistics and Programme Implementation, India) \
or other public datasets.

Rules:
1. The user's message tells you EXACTLY what JSON shape to reply with (it will say \
   something like: Reply with ONLY this JSON object and nothing else: \
   {"answer": {"state": "<state name>"}, "log_url": "..."}). Figure out the real \
   answer using your tools, then reply with ONLY that JSON object, with the "answer" \
   key filled in using the exact shape requested (same nested keys/types). You do NOT \
   need to fill in a real "log_url" — a placeholder there is fine, it gets replaced \
   automatically. No markdown fences, no explanation, no extra text before or after \
   the JSON object.
2. Use run_python (pandas/numpy/httpx preloaded) and fetch_url to actually fetch and \
   compute from real data whenever a question depends on a dataset. Do not guess \
   numeric or factual answers you can instead compute. Use web_search to locate the \
   right MOSPI page/dataset/URL first if you don't already know it.
3. If the conversation has several messages, only the LAST user message is the question \
   you must answer now; earlier messages are context for the same task.
4. If you truly cannot determine an exact value after real effort, give your best \
   evidence-based estimate rather than refusing — but only after you've tried tools.
5. Your very final message must be exactly one JSON object matching the requested shape. \
   Nothing else — no "Here is the answer:", no code fences.
"""


def _extract_json_object(text: str) -> dict | None:
    text = text.strip()
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip())
    try:
        return json.loads(text)
    except Exception:
        pass
    start_idxs = [i for i, c in enumerate(text) if c == "{"]
    for start in start_idxs:
        depth = 0
        for i in range(start, len(text)):
            if text[i] == "{":
                depth += 1
            elif text[i] == "}":
                depth -= 1
                if depth == 0:
                    candidate = text[start:i + 1]
                    try:
                        return json.loads(candidate)
                    except Exception:
                        break
    return None


def _create_with_fallback(client, messages, run_id, chat_id, state):
    """Call chat.completions.create, falling back through FALLBACK_MODELS on
    payment/credit errors (402) or model-not-found errors. Remembers whichever
    model worked (in `state`) so later iterations in the same run don't re-try
    ones we already know are broken."""
    candidates = [state["model"]] + [m for m in FALLBACK_MODELS if m != state["model"]]
    last_err = None
    for model in candidates:
        try:
            resp = client.chat.completions.create(
                model=model,
                messages=messages,
                tools=OPENAI_TOOL_SCHEMAS,
                max_tokens=1500,
            )
            if model != state["model"]:
                log_event({"run_id": run_id, "chat_id": chat_id, "event": "model_fallback",
                           "from": state["model"], "to": model})
                state["model"] = model
            return resp
        except (openai.APIStatusError, openai.NotFoundError) as e:
            last_err = e
            log_event({"run_id": run_id, "chat_id": chat_id, "event": "model_error",
                       "model": model, "error": str(e)})
            continue
    raise last_err


def run_agent(chat_id: int, messages_history: list[str], run_id: str) -> dict:
    client = OpenAI(
        api_key=os.environ["AIPIPE_TOKEN"],
        base_url="https://aipipe.org/openrouter/v1",
    )

    question = messages_history[-1]
    if len(messages_history) > 1:
        context_blurb = "\n\n".join(
            f"[earlier message {i+1}]: {m}" for i, m in enumerate(messages_history[:-1])
        )
        question = (
            f"Conversation so far (for context only):\n{context_blurb}\n\n"
            f"[current message to answer]: {messages_history[-1]}"
        )

    log_event({"run_id": run_id, "chat_id": chat_id, "event": "start", "input": question})

    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": question},
    ]

    state = {"model": MODEL}
    final_text = ""
    for iteration in range(MAX_TOOL_ITERS):
        resp = _create_with_fallback(client, messages, run_id, chat_id, state)
        msg = resp.choices[0].message
        final_text = (msg.content or "").strip()

        log_event({"run_id": run_id, "chat_id": chat_id, "event": "model_response",
                   "iteration": iteration, "model": state["model"],
                   "has_tool_calls": bool(msg.tool_calls), "text": final_text})

        if not msg.tool_calls:
            break

        messages.append({
            "role": "assistant",
            "content": msg.content,
            "tool_calls": [tc.model_dump() for tc in msg.tool_calls],
        })

        for tc in msg.tool_calls:
            try:
                args = json.loads(tc.function.arguments or "{}")
            except Exception:
                args = {}
            result_text = dispatch_tool(tc.function.name, args)
            log_event({"run_id": run_id, "chat_id": chat_id, "event": "tool_call",
                       "iteration": iteration, "tool": tc.function.name, "input": args,
                       "output": result_text[:2000]})
            messages.append({
                "role": "tool",
                "tool_call_id": tc.id,
                "content": result_text,
            })

    parsed = _extract_json_object(final_text)
    log_event({"run_id": run_id, "chat_id": chat_id, "event": "final",
               "raw_text": final_text, "parsed": parsed})

    if parsed is None:
        parsed = {"answer": final_text or "could not determine answer"}

    return parsed
