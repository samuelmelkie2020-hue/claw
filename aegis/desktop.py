"""The desktop shell.

Aegis started life as a web page. This module gives it a native window without
duplicating the app: uvicorn runs in a background thread on loopback, and
pywebview shows the same UI in the OS webview (WebView2 on Windows, WKWebView on
macOS, WebKitGTK on Linux).

Threading rules that matter here, because getting them wrong hangs the app:

* uvicorn's own signal handlers are disabled — in a thread they would fight the
  webview's event loop, and Ctrl+C would not close the window.
* the window is the main thread; the server is the child. When the window
  closes we shut the server down explicitly.
* readiness is a real HTTP poll of ``/api/health``, never a fixed sleep.

Security is unchanged from the browser build: the server is bound to 127.0.0.1,
and the token handshake still applies — except that in the desktop shell it is
invisible, because the first navigation goes to ``/?token=…`` on loopback, which
the server exchanges for an HttpOnly session cookie.
"""

from __future__ import annotations

import logging
import os
import platform
import socket
import sys
import threading
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path

log = logging.getLogger("aegis.desktop")

APP_NAME = "Aegis"
WINDOW_WIDTH = 1240
WINDOW_HEIGHT = 840
MIN_SIZE = (900, 620)
BROWSER_COLOR = "#060b16"
STARTUP_TIMEOUT = 30.0
ERROR_WINDOW_TIMEOUT = 20.0  # never block forever on a crash dialog


def find_free_port(preferred: int) -> int:
    """Return ``preferred`` if it is free, otherwise an ephemeral port.

    A second launch used to die with "address already in use"; now it simply
    picks a different port, which also lets two windows coexist.
    """
    probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        probe.bind(("127.0.0.1", preferred))
        if preferred == 0:
            # "Any port" must resolve to the real one, or callers poll port 0.
            return probe.getsockname()[1]
        return preferred
    except OSError:
        probe.close()
        fallback = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            fallback.bind(("127.0.0.1", 0))
            return fallback.getsockname()[1]
        finally:
            fallback.close()
    finally:
        try:
            probe.close()
        except OSError:
            pass


@dataclass
class ServerHandle:
    port: int
    thread: threading.Thread
    server: object

    @property
    def base_url(self) -> str:
        return f"http://127.0.0.1:{self.port}"


def _adopt_local_model(*, timeout: float = 3.0) -> None:
    """Pick up a model that is already installed on this PC, if any.

    This used to block the window from opening. It must not: on a Windows machine
    it shells out to a model server the user may have just started, and any delay
    here reads as "it did not open". It now runs on a daemon thread with its own
    deadline, and gives up quietly — the Settings panel has a Refresh button, and
    the app is perfectly usable in demo mode meanwhile.
    """
    def work() -> None:
        try:
            from .local_llm import adopt_local

            result = adopt_local()
            if result.get("changed"):
                log.info("Local model: %s", result.get("reason"))
        except Exception:  # pragma: no cover - startup must not depend on this
            log.debug("Local model detection skipped", exc_info=True)

    worker = threading.Thread(target=work, name="aegis-adopt", daemon=True)
    worker.start()
    worker.join(timeout)  # a short courtesy wait, never a requirement


def _write_heartbeat(stage: str) -> None:
    """Record how far startup got, for the "it does not open" case.

    A windowed build has no console, so without this the only evidence is a
    crash log that says nothing at all when the failure is a hang. Each line is
    flushed immediately: the process may never get another chance.
    """
    try:
        from .config import DATA_DIR

        DATA_DIR.mkdir(parents=True, exist_ok=True)
        stamp = time.strftime("%Y-%m-%d %H:%M:%S")
        with open(DATA_DIR / "aegis-startup.log", "a", encoding="utf-8") as handle:
            handle.write(f"{stamp}  {stage}\n")
            handle.flush()
    except Exception:  # pragma: no cover - a diagnostic must never fail
        pass


def start_server(port: int, *, log_level: str = "warning") -> ServerHandle:
    """Run uvicorn on loopback in a daemon thread and wait until it answers."""
    import uvicorn

    from .security import get_token
    from .server import app

    config = uvicorn.Config(
        app,
        host="127.0.0.1",
        port=port,
        log_level=log_level,
        access_log=False,
        lifespan="off",
    )
    server = uvicorn.Server(config)
    # In a thread these would try to own SIGINT/SIGTERM from the webview loop.
    server.install_signal_handlers = lambda: None  # type: ignore[method-assign]

    thread = threading.Thread(target=server.run, name="aegis-uvicorn", daemon=True)
    thread.start()

    handle = ServerHandle(port=port, thread=thread, server=server)
    _await_ready(handle, get_token())
    return handle


