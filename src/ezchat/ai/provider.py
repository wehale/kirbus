"""LLM provider client for ezchat.

Supports any OpenAI-compatible endpoint (Ollama, LM Studio, OpenAI, etc.)
and the native Anthropic SDK.

Usage:
    response_text = ask("What is Rust?")
"""
from __future__ import annotations

from ezchat.ai.config import load_ai_config


class AIConfigError(Exception):
    """Raised when the AI provider cannot be used (missing deps, bad config)."""


def ask(prompt: str, history: list[dict] | None = None) -> str:
    """Send a prompt to the configured LLM and return the response text.

    history is a list of {"role": "user"|"assistant", "content": str} dicts
    for multi-turn context (optional).

    Raises AIConfigError on misconfiguration or missing dependencies.
    Raises other exceptions (ConnectionError, TimeoutError, etc.) on network failure.
    """
    cfg = load_ai_config()
    messages = list(history or [])
    messages.append({"role": "user", "content": prompt})

    if cfg.provider == "anthropic":
        return _ask_anthropic(cfg, messages)
    else:
        return _ask_openai_compat(cfg, messages)


def _ask_openai_compat(cfg, messages: list[dict]) -> str:
    import json
    import urllib.request

    payload = json.dumps({
        "model":    cfg.model,
        "messages": messages,
        "stream":   False,
    }).encode()

    base = cfg.base_url.rstrip("/")
    url  = f"{base}/chat/completions"
    req  = urllib.request.Request(
        url,
        data    = payload,
        headers = {
            "Content-Type":  "application/json",
            "Authorization": f"Bearer {cfg.api_key or 'ollama'}",
        },
        method  = "POST",
    )
    with urllib.request.urlopen(req, timeout=120) as resp:
        data = json.loads(resp.read().decode())
    return data["choices"][0]["message"]["content"] or ""


def _ask_anthropic(cfg, messages: list[dict]) -> str:
    try:
        import anthropic
    except ImportError as exc:
        raise AIConfigError(
            "anthropic package not installed — run: pip install 'ezchat[ai]'"
        ) from exc

    client = anthropic.Anthropic(api_key=cfg.api_key or None)
    resp = client.messages.create(
        model=cfg.model,
        max_tokens=4096,
        messages=messages,
    )
    return resp.content[0].text if resp.content else ""
