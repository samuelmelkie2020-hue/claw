"""FastAPI server: serves the Jarvis web UI and the agent API."""

from __future__ import annotations

import base64
import json
from pathlib import Path
from typing import Any

from fastapi import FastAPI
from fastapi.responses import FileResponse, JSONResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import __version__
from .config import load_config, save_config
from .llm import run_agent_turn
from .tools import DANGEROUS_TOOLS, execute_tool, see_screen

STATIC_DIR = Path(__file__).resolve().parent / "static"

app = FastAPI(title="Claw — Jarvis", version=__version__)
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------

class ChatRequest(BaseModel):
    message: str
    history: list[dict] = []
    settings: dict | None = None


class ApproveRequest(BaseModel):
    name: str
    args: dict = {}


class SettingsRequest(BaseModel):
    settings: dict


# ---------------------------------------------------------------------------
# Pages
# ---------------------------------------------------------------------------

@app.get("/")
def index() -> FileResponse:
    return FileResponse(str(STATIC_DIR / "index.html"))


# ---------------------------------------------------------------------------
# API
# ---------------------------------------------------------------------------

@app.get("/api/health")
def health() -> dict:
    return {"ok": True, "version": __version__, "demo": not load_config().get("llm", {}).get("api_key")}


@app.get("/api/settings")
def get_settings() -> dict:
    return load_config()


@app.post("/api/settings")
def post_settings(body: SettingsRequest) -> dict:
    return save_config(body.settings or {})


@app.get("/api/screenshot")
def get_screenshot() -> Response:
    result = see_screen()
    data = base64.b64decode(result.get("image", ""))
    return Response(content=data, media_type="image/png")


@app.post("/api/approve")
def approve(body: ApproveRequest) -> JSONResponse:
    """Execute an action the user explicitly approved (bypasses safe mode)."""
    if body.name not in DANGEROUS_TOOLS:
        return JSONResponse({"ok": False, "result": "This action does not need approval."})
    result = execute_tool(body.name, body.args or {})
    return JSONResponse(result)


@app.post("/api/chat")
def chat(body: ChatRequest) -> StreamingResponse:
    """Run one agent turn and stream Server-Sent Events to the UI."""
    cfg = load_config()
    if body.settings:
        # UI passes the effective settings with every message (no need to save first)
        merged = json.loads(json.dumps(cfg))
        merged.update({k: v for k, v in body.settings.items() if k != "llm"})
        if isinstance(body.settings.get("llm"), dict):
            merged["llm"].update(body.settings["llm"])
        cfg = merged

    return StreamingResponse(
        _streaming_chat(body, cfg),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


def _sse(etype: str, data: dict) -> str:
    return f"data: {json.dumps({'type': etype, **data})}\n\n"


def _streaming_chat(body: ChatRequest, cfg: dict):
    """True streaming generator: the agent emits events through a queue that
    this generator drains and forwards to the browser in real time."""
    import queue as queue_mod
    import threading

    q: queue_mod.Queue = queue_mod.Queue()

    def emit(etype: str, data: dict) -> None:
        q.put((etype, data))

    def worker() -> None:
        try:
            text = run_agent_turn(body.message.strip(), body.history or [], cfg, emit)
            q.put(("done", {"text": text}))
        except Exception as exc:
            q.put(("error", {"message": str(exc)}))
            q.put(("done", {"text": f"Something went wrong: {exc}"}))
        finally:
            q.put(None)

    threading.Thread(target=worker, daemon=True).start()

    while True:
        item = q.get()
        if item is None:
            break
        etype, data = item
        yield _sse(etype, data)