def _await_ready(handle: ServerHandle, token: str) -> None:
    """Poll the health endpoint until the app answers (or give up loudly)."""
    deadline = time.monotonic() + STARTUP_TIMEOUT
    url = f"{handle.base_url}/api/health"
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        if not handle.thread.is_alive():
            raise RuntimeError("The Aegis server exited during startup.")
        try:
            request = urllib.request.Request(url, headers={"X-Aegis-Token": token})
            with urllib.request.urlopen(request, timeout=2):
                return
        except urllib.error.HTTPError as exc:
            # Any real HTTP answer (even 401) means the socket is serving.
            if exc.code in (200, 401, 403):
                return
            last_error = exc
        except Exception as exc:  # connection refused while it boots
            last_error = exc
        time.sleep(0.1)

    hint = ""
    try:
        from .config import CONFIG_PATH

        hint = f" Settings file: {CONFIG_PATH}"
    except Exception:  # pragma: no cover - diagnostics must never raise
        pass
    raise RuntimeError(
        f"Aegis did not start within {STARTUP_TIMEOUT:.0f}s ({last_error}).{hint}"
    )


def stop_server(handle: ServerHandle | None) -> None:
    if handle is None:
        return
    try:
        handle.server.should_exit = True  # type: ignore[attr-defined]
    except Exception:  # pragma: no cover
        log.warning("Could not ask the server to stop", exc_info=True)
    handle.thread.join(timeout=5)


# ---------------------------------------------------------------------------
# JS bridge (window controls from the page)
# ---------------------------------------------------------------------------

class DesktopAPI:
    """Exposed to the page as ``window.pywebview.api`` in the desktop shell.

    Deliberately tiny: the page keeps using HTTP for everything else, so the
    browser build and the desktop build stay one codebase.
    """

    def __init__(self) -> None:
        self._window = None
        self._server: ServerHandle | None = None

    def attach(self, window, server: ServerHandle | None = None) -> None:
        self._window = window
        self._server = server

    def info(self) -> dict:
        from . import __version__

        return {
            "desktop": True,
            "version": __version__,
            "port": self._server.port if self._server else None,
            "platform": os.name,
        }

    def open_settings(self) -> None:
        """Focus the window and open the settings dialog (menu accelerator)."""
        if self._window is None:
            return
        self._window.restore() if self._window.minimized else self._window.show()
        try:
            self._window.evaluate_js("window.__aegisOpenSettings && window.__aegisOpenSettings()")
        except Exception:  # pragma: no cover - best effort
            log.debug("Could not open settings from the menu", exc_info=True)

    def new_conversation(self) -> None:
        if self._window is None:
            return
        try:
            self._window.evaluate_js("window.__aegisNewChat && window.__aegisNewChat()")
        except Exception:  # pragma: no cover
            log.debug("Could not start a new conversation", exc_info=True)

    def min_size(self) -> dict:
        return {"width": MIN_SIZE[0], "height": MIN_SIZE[1]}


def _menu_option(webview, api: DesktopAPI) -> dict:
    """The menu, as a keyword for ``webview.start`` — or nothing at all.

    A menu is decoration. Different pywebview versions accept it differently (as
    of 5.x it is ignored unless a GUI backend supports it, and passing it to a
    backend that does not is one more way for the window to fail). It must never
    be the reason the app does not open, so it is offered only when this build
    actually has menu support.
    """
    try:
        if not hasattr(webview, "menu"):
            return {}
        return {"menu": _menu(api)}
    except Exception:  # pragma: no cover - decoration
        return {}


def _menu(api: DesktopAPI):
    """A minimal native menu: settings, new conversation, quit."""
    try:
        from webview.menu import Menu, MenuAction, MenuSeparator
    except Exception:  # pragma: no cover - older pywebview
        return []

    items = [
        MenuAction("Settings…", api.open_settings),
        MenuAction("New conversation", api.new_conversation),
        MenuSeparator(),
    ]
    return [Menu("Aegis", items)]


def window_icon_path() -> Path | None:
    """The window icon, wherever it lives in this layout (source or bundle).

    Windows and macOS take the icon from the executable itself, so this only
    matters on Linux — but returning ``None`` cleanly is what keeps a missing
    asset from breaking startup anywhere.
    """
    from .server import STATIC_DIR

    candidate = Path(STATIC_DIR) / "aegis.png"
    return candidate if candidate.exists() else None


