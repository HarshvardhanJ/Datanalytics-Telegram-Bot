"""
Provider-agnostic entry point. Set LLM_PROVIDER to "aipipe" (default — uses your
course's AIPipe credits via a standard OpenAI-compatible API), "gemini" (free tier,
own Google account), or "anthropic" (paid, own Anthropic key).
All three expose the same run_agent(chat_id, messages_history, run_id) -> dict interface.
"""
import os

PROVIDER = os.environ.get("LLM_PROVIDER", "aipipe").lower()

if PROVIDER == "anthropic":
    from agent_anthropic import run_agent  # noqa: F401
elif PROVIDER == "gemini":
    from agent_gemini import run_agent  # noqa: F401
else:
    from agent_aipipe import run_agent  # noqa: F401
