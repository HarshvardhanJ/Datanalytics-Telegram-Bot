"""
The data-analyst agent. Given the recent conversation (list of user text messages,
oldest first) it runs a tool-use loop with Claude — web_search + run_python + fetch_url —
until Claude produces a final reply, then extracts a single JSON object from that reply.
"""
import json
import os
import re
import anthropic
from tools import TOOL_SCHEMAS, dispatch_tool
from logger import log_event

MODEL = os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-4-6")
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
   you must answer now; earlier messages are context (e.g. clarifications or the dataset \
   description) for the same task.
4. If you truly cannot determine an exact value after real effort, give your best \
   evidence-based estimate rather than refusing — but only after you've tried tools.
5. Your very final message must be exactly one JSON object matching the requested shape. \
   Nothing else — no "Here is the answer:", no code fences.
"""


def _extract_json_object(text: str) -> dict | None:
    """Pull the first valid top-level JSON object out of a string."""
    text = text.strip()
    # strip common code fences
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip())
    # try straightforward parse first
    try:
        return json.loads(text)
    except Exception:
        pass
    # fall back: find balanced {...} spans and try each
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


def run_agent(chat_id: int, messages_history: list[str], run_id: str) -> dict:
    """
    messages_history: list of prior user texts in this chat, oldest first, last one
    being the current question to answer.
    Returns the parsed final answer JSON object (the shape the user asked for).
    """
    client = anthropic.Anthropic()

    convo = [{"role": "user", "content": messages_history[-1]}]
    if len(messages_history) > 1:
        context_blurb = "\n\n".join(
            f"[earlier message {i+1}]: {m}" for i, m in enumerate(messages_history[:-1])
        )
        convo[0]["content"] = (
            f"Conversation so far (for context only):\n{context_blurb}\n\n"
            f"[current message to answer]: {messages_history[-1]}"
        )

    log_event({"run_id": run_id, "chat_id": chat_id, "event": "start",
               "input": convo[0]["content"]})

    tools = TOOL_SCHEMAS  # includes free web_search (DuckDuckGo), run_python, fetch_url

    final_text = ""
    for iteration in range(MAX_TOOL_ITERS):
        resp = client.messages.create(
            model=MODEL,
            max_tokens=2000,
            system=SYSTEM_PROMPT,
            tools=tools,
            messages=convo,
        )

        log_event({"run_id": run_id, "chat_id": chat_id, "event": "model_response",
                   "iteration": iteration, "stop_reason": resp.stop_reason,
                   "content": [b.model_dump() for b in resp.content]})

        # collect any text blocks (in case this is the final answer)
        text_blocks = [b.text for b in resp.content if b.type == "text"]
        final_text = "\n".join(text_blocks).strip()

        # only client-side tools (run_python, fetch_url) need dispatching here;
        # web_search is a server tool Anthropic executes and resolves within the
        # same response, so it never shows up as a "tool_use" block to handle.
        tool_uses = [b for b in resp.content if b.type == "tool_use"]

        if not tool_uses:
            # model is done (either finished, or only used server-side web_search)
            break

        convo.append({"role": "assistant", "content": resp.content})

        tool_results = []
        for tu in tool_uses:
            result_text = dispatch_tool(tu.name, tu.input)
            log_event({"run_id": run_id, "chat_id": chat_id, "event": "tool_call",
                       "iteration": iteration, "tool": tu.name, "input": tu.input,
                       "output": result_text[:2000]})
            tool_results.append({
                "type": "tool_result",
                "tool_use_id": tu.id,
                "content": result_text,
            })

        convo.append({"role": "user", "content": tool_results})

    parsed = _extract_json_object(final_text)
    log_event({"run_id": run_id, "chat_id": chat_id, "event": "final",
               "raw_text": final_text, "parsed": parsed})

    if parsed is None:
        # last-resort fallback so the bot always replies with *some* JSON
        parsed = {"answer": final_text or "could not determine answer"}

    return parsed
