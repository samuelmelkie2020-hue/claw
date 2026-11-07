#!/usr/bin/env python3
"""Start the Claw / Jarvis assistant.

    python run.py

Then open http://localhost:8000 and talk to Jarvis.
"""

import os

import uvicorn

from jarvis.server import app

if __name__ == "__main__":
    host = os.environ.get("JARVIS_HOST", "0.0.0.0")
    port = int(os.environ.get("JARVIS_PORT", "8000"))
    print(f"\n  🦞 Claw — your Jarvis is awake → http://localhost:{port}\n")
    uvicorn.run(app, host=host, port=port, log_level="info")