def _ensure_streams() -> None:
    """Give a windowed bundle somewhere to print, in an encoding that cannot fail.

    Two separate failures live here, both seen on real machines:

    * PyInstaller's ``console=False`` build leaves ``sys.stdout`` as ``None``, so a
      bare ``print`` raises ``AttributeError`` and takes the process down.
    * On Windows a console that exists but uses a legacy code page (cp1252) raises
      ``UnicodeEncodeError`` on the first banner emoji — ``'charmap' codec can't
      encode character '\U0001f6e1'`` is the exact error that stopped the window
      from ever being created.

    So: hand back a devnull file when there is nothing, and force the encoding to
    UTF-8 with ``errors="replace"`` when there is something. A banner is never
    worth a failed launch.
    """
    for name in ("stdout", "stderr"):
        stream = getattr(sys, name)
        if stream is None:
            try:
                setattr(sys, name, open(os.devnull, "w", encoding="utf-8"))  # noqa: SIM115
            except OSError:  # pragma: no cover - devnull always opens
                pass
            continue
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:  # not a TextIOWrapper, or closed; printing must still work
            pass


def _print_safe(text: str = "") -> None:
    """print() that cannot raise on a code page or a closed stream.

    Kept separate from :func:`_ensure_streams` because a stream can be replaced
    after startup (a frozen app on Windows reassigns it), and because diagnostics
    are the one thing that must never become the failure.
    """
    try:
        print(text)
        return
    except Exception:
        pass
    try:
        buffer = getattr(sys.stdout, "buffer", None)
        if buffer is not None:
            buffer.write((text + "\n").encode("ascii", "replace"))
            buffer.flush()
    except Exception:  # pragma: no cover - nothing left to try
        pass


def self_check() -> int:
    """Verify a build can start, without opening a window.

    Used by CI against the frozen binary and by users who report "it does not
    open" — it checks the pieces that actually break in a bundle (static
    assets, imports, a writable settings location) and prints where the
    settings file lives.
    """
    _ensure_streams()
    problems: list[str] = []
    report: list[str] = []

    def say(line: str = "") -> None:
        report.append(line)
        print(line)

    try:
        from . import __version__

        say(f"Aegis {__version__} self-check")
    except Exception as exc:  # pragma: no cover - only if the bundle is broken
        problems.append(f"version import failed: {exc}")

    try:
        from .config import CONFIG_PATH, DATA_DIR, is_frozen, user_data_dir

        say(f"  frozen:      {is_frozen()}")
        say(f"  data dir:    {DATA_DIR}")
        say(f"  settings:    {CONFIG_PATH}")
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        probe = user_data_dir() / ".write-probe"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
        say("  writable:    yes")
    except Exception as exc:
        problems.append(f"settings location unusable: {exc}")

    try:
        from pathlib import Path

        from .server import STATIC_DIR

        for asset in ("index.html", "app.js", "style.css"):
            if not (Path(STATIC_DIR) / asset).exists():
                problems.append(f"missing bundled asset: aegis/static/{asset}")
        if window_icon_path() is None:
            # Cosmetic, so it is reported but does not fail the check.
            print("  window icon: missing (aegis.png not bundled)")
        else:
            print("  window icon: ok")
        say(f"  web UI:      {STATIC_DIR}")
    except Exception as exc:
        problems.append(f"web UI missing: {exc}")

    try:
        handle = start_server(find_free_port(0))
        say(f"  server:      ok ({handle.base_url})")
        stop_server(handle)
        say("  shutdown:    ok")
    except Exception as exc:
        problems.append(f"server failed to start: {exc}")

    try:
        import webview  # noqa: F401

        say("  webview:     installed")
    except Exception as exc:
        problems.append(f"pywebview not available: {exc}")

    # The default brain is a local one, so a build where that module cannot even
    # be imported would open a window that can never think. Check it here rather
    # than discovering it when the user presses Save.
    try:
        from . import local_llm

        hardware = local_llm.cached_hardware()  # never probes: --self-check must stay fast
        say(f"  local model: {'cached' if hardware else 'not probed (ok)'}")
    except Exception as exc:
        problems.append(f"local model module failed to import: {exc}")

    if problems:
        say("\nFAILED:")
        for problem in problems:
            say(f"  - {problem}")
    else:
        say("\nAll checks passed.")
    _write_report(report)
    return 1 if problems else 0


