"""Configuration for Jarvis. Settings are stored in jarvis_config.json (git-ignored)."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

CONFIG_PATH = Path(
    os.environ.get(
        "JARVIS_CONFIG",
        str(Path(__file__).resolve().parent.parent / "jarvis_config.json"),
    )
)

DEFAULTS: dict[str, Any] = {
    "assistant_name": "Jarvis",
    "llm": {
        # Any OpenAI-compatible endpoint works:
        #   OpenAI     -> https://api.openai.com/v1        (model: gpt-4o-mini / gpt-4o)
        #   OpenRouter -> https://openrouter.ai/api/v1
        #   Groq       -> https://api.groq.com/openai/v1
        #   Gemini     -> https://generativelanguage.googleapis.com/v1beta/openai/
        #   Ollama     -> http://localhost:11434/v1        (no key needed, model: llama3.2-vision)
        "base_url": "https://api.openai.com/v1",
        "api_key": "",
        "model": "gpt-4o-mini",
    },
    # When True, Jarvis asks for your approval before acting on the PC
    # (running commands, typing, clicking, opening apps, writing files).
    "safe_mode": True,
    # When True, replies are spoken out loud in the browser.
    "voice_replies": True,
}


def _deep_merge(base: dict, override: dict) -> dict:
    out = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = _deep_merge(out[key], value)
        else:
            out[key] = value
    return out


def load_config() -> dict[str, Any]:
    cfg = json.loads(json.dumps(DEFAULTS))  # deep copy
    try:
        if CONFIG_PATH.exists():
            saved = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
            if isinstance(saved, dict):
                cfg = _deep_merge(cfg, saved)
    except Exception:
        pass
    return cfg


def save_config(cfg: dict[str, Any]) -> dict[str, Any]:
    merged = _deep_merge(load_config(), cfg or {})
    CONFIG_PATH.write_text(json.dumps(merged, indent=2), encoding="utf-8")
    try:
        os.chmod(CONFIG_PATH, 0o600)  # only the owner can read the API key
    except Exception:
        pass
    return merged


def is_demo_mode(cfg: dict[str, Any]) -> bool:
    """True when no real LLM is reachable: no key on a remote endpoint."""
    llm = cfg.get("llm", {})
    base = (llm.get("base_url") or "").lower()
    local = "localhost" in base or "127.0.0.1" in base
    return not llm.get("api_key") and not local
