"""The Jarvis agent loop: talks to any OpenAI-compatible LLM with tool calling,
or falls back to a built-in demo brain when no key is configured."""

from __future__ import annotations

import json
import re
from typing import Any, Callable

import httpx

from .config import is_demo_mode
from .tools import DANGEROUS_TOOLS, TOOLS, execute_tool

MAX_TOOL_ROUNDS = 8
EmitFn = Callable[[str, dict], None]

SYSTEM_PROMPT = """You are {name}, a personal AI assistant that runs on the user's computer — like Jarvis.
You can SEE the screen and CONTROL the computer with tools: run commands, open apps, type, click, manage files, read the clipboard and report system status.

Personality: calm, capable, a little witty — but always concise. Speak like a trusted aide.

Rules:
- When the user asks anything about what is on their screen, what they are doing, what a window/error says — call see_screen FIRST and then answer from the image.
- To operate the UI: see_screen to find coordinates -> click -> type_text / press_keys.
- Prefer safe, reversible actions. Never run destructive commands (rm -rf, formatting disks, deleting system files, registry wipes) unless the user explicitly and clearly asks for exactly that.
- Summarize what you did in one or two sentences; don't dump raw tool output unless asked.
- Answer in the same language the user writes in.
- If a tool fails, explain briefly and suggest the fix.
"""


# ---------------------------------------------------------------------------
# OpenAI-compatible client
# ---------------------------------------------------------------------------

class ChatClient:
    def __init__(self, base_url: str, api_key: str, model: str):
        self.url = (base_url or "").rstrip("/") + "/chat/completions"
        self.api_key = api_key or ""
        self.model = model

    def complete(self, messages: list[dict], tools: list[dict]) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "temperature": 0.4,
        }
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = "auto"
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        resp = httpx.post(self.url, json=payload, headers=headers, timeout=240)
        if resp.status_code != 200:
            raise RuntimeError(f"LLM error {resp.status_code}: {resp.text[:500]}")
        data = resp.json()
        try:
            msg = data["choices"][0]["message"]
        except (KeyError, IndexError) as exc:
            raise RuntimeError(f"Unexpected LLM response: {str(data)[:500]}") from exc
        # normalize
        out: dict[str, Any] = {"role": "assistant", "content": msg.get("content") or ""}
        if msg.get("tool_calls"):
            out["tool_calls"] = [
                {
                    "id": tc.get("id") or f"call_{i}",
                    "type": "function",
                    "function": {
                        "name": tc["function"]["name"],
                        "arguments": tc["function"].get("arguments") or "{}",
                    },
                }
                for i, tc in enumerate(msg["tool_calls"])
            ]
        return out


def _parse_args(raw: str) -> dict:
    try:
        args = json.loads(raw or "{}")
        return args if isinstance(args, dict) else {}
    except Exception:
        return {}


def _tool_message(call_id: str, name: str, result: dict) -> dict:
    return {"role": "tool", "tool_call_id": call_id, "name": name, "content": result.get("result", "")}