def _webview2_version() -> str | None:
    """The installed Edge WebView2 runtime version, or ``None`` when absent.

    Duplicated from the frozen bootstrap (packaging/entry.py) on purpose: that
    file must run before the application imports, so it cannot import this one.
    """
    if not sys.platform.startswith("win"):
        return None
    try:
        import winreg
    except ImportError:  # pragma: no cover - only reachable on Windows
        return None

    guide = r"Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}"
    for root, prefix in (
        (winreg.HKEY_LOCAL_MACHINE, "SOFTWARE\\WOW6432Node\\"),
        (winreg.HKEY_LOCAL_MACHINE, "SOFTWARE\\"),
        (winreg.HKEY_CURRENT_USER, "SOFTWARE\\"),
    ):
        try:
            with winreg.OpenKey(root, prefix + guide) as key:
                version = winreg.QueryValueEx(key, "pv")[0]
        except OSError:
            continue
        except Exception:  # noqa: BLE001 - a registry read must never be fatal
            continue
        if version and version != "0.0.0.0":
            return version
    return None


def diagnose() -> int:
    """A shareable report for "it does not open".

    Deliberately not a pass/fail check like ``--self-check``: the question here
    is *why* nothing appeared, so it prints the facts a maintainer needs — the
    webview backend, whether WebView2 is present, whether another copy already
    holds the port, and whether a crash or startup log exists — and says which
    of them is the likely culprit.
    """
    _ensure_streams()
    report: list[str] = []

    def say(line: str = "") -> None:
        report.append(line)
        print(line)

    from . import __version__

    say(f"Aegis {__version__} — startup diagnosis")
    say(f"  python:      {sys.version.split()[0]}")
    say(f"  platform:    {platform_description()}")
    say(f"  frozen:      {is_frozen_bundle()}")
    say(f"  executable:  {sys.executable}")

    try:
        from .config import CONFIG_PATH, user_data_dir

        say(f"  data dir:    {user_data_dir()}")
        say(f"  settings:    {CONFIG_PATH}")
        writable = "yes"
        try:
            probe = user_data_dir() / ".write-probe"
            probe.write_text("ok", encoding="utf-8")
            probe.unlink()
        except Exception as exc:
            writable = f"NO ({exc})"
        say(f"  writable:    {writable}")
    except Exception as exc:
        say(f"  data dir:    unavailable ({exc})")

    try:
        import webview

        say(f"  pywebview:   {getattr(webview, '__version__', 'installed')}")
    except Exception as exc:
        say(f"  pywebview:   MISSING ({exc})")
        say("")
        say("→ Install it: pip install pywebview")

    if sys.platform.startswith("win"):
        version = _webview2_version()
        say(f"  WebView2:    {version or 'NOT FOUND'}")
        if not version:
            say("")
            say("→ This is the usual cause of 'nothing happens' on Windows.")
            say("  Install it once (free, ~2 MB):")
            say("  https://go.microsoft.com/fwlink/p/?LinkId=2124703")

    # How far did the last launch actually get? This is the difference between
    # "it crashed", "it hung" and "it opened and the window was invisible".
    try:
        from .config import DATA_DIR as dir_for_logs

        progress = dir_for_logs / "aegis-startup.log"
        if progress.exists():
            lines = progress.read_text(encoding="utf-8", errors="replace").splitlines()
            last = [ln for ln in lines if ln.strip()][-12:]
            say(f"  startup log: {progress}")
            say("")
            say("  --- how far the last launch got ---")
            for line in last:
                say(f"  {line}")
            say("  --- end ---")
            if last:
                final = last[-1]
                if "4/4" in final.split("  ")[-1]:
                    say("")
                    say("→ It reached the window. If you saw nothing, WebView2 is the suspect below.")
                elif "FAILED" in final:
                    say("")
                    say("→ It failed starting the server; the crash log below has the reason.")
                else:
                    say("")
                    say("→ It stopped before creating a window (stage above).")
            say("")
    except Exception:  # pragma: no cover - diagnostics must never raise
        pass

    port = int(os.environ.get("AEGIS_PORT", "8000"))
    busy = _port_in_use(port)
    say(f"  port {port}:   {'IN USE — another copy is probably running' if busy else 'free'}")
    if busy:
        say("")
        say("→ Another copy is already running (that is fine — Aegis opens on a free port).")
        say("  Look for an existing Aegis window, behind other windows or on another desktop.")

    try:
        from .config import DATA_DIR as dir_for_logs

        for name in ("aegis-crash.log", "self-check.txt"):
            path = dir_for_logs / name
            if path.exists():
                say(f"  {name}: {path}")
                if name.endswith(("crash.log", "startup.log")):
                    say("")
                    say(f"  --- last lines of {name} ---")
                    for line in path.read_text(encoding="utf-8", errors="replace").splitlines()[-8:]:
                        say(f"  {line}")
                    say(f"  --- end of {name} ---")
                    say("")
    except Exception:  # pragma: no cover - diagnostics must never raise
        pass

    try:
        from . import local_llm
        from .config import load_config as _load

        llm = (_load().get("llm") or {})
        say(f"  model:       {llm.get('model') or '(none)'} @ {llm.get('base_url') or '?'}")
        say(f"  local brain: {'yes' if llm.get('local') else 'no (cloud provider)'}")
        server = local_llm.detect_running(include=llm.get("base_url") or "", timeout=0.8)
        say(
            f"  local server: {server.name + ' on ' + server.base_url if server else 'none running'}"
        )
    except Exception as exc:  # pragma: no cover - diagnostics must never raise
        say(f"  model:       unavailable ({exc})")

    say("")
    say("If the window never appears, this is the guaranteed way in:")
    say("  Aegis.exe --web")
    say("It serves the same app on 127.0.0.1 and opens your normal browser.")
    say("")
    say("Copy this report when asking for help. It contains no API key and no token.")
    try:
        from .config import DATA_DIR as dir_for_logs

        (dir_for_logs / "aegis-diagnose.txt").write_text("\n".join(report) + "\n", encoding="utf-8")
    except Exception:  # pragma: no cover
        pass
    return 0


