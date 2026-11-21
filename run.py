#!/usr/bin/env python3
"""Start Aegis.

    python run.py            # desktop window (default)
    python run.py --web      # browser version, prints a token URL
    python run.py --web --no-open
    python run.py --port 8080

The desktop shell runs the same server on loopback and shows it in a native
window, so nothing about the app is duplicated — see aegis/desktop.py.
"""

from __future__ import annotations

import argparse
import os
import sys
import threading
import time
import urllib.request
import webbrowser

from aegis.security import describe_exposure, unlock_url

DEFAULT_HOST = "127.0.0.1"  # localhost only; see aegis/security.py


def _open_when_ready(url: str, health_url: str, token: str) -> None:
    """Open the browser only once the server actually answers.

    A fixed sleep used to race the startup and show a "can't connect" page.
    """
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        try:
            request = urllib.request.Request(health_url, headers={"X-Aegis-Token": token})
            urllib.request.urlopen(request, timeout=2)
            break
        except Exception:
            time.sleep(0.2)
    try:
        webbrowser.open(url)
    except Exception:
        print(f"  Open this URL in your browser: {url}")


def run_web(host: str, port: int, open_browser: bool) -> int:
    import uvicorn

    from aegis.security import get_token
    from aegis.server import app

    print()
    print("  Aegis is awake")
    print(f"  →  open {unlock_url(port, host)}")
    print(f"     {describe_exposure(host)}")
    if host not in {"127.0.0.1", "localhost", "::1"}:
        print("     (set AEGIS_HOST=127.0.0.1 to go back to this machine only)")
    print()

    _adopt_local_model()

    if open_browser:
        target = unlock_url(port, host)
        health = f"http://localhost:{port}/api/health"
        threading.Thread(
            target=_open_when_ready, args=(target, health, get_token()), daemon=True
        ).start()

    uvicorn.run(app, host=host, port=port, log_level="info")
    return 0


def _adopt_local_model(*, timeout: float = 3.0) -> None:
    """Use a model already on this PC, so the app works with no setup at all.

    Bounded on purpose: this runs before the server starts, and a model server
    that is mid-launch must not delay the first page. Whatever happens, the app
    opens; Settings → 💻 This computer has a Refresh button for the retry.
    """
    def work() -> None:
        try:
            from aegis.local_llm import adopt_local

            result = adopt_local()
            if result.get("changed"):
                print(f"  ✓ {result.get('reason')} (no API key needed)")
        except Exception:  # pragma: no cover - never block the app from starting
            pass

    worker = threading.Thread(target=work, name="aegis-adopt", daemon=True)
    worker.start()
    worker.join(timeout)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="aegis",
        description="Aegis — your own Aegis for the PC.",
    )
    parser.add_argument(
        "--web",
        action="store_true",
        help="serve the browser UI instead of opening a desktop window",
    )
    parser.add_argument(
        "--no-open",
        action="store_true",
        help="with --web: do not open a browser automatically",
    )
    parser.add_argument("--port", type=int, default=None, help="port to listen on (default 8000)")
    parser.add_argument(
        "--host",
        default=None,
        help="bind address for --web (default 127.0.0.1; 0.0.0.0 exposes it on your network)",
    )
    parser.add_argument("--debug", action="store_true", help="developer tools in the desktop window")
    parser.add_argument(
        "--self-check",
        action="store_true",
        help="verify this build can start, without opening a window (used by CI)",
    )
    # Used by CI to prove a real window opens: a normal launch, but the app closes
    # itself after a moment and the exit code says whether a window existed.
    # Hidden, because it is an assertion tool rather than something a user runs.
    parser.add_argument("--window-proof", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument(
        "--diagnose",
        action="store_true",
        help="print a shareable report explaining why the window does not open",
    )
    args = parser.parse_args(argv)

    port = args.port if args.port is not None else int(os.environ.get("AEGIS_PORT", "8000"))

    if args.window_proof:
        # The desktop shell reads these; setting them here means the flag alone is
        # enough (CI does not have to remember two things).
        os.environ.setdefault("AEGIS_WINDOW_PROOF", "1")
        os.environ.setdefault("AEGIS_WINDOW_PROOF_SECONDS", "8")

    if args.self_check:
        from aegis.desktop import self_check

        return self_check()

    if args.diagnose:
        from aegis.desktop import diagnose

        return diagnose()

    if args.web:
        host = args.host or os.environ.get("AEGIS_HOST", DEFAULT_HOST)
        os.environ["AEGIS_HOST"] = host
        return run_web(host, port, open_browser=not args.no_open)

    from aegis.desktop import run_desktop

    return run_desktop(port=port, debug=args.debug)


if __name__ == "__main__":
    sys.exit(main())