def _image_message(image_b64: str) -> dict:
    return {
        "role": "user",
        "content": [
            {"type": "text", "text": "[Jarvis captured this screenshot of the user's screen]"},
            {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{image_b64}"}},
        ],
    }


# ---------------------------------------------------------------------------
# The agent turn
# ---------------------------------------------------------------------------

def run_agent_turn(
    user_message: str,
    history: list[dict],
    cfg: dict,
    emit: EmitFn,
) -> str:
    """Run one user turn (with tool loops) and return the final text reply."""
    name = cfg.get("assistant_name") or "Jarvis"
    safe_mode = bool(cfg.get("safe_mode", True))

    if is_demo_mode(cfg):
        return _demo_turn(user_message, cfg, emit)

    llm = cfg.get("llm", {})
    client = ChatClient(llm.get("base_url", ""), llm.get("api_key", ""), llm.get("model", ""))

    # clean history: only role/content strings
    clean_history = []
    for m in history or []:
        if isinstance(m, dict) and m.get("role") in ("user", "assistant") and isinstance(m.get("content"), str):
            clean_history.append({"role": m["role"], "content": m["content"]})

    messages: list[dict] = (
        [{"role": "system", "content": SYSTEM_PROMPT.format(name=name)}]
        + clean_history[-20:]
        + [{"role": "user", "content": user_message}]
    )

    pending_approval = False
    for _ in range(MAX_TOOL_ROUNDS):
        emit("status", {"message": "Thinking…"})
        try:
            msg = client.complete(messages, TOOLS)
        except Exception as exc:
            return (
                f"I couldn't reach the AI model: {exc}. "
                "Open Settings and check the API base URL, key and model — "
                "or leave the key empty to use my built-in demo brain."
            )

        if not msg.get("tool_calls"):
            text = msg.get("content") or "(no response)"
            emit("message", {"text": text})
            return text

        messages.append(
            {
                "role": "assistant",
                "content": msg.get("content") or "",
                "tool_calls": msg["tool_calls"],
            }
        )

        for call in msg["tool_calls"]:
            fn = call.get("function", {})
            tool_name = fn.get("name", "")
            args = _parse_args(fn.get("arguments", "{}"))
            emit("tool_start", {"name": tool_name, "args": args})

            if safe_mode and tool_name in DANGEROUS_TOOLS:
                emit(
                    "approval",
                    {"name": tool_name, "args": args, "description": _describe_action(tool_name, args)},
                )
                messages.append(_tool_message(call.get("id", ""), tool_name, {
                    "ok": False,
                    "result": "Action paused — waiting for the user to approve it in the interface.",
                }))
                pending_approval = True
                continue

            result = execute_tool(tool_name, args)
            emit("tool_result", {"name": tool_name, "result": result.get("result", ""), "ok": result.get("ok", True)})
            if result.get("image"):
                emit("screenshot", {"data": result["image"]})
            messages.append(_tool_message(call.get("id", ""), tool_name, result))
            if result.get("image"):
                messages.append(_image_message(result["image"]))

        if pending_approval:
            break

    if pending_approval:
        text = "I've paused — I need your approval before acting on the computer. Use the approval card above."
        emit("message", {"text": text})
        return text
    text = "I ran into a loop while working on that — could you rephrase the request?"
    emit("message", {"text": text})
    return text


def _describe_action(tool_name: str, args: dict) -> str:
    if tool_name == "run_command":
        return f"Run command: `{args.get('command', '')}`"
    if tool_name == "open_app":
        return f"Open app: **{args.get('app', '')}**"
    if tool_name == "type_text":
        t = args.get("text", "")
        return f"Type: “{t[:80]}{'…' if len(t) > 80 else ''}”"
    if tool_name == "press_keys":
        return f"Press keys: {'+'.join(args.get('keys', []))}"
    if tool_name == "click":
        return f"Click at ({args.get('x')}, {args.get('y')})"
    if tool_name == "write_file":
        return f"Write file: {args.get('path', '')}"
    if tool_name == "clipboard":
        return "Change the clipboard"
    return tool_name


# ---------------------------------------------------------------------------
# Demo brain — works with no API key at all
# ---------------------------------------------------------------------------

def _demo_turn(user_message: str, cfg: dict, emit: EmitFn) -> str:
    name = cfg.get("assistant_name") or "Jarvis"
    text = (user_message or "").strip()
    low = text.lower()

    def run_safe_tool(tool: str, args: dict, phrase: str) -> str:
        if cfg.get("safe_mode", True) and tool in DANGEROUS_TOOLS:
            emit("approval", {"name": tool, "args": args, "description": _describe_action(tool, args)})
            return f"I'd like to {phrase}, but I need your approval first — use the approval card above."
        emit("tool_start", {"name": tool, "args": args})
        result = execute_tool(tool, args)
        emit("tool_result", {"name": tool, "result": result.get("result", ""), "ok": result.get("ok", True)})
        if result.get("image"):
            emit("screenshot", {"data": result["image"]})
        return result.get("result", "")

    reply: str
    if re.search(r"\b(screen|what am i|what's open|what is open|see my|looking at)\b", low):
        reply = run_safe_tool("see_screen", {}, "look at your screen")
        if "attached" in reply or "captured" in reply.lower():
            reply = (
                "I've captured your screen — you can see it in the screen panel. "
                "(Demo brain: connect a vision model in Settings and I'll describe and use what I see.)"
            )
    elif re.search(r"\b(system|status|cpu|memory|ram|disk|battery|uptime|how is my (pc|computer))\b", low):
        info = run_safe_tool("system_info", {}, "check system status")
        reply = f"Here's your system status:\n\n{info}"
    elif re.search(r"\bopen\s+['\"]?([\w .\-]+)", low):
        app = re.search(r"\bopen\s+['\"]?([\w .\-]+)", low).group(1).strip(" .\"'")
        reply = run_safe_tool("open_app", {"app": app}, f"open **{app}**")
    elif re.search(r"\b(run|execute)\s+(.+)", low):
        cmd = re.search(r"\b(?:run|execute)\s+(.+)", text, re.IGNORECASE).group(1).strip()
        reply = run_safe_tool("run_command", {"command": cmd}, f"run `{cmd}`")
    elif re.search(r"\b(list|show)\b.*\b(files|folder|directory|documents|downloads|desktop)\b", low):
        folder = None
        for key, sub in (("desktop", "Desktop"), ("downloads", "Downloads"), ("documents", "Documents")):
            if key in low:
                from pathlib import Path

                folder = str(Path.home() / sub)
        reply = run_safe_tool("list_files", {"path": folder}, "list your files")
    elif re.search(r"\b(help|what can you do|capabilities|who are you|hello|hi|hey)\b", low):
        reply = (
            f"At your service — I'm {name}. Right now I'm running my built-in **demo brain**, "
            "but I can already:\n\n"
            "• 👀 **See your screen** — ask “what's on my screen?”\n"
            "• 💻 **Run commands** — “run ipconfig” or “execute ls”\n"
            "• 🚀 **Open apps** — “open notepad”\n"
            "• 📂 **Browse files** — “list my downloads”\n"
            "• 🖥 **System status** — “how is my pc?”\n\n"
            "Connect an AI model in ⚙️ Settings (OpenAI, Gemini, Groq, OpenRouter or local Ollama) "
            "and I become a full assistant that can reason about your screen and chain actions together."
        )
    else:
        reply = (
            f"That's a bit beyond my built-in demo brain. Try “what's on my screen?”, "
            "“run <command>”, “open <app>” or “help” — or connect an AI model in ⚙️ Settings "
            "so I can think for real."
        )

    emit("message", {"text": reply})
    return reply