def platform_description() -> str:
    return f"{platform.system()} {platform.release()} ({platform.machine()})"


def is_frozen_bundle() -> bool:
    return bool(getattr(sys, "frozen", False))


def _port_in_use(port: int) -> bool:
    probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    probe.settimeout(0.4)
    try:
        return probe.connect_ex(("127.0.0.1", port)) == 0
    except OSError:
        return False
    finally:
        probe.close()


def _write_report(report: list[str]) -> None:
    """Persist the self-check output: windowed builds have no console to read."""
    try:
        from .config import DATA_DIR

        DATA_DIR.mkdir(parents=True, exist_ok=True)
        (DATA_DIR / "self-check.txt").write_text("\n".join(report) + "\n", encoding="utf-8")
    except Exception:  # pragma: no cover - diagnostics must never raise
        pass


def _report_fatal(exc: Exception, *, page: str | None = None) -> None:
    """Tell the user something useful even when there is no terminal.

    A windowed build (`console=False`) swallows stdout, so a startup failure
    would otherwise look like "nothing happened".

    Order matters, and one option is deliberately missing: a **modal** dialog
    (tkinter) is not used. In CI it blocks forever on a click that never comes,
    and on a desktop it can end up hidden behind the project window while the
    user waits for something that already failed. So: always write the log,
    then show the error in a real window if one can be opened, and otherwise
    just leave a message the user can find.
    """
    import traceback

    detail = "".join(traceback.format_exception(exc))
    log.error("Fatal startup error", exc_info=exc)
    location = ""
    try:
        from .config import DATA_DIR

        DATA_DIR.mkdir(parents=True, exist_ok=True)
        path = DATA_DIR / "aegis-crash.log"
        path.write_text(detail, encoding="utf-8")
        location = str(path)
    except Exception:  # pragma: no cover
        pass

    print(f"\n  Could not start Aegis: {exc}\n")
    if location:
        print(f"  Details written to {location}\n")

    if not page:
        return
    if os.environ.get("AEGIS_NO_GUI_ERRORS"):
        # Headless (CI, a service): a window here would block with nobody to
        # close it. The log above is the record.
        return
    try:  # the webview is already imported: we only get here after it was
        import webview

        webview.create_window("Aegis could not start", html=page(error=exc, log=location))
        _show_without_blocking(webview)
    except Exception:  # pragma: no cover - no display, no backend, or headless
        log.warning("Could not show the error window", exc_info=True)


def _show_without_blocking(webview, timeout: float | None = None) -> None:
    """Open a window, but never wait on it forever.

    ``webview.start()`` can block without raising when there is no usable
    display, and a message nobody can dismiss is worse than a log line: it
    hides the failure. Runs it on a daemon thread and gives up quietly.
    """
    thread = threading.Thread(
        target=_swallow, args=(webview.start,), name="aegis-error-window", daemon=True
    )
    thread.start()
    thread.join(ERROR_WINDOW_TIMEOUT if timeout is None else timeout)


