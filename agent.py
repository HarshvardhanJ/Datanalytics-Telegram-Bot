"""
Provider-agnostic entry point. Set LLM_PROVIDER=gemini (default, free) or
LLM_PROVIDER=anthropic to choose which backend actually answers questions.
Both expose the same run_agent(chat_id, messages_history, run_id) -> dict interface.
"""
import os

PROVIDER = os.environ.get("LLM_PROVIDER", "gemini").lower()

if PROVIDER == "anthropic":
    from agent_anthropic import run_agent  # noqa: F401
else:
    from agent_gemini import run_agent  # noqa: F401
