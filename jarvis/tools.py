"""Tools that let Jarvis see and control the PC.

Everything is guarded so the server also runs on machines without a display
(e.g. during development) — in that case tools return friendly errors or a
placeholder screenshot instead of crashing.
"""

from __future__ import annotations

import base64
import io
import os
import platform
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

MAX_OUTPUT = 4000        # max characters of tool output fed back to the model
MAX_FILE_READ = 8000     # max characters of a file read

# Tools that modify the system or control the keyboard/mouse.
DANGEROUS_TOOLS = {
    "run_command",
    "open_app",
    "type_text",
    "press_keys",
    "click",
    "write_file",
    "clipboard",
}

# ---------------------------------------------------------------------------
# Tool schemas (OpenAI function-calling format)
# ---------------------------------------------------------------------------

TOOLS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "see_screen",
            "description": (
                "Capture the user's screen and look at it. Use this whenever the "
                "user asks what is on their screen, what they are doing, what an "
                "error says, or anything that requires seeing their PC. The "
                "screenshot is attached to the conversation as an image."
            ),
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "run_command",
            "description": (
                "Run a shell command on the user's computer and return its output. "
                "Use for anything that can be done from a terminal. Never run "
                "destructive commands (rm -rf, format, del /s, registry edits) "
                "unless the user explicitly asked for exactly that."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "command": {"type": "string", "description": "The shell command to run."},
                    "cwd": {"type": "string", "description": "Optional working directory."},
                },
                "required": ["command"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "open_app",
            "description": "Open an application on the user's computer (e.g. 'notepad', 'chrome', 'Spotify', 'Calculator').",
            "parameters": {
                "type": "object",
                "properties": {
                    "app": {"type": "string", "description": "Name of the app to open."}
                },
                "required": ["app"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "type_text",
            "description": "Type text with the keyboard at the current cursor position. Use after opening an app or after click.",
            "parameters": {
                "type": "object",
                "properties": {
                    "text": {"type": "string", "description": "The text to type."}
                },
                "required": ["text"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "press_keys",
            "description": "Press keyboard shortcuts, e.g. ['ctrl','s'] to save, ['enter'], ['alt','tab'].",
            "parameters": {
                "type": "object",
                "properties": {
                    "keys": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Keys to press together as a shortcut.",
                    }
                },
                "required": ["keys"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "click",
            "description": "Click the mouse at screen coordinates (pixels). Combine with see_screen to find the coordinates.",
            "parameters": {
                "type": "object",
                "properties": {
                    "x": {"type": "integer"},
                    "y": {"type": "integer"},
                    "button": {"type": "string", "enum": ["left", "right", "middle"], "default": "left"},
                },
                "required": ["x", "y"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "system_info",
            "description": "Report the computer's status: OS, CPU, memory, disk, battery, uptime and top processes.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_files",
            "description": "List files and folders in a directory (defaults to the user's home folder).",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Directory path. Defaults to home."}
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": "Read a text file from the computer.",
            "parameters": {
                "type": "object",
                "properties": {"path": {"type": "string"}},
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "write_file",
            "description": "Create or overwrite a text file with the given content.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "content": {"type": "string"},
                },
                "required": ["path", "content"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_files",
            "description": "Search for files by name under a folder (defaults to the user's home folder).",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Substring of the file name."},
                    "path": {"type": "string", "description": "Folder to search in. Defaults to home."},
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "clipboard",
            "description": "Get the current clipboard text, or set it to new text.",
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {"type": "string", "enum": ["get", "set"]},
                    "text": {"type": "string", "description": "Text to put on the clipboard when action is 'set'."},
                },
                "required": ["action"],
            },
        },
    },
]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _truncate(text: str, limit: int = MAX_OUTPUT) -> str:
    text = text or ""
    if len(text) <= limit:
        return text
    return text[:limit] + f"\n… [truncated, {len(text) - limit} more characters]"


def _fail(message: str) -> dict[str, Any]:
    return {"ok": False, "result": f"Error: {message}"}


def _placeholder_image(message: str) -> str:
    """Generate a placeholder PNG (base64) when the screen can't be captured."""
    from PIL import Image, ImageDraw

    img = Image.new("RGB", (960, 540), (10, 16, 30))
    draw = ImageDraw.Draw(img)
    draw.rectangle([40, 40, 920, 500], outline=(40, 200, 230), width=3)
    # simple wrapped message
    words, lines, line = message.split(), [], ""
    for w in words:
        if len(line) + len(w) > 60:
            lines.append(line)
            line = w
        else:
            line = (line + " " + w).strip()
    if line:
        lines.append(line)
    y = 230
    for ln in lines[:8]:
        draw.text((80, y), ln, fill=(160, 220, 245))
        y += 28
    draw.text((80, 470), "Claw / Jarvis — screen capture", fill=(90, 130, 160))
    buf = io.BytesIO()
    img.save(buf, "PNG")
    return base64.b64encode(buf.getvalue()).decode()


def _pyautogui():
    import pyautogui  # noqa: PLC0415  (lazy: needs a display)

    pyautogui.FAILSAFE = True
    return pyautogui


# ---------------------------------------------------------------------------
# Tool implementations
# ---------------------------------------------------------------------------

def see_screen() -> dict[str, Any]:
    try:
        import mss
        from PIL import Image

        with mss.mss() as sct:
            monitor = sct.monitors[1] if len(sct.monitors) > 1 else sct.monitors[0]
            shot = sct.grab(monitor)
            img = Image.frombytes("RGB", shot.size, shot.rgb)
        if img.width > 1280:
            img = img.resize((1280, int(img.height * 1280 / img.width)))
        buf = io.BytesIO()
        img.save(buf, "PNG")
        data = base64.b64encode(buf.getvalue()).decode()
        return {
            "ok": True,
            "result": "Screenshot captured and attached below. Describe or use it as needed.",
            "image": data,
        }
    except Exception as exc:  # no display, permissions, etc.
        return {
            "ok": True,
            "result": f"Screen capture unavailable here ({exc}). If you are running this on your PC, make sure a display is attached and the app has screen-recording permission.",
            "image": _placeholder_image(f"Screen capture unavailable: {exc}"),
        }


def run_command(command: str, cwd: str | None = None) -> dict[str, Any]:
    try:
        proc = subprocess.run(
            command,
            shell=True,
            capture_output=True,
            text=True,
            timeout=120,
            cwd=cwd or None,
        )
    except subprocess.TimeoutExpired:
        return _fail("the command timed out after 120 seconds")
    except Exception as exc:
        return _fail(str(exc))
    out = proc.stdout or ""
    if proc.stderr:
        out += ("\n[stderr]\n" if out else "[stderr]\n") + (proc.stderr or "")
    out = out.strip() or "(no output)"
    status = f"exit code {proc.returncode}"
    return {"ok": proc.returncode == 0, "result": _truncate(f"{status}\n{out}")}


def open_app(app: str) -> dict[str, Any]:
    app = (app or "").strip()
    if not app:
        return _fail("no app name given")
    try:
        if sys.platform.startswith("win"):
            os.startfile(app) if Path(app).exists() else subprocess.Popen(  # noqa: S606
                f'start "" "{app}"', shell=True
            )
        elif sys.platform == "darwin":
            target = app if Path(app).exists() else f"-a"
            subprocess.Popen(["open", target, app] if target == "-a" else ["open", app])
        else:
            exe = shutil.which(app)
            if exe:
                subprocess.Popen([exe], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            elif Path(app).exists():
                subprocess.Popen(["xdg-open", app], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            else:
                # try common desktop launchers
                for launcher in (["gtk-launch", app], [app]):
                    try:
                        subprocess.Popen(launcher, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                        return {"ok": True, "result": f"Opened {app}."}
                    except Exception:
                        continue
                return _fail(f"couldn't find an app or file named '{app}'")
        return {"ok": True, "result": f"Opened {app}."}
    except Exception as exc:
        return _fail(str(exc))


def type_text(text: str) -> dict[str, Any]:
    try:
        import pyperclip

        pyperclip.copy(text)
        pg = _pyautogui()
        modifier = "command" if sys.platform == "darwin" else "ctrl"
        pg.hotkey(modifier, "v")
        return {"ok": True, "result": f"Typed {len(text)} characters."}
    except Exception as exc:
        return _fail(f"could not type: {exc}")


def press_keys(keys: list[str]) -> dict[str, Any]:
    try:
        pg = _pyautogui()
        keys = [str(k) for k in keys]
        if len(keys) == 1:
            pg.press(keys[0])
        else:
            pg.hotkey(*keys)
        return {"ok": True, "result": f"Pressed {'+'.join(keys)}."}
    except Exception as exc:
        return _fail(str(exc))


def click(x: int, y: int, button: str = "left") -> dict[str, Any]:
    try:
        pg = _pyautogui()
        pg.click(int(x), int(y), button=button or "left")
        return {"ok": True, "result": f"Clicked at ({x}, {y}) with {button} button."}
    except Exception as exc:
        return _fail(str(exc))


def system_info() -> dict[str, Any]:
    lines = [f"Platform: {platform.system()} {platform.release()} ({platform.machine()})"]
    try:
        import psutil

        boot = time.time() - psutil.boot_time()
        lines.append(f"Boot time: {int(boot // 3600)}h {int((boot % 3600) // 60)}m ago")
        lines.append(f"CPU: {platform.processor() or 'unknown'}, {psutil.cpu_count(logical=True)} cores, load {psutil.getloadavg()[0]:.2f}" if hasattr(psutil, "getloadavg") else f"CPU: {platform.processor()}, {psutil.cpu_count(logical=True)} cores")
        vm = psutil.virtual_memory()
        lines.append(f"Memory: {vm.used / 1e9:.1f} GB used of {vm.total / 1e9:.1f} GB ({vm.percent}%)")
        for part in psutil.disk_partitions()[:3]:
            try:
                usage = psutil.disk_usage(part.mountpoint)
                lines.append(f"Disk {part.mountpoint}: {usage.used / 1e9:.0f} GB used of {usage.total / 1e9:.0f} GB ({usage.percent}%)")
            except Exception:
                continue
        if hasattr(psutil, "sensors_battery"):
            bat = psutil.sensors_battery()
            if bat:
                lines.append(f"Battery: {bat.percent}%{' (charging)' if bat.power_plugged else ''}")
        procs = []
        for p in psutil.process_iter(["name", "cpu_percent", "memory_percent"]):
            try:
                procs.append((p.info["memory_percent"] or 0, p.info["name"]))
            except Exception:
                continue
        top = " , ".join(n for _, n in sorted(procs, reverse=True)[:5])
        lines.append(f"Top processes by memory: {top}")
    except Exception as exc:
        lines.append(f"(detailed stats unavailable: {exc})")
    return {"ok": True, "result": _truncate("\n".join(lines))}


def list_files(path: str | None = None) -> dict[str, Any]:
    target = Path(path).expanduser() if path else Path.home()
    if not target.exists() or not target.is_dir():
        return _fail(f"'{target}' is not a folder")
    rows = []
    try:
        entries = sorted(target.iterdir(), key=lambda p: (p.is_file(), p.name.lower()))
        for e in entries[:100]:
            kind = "dir " if e.is_dir() else "file"
            size = ""
            if e.is_file():
                try:
                    s = e.stat().st_size
                    size = f"  {s / 1e6:.1f} MB" if s > 1e6 else f"  {s / 1e3:.1f} KB"
                except Exception:
                    pass
            rows.append(f"{kind}  {e.name}{size}")
        if len(entries) > 100:
            rows.append(f"… and {len(entries) - 100} more")
    except Exception as exc:
        return _fail(str(exc))
    return {"ok": True, "result": _truncate(f"{target}:\n" + ("\n".join(rows) or "(empty folder)"))}


def read_file(path: str) -> dict[str, Any]:
    p = Path(path).expanduser()
    if not p.exists():
        return _fail(f"'{path}' does not exist")
    if not p.is_file():
        return _fail(f"'{path}' is not a file")
    try:
        text = p.read_text(encoding="utf-8", errors="replace")
    except Exception as exc:
        return _fail(str(exc))
    return {"ok": True, "result": _truncate(text, MAX_FILE_READ)}


def write_file(path: str, content: str) -> dict[str, Any]:
    p = Path(path).expanduser()
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content or "", encoding="utf-8")
    except Exception as exc:
        return _fail(str(exc))
    return {"ok": True, "result": f"Wrote {len(content or '')} characters to {p}."}


def search_files(query: str, path: str | None = None) -> dict[str, Any]:
    root = Path(path).expanduser() if path else Path.home()
    if not root.exists():
        return _fail(f"'{root}' does not exist")
    needle = (query or "").lower()
    hits: list[str] = []
    for dirpath, dirnames, filenames in os.walk(root):
        # skip heavy/hidden folders
        dirnames[:] = [d for d in dirnames if not d.startswith(".") and d.lower() not in {"node_modules", "__pycache__", "venv", ".venv"}]
        for fn in filenames:
            if needle in fn.lower():
                hits.append(str(Path(dirpath) / fn))
                if len(hits) >= 30:
                    break
        if len(hits) >= 30:
            break
    return {"ok": True, "result": _truncate("\n".join(hits) or f"No files matching '{query}' under {root}")}


def clipboard(action: str, text: str | None = None) -> dict[str, Any]:
    try:
        import pyperclip

        if action == "get":
            return {"ok": True, "result": _truncate(f"Clipboard: {pyperclip.paste()!r}")}
        pyperclip.copy(text or "")
        return {"ok": True, "result": "Clipboard updated."}
    except Exception as exc:
        return _fail(str(exc))


# ---------------------------------------------------------------------------
# Dispatcher
# ---------------------------------------------------------------------------

def execute_tool(name: str, args: dict[str, Any]) -> dict[str, Any]:
    args = args or {}
    try:
        if name == "see_screen":
            return see_screen()
        if name == "run_command":
            return run_command(args.get("command", ""), args.get("cwd"))
        if name == "open_app":
            return open_app(args.get("app", ""))
        if name == "type_text":
            return type_text(args.get("text", ""))
        if name == "press_keys":
            return press_keys(args.get("keys", []))
        if name == "click":
            return click(args.get("x", 0), args.get("y", 0), args.get("button", "left"))
        if name == "system_info":
            return system_info()
        if name == "list_files":
            return list_files(args.get("path"))
        if name == "read_file":
            return read_file(args.get("path", ""))
        if name == "write_file":
            return write_file(args.get("path", ""), args.get("content", ""))
        if name == "search_files":
            return search_files(args.get("query", ""), args.get("path"))
        if name == "clipboard":
            return clipboard(args.get("action", "get"), args.get("text"))
        return _fail(f"unknown tool '{name}'")
    except Exception as exc:  # never let a tool crash the agent
        return _fail(f"{type(exc).__name__}: {exc}")