def _swallow(func) -> None:
    try:
        func()
    except Exception:  # pragma: no cover - the point is to ignore it
        log.warning("Error window failed", exc_info=True)


def _open_in_browser(url: str) -> bool:
    """Last resort: the same app, in the browser the machine already has."""
    try:
        import webbrowser

        return bool(webbrowser.open(url))
    except Exception:  # pragma: no cover - no default browser, weird env
        return False


def _fallback_to_browser(url: str, reason: str) -> None:
    """Tell the user in words, and give them a working app.

    A native window can fail for reasons this app cannot fix (a stripped WebView2
    runtime, a locked-down machine, antivirus interference). Dying there is a
    dead end: the server is *already running*, so the honest thing is to open it
    where it is guaranteed to work and say so plainly.
    """
    message = (
        "Aegis opened in your web browser instead of its own window.\n\n"
        f"Reason: {reason}\n\n"
        "Everything works exactly the same there. This tab is the app."
    )
    _print_safe(f"\n  {message}\n")
    _write_heartbeat(f"window FAILED ({reason}) — using the browser instead")
    if _open_in_browser(url):
        return
    # No browser either: at least leave the URL somewhere the user will find it,
    # and keep the server alive so pasting it works.
    try:
        from .config import DATA_DIR

        DATA_DIR.mkdir(parents=True, exist_ok=True)
        (DATA_DIR / "aegis-open-me.txt").write_text(
            message + "\n\nOpen this address:\n" + url + "\n", encoding="utf-8"
        )
    except Exception:  # pragma: no cover
        pass


def _keep_serving(handle: ServerHandle, *, wait_forever: bool = False) -> bool:
    """Stay alive after a fallback, so the browser tab has a server to talk to.

    Without this the process would exit the moment the fallback opened the page,
    and the user would get a working-looking URL that instantly dies — which is
    the same "it does not work" with extra steps. Returns True if it kept going.
    """
    if not wait_forever:
        # A test or a scripted run must not block; the caller only asks whether
        # serving was possible.
        return True
    try:
        print("  Keeping Aegis running. Press Ctrl+C to stop.\n")
    except Exception:  # pragma: no cover
        pass
    try:
        while handle.thread.is_alive():
            time.sleep(0.5)
    except KeyboardInterrupt:
        pass
    return True


def _supported_kwargs(function, kwargs: dict) -> dict:
    """Drop keywords this pywebview version does not accept.

    ``create_window(icon=...)`` is the bug that made *every* platform fail to open
    a window: ``icon`` moved to ``start()`` in a later pywebview, and requirements
    allow a range of versions, so the build could get either. A cosmetic icon must
    never be able to stop the app from opening, so unknown keywords are dropped
    with a log line rather than raised.
    """
    try:
        import inspect

        parameters = inspect.signature(function).parameters
    except (TypeError, ValueError):  # pragma: no cover - builtins, C functions
        return kwargs
    if any(p.kind is inspect.Parameter.VAR_KEYWORD for p in parameters.values()):
        return kwargs
    unsupported = [key for key in kwargs if key not in parameters]
    if unsupported:
        log.warning("This pywebview does not accept %s; opening without it", unsupported)
        return {k: v for k, v in kwargs.items() if k in parameters}
    return kwargs


def _safe_window_step(step, *args, **kwargs) -> None:
    """Run one optional window step, and never let it abort startup.

    Exposing the JS bridge exposes *bound methods*, so ``inspect`` is called on
    ``self`` and on some pywebview versions that can raise on a window that is not
    finished being created. Losing the menu or the bridge is a nuisance; losing
    the window is a broken app.
    """
    try:
        step(*args, **kwargs)
    except Exception:  # pragma: no cover - depends on the pywebview version
        log.debug("Optional window step failed: %s", getattr(step, "__name__", step), exc_info=True)


