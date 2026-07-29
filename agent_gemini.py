"""
Free-tier data-analyst agent using Google's Gemini API (no credit card required).
Same interface as agent_anthropic.run_agent so app.py can pick either backend.

Uses:
- Gemini 2.5 Flash (free tier: no card, function calling included)
- our own free tools: web_search (DuckDuckGo), run_python, fetch_url
  (Gemini's built-in Google Search grounding tool is NOT free, so we don't use it)
"""
import json
import os
import re

from google import genai
from google.genai import types

from tools import TOOL_SCHEMAS, dispatch_tool
from logger import log_event

MODEL = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")
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

# Translate our Anthropic-style tool schemas into Gemini FunctionDeclaration objects.
def _to_gemini_tools():
    decls = []
    for t in TOOL_SCHEMAS:
        decls.append(types.FunctionDeclaration(
            name=t["name"],
            description=t["description"],
            parameters=t["input_schema"],
        ))
    return [types.Tool(function_declarations=decls)]


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


def run_agent(chat_id: int, messages_history: list[str], run_id: str) -> dict:
    client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])

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

    tools = _to_gemini_tools()
    config = types.GenerateContentConfig(
        system_instruction=SYSTEM_PROMPT,
        tools=tools,
        automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
    )
    # Use the chat session (not raw generate_content) so the SDK manages conversation
    # history — including Gemini 3's mandatory thought_signature bookkeeping — for us,
    # instead of us hand-rolling `contents` and risking dropped signatures.
    chat = client.chats.create(model=MODEL, config=config)

    next_message = [types.Part.from_text(text=question)]
    final_text = ""
    for iteration in range(MAX_TOOL_ITERS):
        resp = chat.send_message(next_message)

        candidate = resp.candidates[0] if resp.candidates else None
        parts = candidate.content.parts if candidate and candidate.content else []
        func_calls = [p.function_call for p in parts if getattr(p, "function_call", None)]
        text_parts = [p.text for p in parts if getattr(p, "text", None)]
        final_text = "\n".join(text_parts).strip()

        log_event({"run_id": run_id, "chat_id": chat_id, "event": "model_response",
                   "iteration": iteration, "has_function_calls": bool(func_calls),
                   "text": final_text})

        if not func_calls:
            break

        response_parts = []
        for fc in func_calls:
            result_text = dispatch_tool(fc.name, dict(fc.args or {}))
            log_event({"run_id": run_id, "chat_id": chat_id, "event": "tool_call",
                       "iteration": iteration, "tool": fc.name, "input": dict(fc.args or {}),
                       "output": result_text[:2000]})
            response_parts.append(types.Part.from_function_response(
                name=fc.name, response={"result": result_text}
            ))
        next_message = response_parts

    parsed = _extract_json_object(final_text)
    log_event({"run_id": run_id, "chat_id": chat_id, "event": "final",
               "raw_text": final_text, "parsed": parsed})

    if parsed is None:
        parsed = {"answer": final_text or "could not determine answer"}

    return parsed
"""
Free-tier data-analyst agent using Google's Gemini API (no credit card required).
Same interface as agent_anthropic.run_agent so app.py can pick either backend.

Uses:
- Gemini 2.5 Flash (free tier: no card, function calling included)
- our own free tools: web_search (DuckDuckGo), run_python, fetch_url
  (Gemini's built-in Google Search grounding tool is NOT free, so we don't use it)
"""
import json
import os
import re

from google import genai
from google.genai import types

from tools import TOOL_SCHEMAS, dispatch_tool
from logger import log_event

MODEL = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")
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

# Translate our Anthropic-style tool schemas into Gemini FunctionDeclaration objects.
def _to_gemini_tools():
    decls = []
    for t in TOOL_SCHEMAS:
        decls.append(types.FunctionDeclaration(
            name=t["name"],
            description=t["description"],
            parameters=t["input_schema"],
        ))
    return [types.Tool(function_declarations=decls)]


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


def run_agent(chat_id: int, messages_history: list[str], run_id: str) -> dict:
    client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])

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

    contents = [types.Content(role="user", parts=[types.Part.from_text(text=question)])]
    tools = _to_gemini_tools()
    config = types.GenerateContentConfig(
        system_instruction=SYSTEM_PROMPT,
        tools=tools,
        automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
    )

    final_text = ""
    for iteration in range(MAX_TOOL_ITERS):
        resp = client.models.generate_content(model=MODEL, contents=contents, config=config)

        candidate = resp.candidates[0] if resp.candidates else None
        parts = candidate.content.parts if candidate and candidate.content else []
        func_calls = [p.function_call for p in parts if getattr(p, "function_call", None)]
        text_parts = [p.text for p in parts if getattr(p, "text", None)]
        final_text = "\n".join(text_parts).strip()

        log_event({"run_id": run_id, "chat_id": chat_id, "event": "model_response",
                   "iteration": iteration, "has_function_calls": bool(func_calls),
                   "text": final_text})

        if not func_calls:
            break

        # echo the model's turn back, then supply function results
        contents.append(candidate.content)
        response_parts = []
        for fc in func_calls:
            result_text = dispatch_tool(fc.name, dict(fc.args or {}))
            log_event({"run_id": run_id, "chat_id": chat_id, "event": "tool_call",
                       "iteration": iteration, "tool": fc.name, "input": dict(fc.args or {}),
                       "output": result_text[:2000]})
            response_parts.append(types.Part.from_function_response(
                name=fc.name, response={"result": result_text}
            ))
        contents.append(types.Content(role="user", parts=response_parts))

    parsed = _extract_json_object(final_text)
    log_event({"run_id": run_id, "chat_id": chat_id, "event": "final",
               "raw_text": final_text, "parsed": parsed})

    if parsed is None:
        parsed = {"answer": final_text or "could not determine answer"}

    return parsed
