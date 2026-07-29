"""
Tools available to the data-analyst agent:
- run_python: execute python (pandas/numpy/requests available) and capture stdout
- fetch_url: download a URL (CSV/JSON/HTML) and return truncated text content

These are intentionally simple (exec() in a restricted-ish namespace) — good enough
for a grading sandbox that always runs the same container, not a multi-tenant service.
"""
import io
import contextlib
import traceback
import httpx
import pandas as pd
import numpy as np

MAX_OUTPUT_CHARS = 6000


def run_python(code: str) -> str:
    """Execute python code, return whatever was printed to stdout (or the error)."""
    buf = io.StringIO()
    g = {
        "pd": pd,
        "np": np,
        "httpx": httpx,
        "print": print,
    }
    try:
        with contextlib.redirect_stdout(buf):
            exec(code, g, g)
        out = buf.getvalue()
        if not out.strip():
            out = "(no stdout — remember to print() the values you need)"
    except Exception:
        out = "ERROR:\n" + traceback.format_exc()
    if len(out) > MAX_OUTPUT_CHARS:
        out = out[:MAX_OUTPUT_CHARS] + "\n...[truncated]"
    return out


def fetch_url(url: str) -> str:
    """Fetch a URL and return its text content, truncated. Good for CSV/JSON/HTML."""
    try:
        r = httpx.get(url, timeout=30, follow_redirects=True, headers={
            "User-Agent": "Mozilla/5.0 (data-analyst-bot)"
        })
        r.raise_for_status()
        text = r.text
    except Exception as e:
        return f"ERROR fetching {url}: {e}"
    if len(text) > MAX_OUTPUT_CHARS:
        text = text[:MAX_OUTPUT_CHARS] + "\n...[truncated]"
    return text


def web_search(query: str) -> str:
    """Free web search via DuckDuckGo (no API key). Returns titles/snippets/URLs."""
    try:
        from ddgs import DDGS
    except ImportError:
        from duckduckgo_search import DDGS  # older package name, fallback
    try:
        with DDGS() as ddgs:
            results = list(ddgs.text(query, max_results=6))
    except Exception as e:
        return f"ERROR searching '{query}': {e}"
    if not results:
        return "No results found."
    lines = []
    for r in results:
        title = r.get("title", "")
        href = r.get("href") or r.get("link", "")
        body = r.get("body", "")
        lines.append(f"- {title}\n  {href}\n  {body}")
    return "\n".join(lines)


TOOL_SCHEMAS = [
    {
        "name": "run_python",
        "description": (
            "Execute Python code for data analysis. pandas (pd), numpy (np) and httpx "
            "are preloaded. Use httpx.get(url).text or pd.read_csv(url) to pull data "
            "(e.g. MOSPI datasets). Always print() the results you need to see — only "
            "stdout is returned to you."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "code": {"type": "string", "description": "Python code to execute."}
            },
            "required": ["code"],
        },
    },
    {
        "name": "fetch_url",
        "description": "Fetch raw text content of a URL (HTML/CSV/JSON). Useful for exploring a page before parsing it in run_python.",
        "input_schema": {
            "type": "object",
            "properties": {
                "url": {"type": "string", "description": "URL to fetch."}
            },
            "required": ["url"],
        },
    },
    {
        "name": "web_search",
        "description": "Free web search (DuckDuckGo) to find dataset pages, MOSPI links, or facts. Returns titles/snippets/URLs.",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search query."}
            },
            "required": ["query"],
        },
    },
]


def dispatch_tool(name: str, tool_input: dict) -> str:
    if name == "run_python":
        return run_python(tool_input.get("code", ""))
    if name == "fetch_url":
        return fetch_url(tool_input.get("url", ""))
    if name == "web_search":
        return web_search(tool_input.get("query", ""))
    return f"ERROR: unknown tool {name}"