def _start_webview(webview, **options) -> None:
    """Run the webview event loop, and never return silently without a window.

    pywebview reports a missing or broken backend in two ways: it raises, or —
    on Windows when WebView2 cannot initialise — it logs a warning and returns
    *without ever opening a window*. The second case is the bug report we kept
    getting: the process is alive, the server is on port 8000 and answering,
    and the user sees nothing at all. So if ``start()`` returns and no window
    was ever created, that is treated as a failure with a real message.
    """
    webview.start(**options)
    try:
        open_windows = len(webview.windows)
    except Exception:  # pragma: no cover - older pywebview
        return
    if open_windows == 0:
        raise RuntimeError(
            "The desktop window could not be created. This is almost always a "
            "missing WebView2 runtime on Windows, or a missing WebKitGTK on "
            "Linux — see the startup log for the backend's own message."
        )


def run_desktop(
    *, port: int | None = None, debug: bool = False, keep_serving: bool = False
) -> int:
    """Start the server, open the desktop window, and block until it closes.

    ``keep_serving`` is what makes the browser fallback usable: if no native
    window can be created, the server stays up for the tab that replaces it. It
    defaults to **off** so a caller (a test, CI, a script) never blocks on a
    fallback by accident; the real entry point in ``run.py`` turns it on.
    """
    _ensure_streams()
    try:
        import webview
    except ImportError:
        print(
            "The desktop window needs pywebview, which is not installed.\n"
            "  pip install pywebview\n"
            "or run the browser version:  python run.py --web"
        )
        return 1

    from .security import get_token

    preferred = port or int(os.environ.get("AEGIS_PORT", "8000"))
    chosen = find_free_port(preferred)
    if chosen != preferred:
        log.warning("Port %s was busy; using %s instead", preferred, chosen)

    _write_heartbeat(f"1/4 starting (port {chosen}, frozen={is_frozen_bundle()})")
    _adopt_local_model()
    _write_heartbeat("2/4 local model checked")
    try:
        handle = start_server(chosen)
    except Exception as exc:
        _write_heartbeat(f"2/4 FAILED to start the server: {exc}")
        _report_fatal(exc, page=_error_page)
        return 1
    _write_heartbeat("3/4 server answering")

    api = DesktopAPI()
    app_url = f"{handle.base_url}/?token={get_token()}"
    proof_ok = False
    try:
        # Open on a page that explains itself. The app URL is swapped in once the
        # server answers, so a slow first paint is a message, not a blank window.
        icon = window_icon_path()
        window = webview.create_window(
            **_supported_kwargs(
                webview.create_window,
                {
                    "title": APP_NAME,
                    "html": _STARTING_PAGE,
                    "js_api": api,
                    "width": WINDOW_WIDTH,
                    "height": WINDOW_HEIGHT,
                    "min_size": MIN_SIZE,
                    "background_color": BROWSER_COLOR,
                    "text_select": True,
                    "zoomable": True,
                    "confirm_close": True,
                },
            )
        )
        api.attach(window, handle)

        # Swap the "starting" page for the app. Everything has already answered by
        # now (start_server polls /api/health), so this is a navigation to a server
        # that is definitely listening — the failure mode that matters is a user
        # staring at a white window wondering whether anything happened.
        _navigate_when_ready(window, app_url)

        # The page also asks for these via JS so the browser build stays unaware.
        _safe_window_step(
            window.expose, api.info, api.open_settings, api.new_conversation, api.min_size
        )

        # An update replaces this executable, which the OS will not allow while
        # it runs. The updater starts a helper that waits for this process to
        # die; this hook is what lets it die without the user being told to
        # close the window by hand.
        from . import updates

        # A test double (or an older pywebview) may not offer destroy; the
        # update then still installs, it just waits for the user to quit.
        destroy = getattr(window, "destroy", None)
        _safe_window_step(updates.register_restart_hook, destroy if callable(destroy) else None)

        _write_heartbeat("4/4 window created")
        # Proof for CI, and for a user wondering whether anything happened: this
        # line is only reachable after pywebview really made a window.
        _write_heartbeat("WINDOW CREATED")
        proof_ok = True
        if os.environ.get("AEGIS_WINDOW_PROOF"):
            # Record the proof, then leave the process alone: CI kills it once it
            # has read this line. Closing a GUI from another thread is what turned
            # a working window into a CLR crash on Windows (0xE0434352) and into a
            # hung Cocoa loop on macOS. The window is the evidence; how the process
            # ends is not part of the claim.
            _write_heartbeat("WINDOW PROOF: window is open and serving")
        _print_safe(f"\n  🛡 Aegis is running as a desktop app (port {chosen}).")
        _print_safe("     Close the window to quit.\n")

        try:
            _start_webview(
                webview,
                **_supported_kwargs(
                    webview.start,
                    {
                        "debug": debug,
                        "private_mode": False,   # keep localStorage (voice prefs)
                        "http_server": False,    # uvicorn serves the app, not pywebview
                        **_menu_option(webview, api),
                        **({"icon": str(icon)} if icon else {}),
                    },
                ),
            )
        except Exception as exc:  # no WebView2/WebKitGTK, no display, backend refused
            _write_heartbeat(f"4/4 window could not be created: {exc}")
            _fallback_to_browser(app_url, str(exc))
            return _fallback_code(_keep_serving(handle, wait_forever=keep_serving))
    except Exception as exc:  # the window could not even be constructed
        _write_heartbeat(f"4/4 window could not be created: {exc}")
        _fallback_to_browser(app_url, str(exc))
        return _fallback_code(_keep_serving(handle, wait_forever=keep_serving))
    finally:
        stop_server(handle)

    if os.environ.get("AEGIS_WINDOW_PROOF"):
        # The proof is the exit code: 0 only if a window really existed.
        return 0 if proof_ok else 4
    return 0


def _fallback_code(serving: bool) -> int:
    """Exit code after a browser fallback.

    0 normally — the user has a working app. In a window-proof run it must be
    non-zero: the whole point of that run is "a native window opened", and a tab
    is not that.
    """
    if os.environ.get("AEGIS_WINDOW_PROOF"):
        return 4
    return 0 if serving else 1


def _navigate_when_ready(window, url: str, *, attempts: int = 40) -> None:
    """Point the window at the app, retrying briefly if the navigation is refused.

    Runs on a daemon thread because ``create_window`` returns before the window
    itself exists; a failure here must never take the app down. If every attempt
    fails the window keeps the page that explains what to do.
    """
    def work() -> None:
        for _ in range(attempts):
            try:
                window.load_url(url)
                return
            except Exception:  # the window is not ready yet
                time.sleep(0.25)

    threading.Thread(target=work, name="aegis-navigate", daemon=True).start()


_STARTING_PAGE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8"><title>Aegis</title>
<style>
  body { margin:0; min-height:100vh; display:grid; place-items:center;
         background:#060b16; color:#e6edf7;
         font:16px/1.6 system-ui, -apple-system, "Segoe UI", sans-serif; }
  main { max-width:32rem; padding:2rem; text-align:center; }
  h1 { font-size:1.3rem; margin:0 0 .6rem; }
  p { margin:.4rem 0; color:#9fb0c9; }
  .dots::after { content:"…"; animation: blink 1.2s steps(2, start) infinite; }
  @keyframes blink { to { visibility:hidden; } }
  code { background:#0f172a; border:1px solid #24314a; border-radius:.4rem;
         padding:.1rem .35rem; color:#7fe7ff; }
</style></head>
<body><main>
  <h1>Aegis is starting<span class="dots"></span></h1>
  <p>This page is replaced as soon as the app answers.</p>
  <p>If it stays here, close the window and run
     <code>Aegis.exe --diagnose</code> — it writes a report that explains why,
     with no key or token in it.</p>
</main></body></html>"""


_ERROR_PAGE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8"><title>Aegis could not start</title>
<style>
  body {{ margin:0; min-height:100vh; display:grid; place-items:center;
         background:#060b16; color:#e6edf7;
         font:16px/1.6 system-ui, -apple-system, "Segoe UI", sans-serif; }}
  main {{ max-width:38rem; padding:2rem; }}
  h1 {{ font-size:1.35rem; margin:0 0 .75rem; }}
  code {{ display:block; white-space:pre-wrap; word-break:break-word;
         background:#0f172a; border:1px solid #24314a; border-radius:.5rem;
         padding:.75rem; margin-top:.75rem; color:#ffb4b4; }}
  p {{ margin:.5rem 0; color:#9fb0c9; }}
</style></head>
<body><main>
  <h1>Aegis could not start</h1>
  <code>{error}</code>
  <p>Full details: {log}</p>
  <p>On Linux the window needs WebKitGTK
     (<code style="display:inline">libwebkit2gtk-4.1-0</code> + <code style="display:inline">python3-gi</code>).
     Run <code style="display:inline">python run.py --self-check</code> to see what is missing,
     or <code style="display:inline">python run.py --web</code> to use the browser instead —
     it is the same app.</p>
</main></body></html>"""


def _error_page(*, error: object, log: str) -> str:
    """Render the crash page with everything HTML-escaped."""
    from html import escape

    return _ERROR_PAGE.format(error=escape(str(error)), log=escape(log or "not written"))
