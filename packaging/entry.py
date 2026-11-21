"""Bootstrap for the frozen desktop build.

The windowed bundle is started by double-clicking an ``.exe`` with no console,
so anything that fails before a window exists looks to the user like *nothing
happened at all* — which is exactly the bug report we kept getting. Several
different causes produce that same silence:

* a missing or blocked WebView2 runtime (pywebview raises, we open a window…
  except this is why it failed);
* an antivirus or SmartScreen action that kills the process outright;
* an import error inside the bundle (a hidden import PyInstaller missed);
* a redirected AppData/OneDrive config location that is not writable.

Two launches are also a realistic mistake: one already-running copy holds the
port, and the second window shows a login-looking page.

So before any of that can happen, this writes a line-by-line breadcrumb log,
records uncaught exceptions, reports a second launch instead of fighting the
first, and finally offers a visible diagnostic window. Run the exe with
``--self-check`` for a readable report.
"""

from __future__ import annotations

import datetime as _dt
import os
import sys
import traceback

_LOG_NAME = "aegis-startup.log"


def _data_dir() -> object:
    """The per-user data directory, with no dependency on the app package.

    Deliberately duplicated from :mod:`aegis.config` instead of imported: this
    file is the first thing to run, and it must still produce a log when the
    import of the application is what failed.
    """
    from pathlib import Path

    override = os.environ.get("AEGIS_DATA_DIR")
    if override:
        return Path(override).expanduser()
    home = Path.home()
    if sys.platform.startswith("win"):
        base = Path(os.environ.get("APPDATA") or home / "AppData" / "Roaming")
        return base / "Aegis"
    if sys.platform == "darwin":
        return home / "Library" / "Application Support" / "Aegis"
    return Path(os.environ.get("XDG_CONFIG_HOME") or home / ".config") / "aegis"


def _log_path():
    return _data_dir() / _LOG_NAME


def _timestamp() -> str:
    return _dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _write(line: str) -> None:
    """Append one breadcrumb, and never raise while doing it."""
    try:
        path = _log_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        new = not path.exists()
        with open(path, "a", encoding="utf-8") as handle:
            if new:
                handle.write(f"# Aegis startup log — {_timestamp()}\n")
            handle.write(f"{_timestamp()}  {line}\n")
    except Exception:
        pass  # a diagnostic must never become the failure


def _crash(reason: str, exc: BaseException | None = None) -> None:
    """Record a fatal error, then try to show it in a window."""
    _write(f"FATAL: {reason}")
    # A console (or CI) must see it too: a diagnostic that only writes a file is
    # how a fatal error stays invisible in the very runs that would catch it.
    print(f"\nAegis could not start: {reason}\n", file=sys.stderr)
    if exc is not None:
        traceback.print_exception(type(exc), exc, exc.__traceback__)
    if exc is not None:
        _write("".join(traceback.format_exception(type(exc), exc, exc.__traceback__)))

    try:

        path = _data_dir() / "aegis-crash.log"
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(f"{reason}\n\n")
            if exc is not None:
                handle.write("".join(traceback.format_exception(type(exc), exc, exc.__traceback__)))
    except Exception:
        path = None

    # A windowed build has no console, and a user who double-clicked will not go
    # looking for a log. Say it where they are looking.
    if os.environ.get("AEGIS_NO_GUI_ERRORS"):
        return
    try:
        _show_dialog(reason, exc, str(path) if path else "")
    except Exception:
        pass


def _show_dialog(reason: str, exc: BaseException | None, log_file: str) -> None:
    """A native message box, using whatever is available on this platform."""
    detail = f"{reason}"
    if exc is not None:
        detail += f"\n\n{type(exc).__name__}: {exc}"
    log_hint = f"\n\nDetails: {log_file}" if log_file else ""
    if _log_path().exists():
        log_hint += f"\nStartup log: {_log_path()}"
    message = (
        f"Aegis could not start.\n\n{detail}{log_hint}\n\n"
        "Run Aegis.exe --self-check from a terminal for a full report."
    )

    if sys.platform.startswith("win"):
        # No imports beyond ctypes: a dialog is most needed when Qt/Tk are gone.
        import ctypes

        ctypes.windll.user32.MessageBoxW(None, message, "Aegis could not start", 0x10)
        return
    if sys.platform == "darwin":
        import subprocess

        script = (
            'display alert "Aegis could not start" message '
            + _applescript_string(message)
            + " as critical"
        )
        subprocess.run(["osascript", "-e", script], check=False, timeout=15)
        return
    # Linux: try a dialog tool if one is installed, otherwise the log stands.
    import shutil
    import subprocess

    for tool, args in (
        ("zenity", ["--error", "--title", "Aegis could not start", "--text", message]),
        ("kdialog", ["--error", message, "--title", "Aegis could not start"]),
        ("xmessage", ["-center", message]),
    ):
        if shutil.which(tool):
            subprocess.run([tool, *args], check=False, timeout=30)
            return


def _applescript_string(text: str) -> str:
    return '"' + text.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _webview2_status() -> tuple[bool, str]:
    """Is the Edge WebView2 runtime installed? ``(found, detail)``.

    Checked by hand rather than by asking pywebview, because pywebview only
    discovers the runtime when it tries to create a window — after the server has
    started, so its failure is the confusing one. The registry keys are the ones
    Microsoft documents for detection.

    Returns an explicit ``(found, detail)`` pair rather than "a string when the
    runtime is missing": the first version of this returned the *version* on
    success, which the caller read as a failure and refused to start — a bug that
    only appeared on a Windows machine that had WebView2, i.e. almost all of them.
    """
    try:
        import winreg
    except ImportError:  # pragma: no cover - only on Windows
        return True, "not Windows: nothing to check"

    # Note: not raw strings. A raw string cannot end with a backslash, and these
    # key paths are prefix + client, so the prefix needs a trailing separator.
    client = "Microsoft\\EdgeUpdate\\Clients\\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}"
    for root, prefix in (
        (winreg.HKEY_LOCAL_MACHINE, "SOFTWARE\\WOW6432Node\\"),
        (winreg.HKEY_LOCAL_MACHINE, "SOFTWARE\\"),
        (winreg.HKEY_CURRENT_USER, "SOFTWARE\\"),
    ):
        try:
            with winreg.OpenKey(root, prefix + client) as key:
                version = winreg.QueryValueEx(key, "pv")[0]
        except OSError:
            continue
        except Exception:  # noqa: BLE001 - a registry read must never be fatal
            continue
        if version and version != "0.0.0.0":
            return True, f"runtime {version}"

    # Some managed installs have no EdgeUpdate key but do ship the loader.
    for candidate in (
        os.path.expandvars("%ProgramFiles(x86)%\\Microsoft\\EdgeWebView\\Application"),
        os.path.expandvars("%ProgramFiles%\\Microsoft\\EdgeWebView\\Application"),
    ):
        try:
            if candidate and os.path.isdir(candidate):
                return True, candidate
        except Exception:  # noqa: BLE001
            continue
    return False, "no WebView2 runtime in the registry or Program Files"


def _already_running() -> bool:
    """True when another Aegis holds the loopback port we would start on.

    Checked here rather than in the app because "a window opened showing a
    login page" is indistinguishable from "it did not start" to a user, and
    running a second copy is the commonest way to get there.
    """
    import socket

    port = int(os.environ.get("AEGIS_PORT", "8000"))
    probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    probe.settimeout(0.4)
    try:
        return probe.connect_ex(("127.0.0.1", port)) == 0
    except OSError:
        return False
    finally:
        probe.close()


def main() -> int:
    _write("=" * 60)
    _write("bootstrap: starting")
    _write(f"  frozen:   {getattr(sys, 'frozen', False)}")
    _write(f"  exe:      {sys.executable}")
    _write(f"  argv:     {sys.argv[1:]}")
    _write(f"  data dir: {_data_dir()}")

    try:
        import webview

        _write(f"webview:  imported (pywebview {getattr(webview, '__version__', '?')})")
    except Exception as exc:
        _write("webview:  IMPORT FAILED")
        _crash("The desktop window component is missing from this build.", exc)
        return 1

    if sys.platform.startswith("win"):
        found, detail = _webview2_status()
        _write(f"webview2: {'found' if found else 'NOT FOUND'} ({detail})")
        if not found:
            _crash(
                "Aegis needs Microsoft Edge WebView2, which is not installed on "
                "this PC.\n\n"
                "Install it once from Microsoft, then start Aegis again:\n"
                "https://go.microsoft.com/fwlink/p/?LinkId=2124703\n\n"
                "It is a small free download and comes preinstalled on Windows 11 "
                "and on most Windows 10 machines.",
                None,
            )
            return 1

    if len(sys.argv) == 1 and _already_running():
        # Not fatal any more. The app already picks another port when one is
        # busy, so refusing to start turned "open a second window" into "it does
        # not open" — with no window to explain the difference.
        _write("port 8000 is in use: starting on another port instead")

    try:
        from run import main as run_main
    except ImportError:
        # Frozen builds do not always carry run.py as a module: PyInstaller puts
        # the entry script in the archive under a name of its own. Resolving it
        # from the bundle directory and exec'ing it is what makes --self-check
        # and --diagnose work in the packaged app, which is when they matter.
        run_main = _load_run_py()

    try:
        # Housekeeping from a previous update: helper scripts cannot delete
        # themselves safely (see aegis.updates.prune_helpers).
        from aegis.updates import prune_helpers

        for name in prune_helpers():
            _write(f"pruned update helper: {name}")
    except Exception:
        _write("prune: skipped")

    # A "window proof" run: used by CI to prove a real window opens on each OS.
    # It is a normal launch, with a watchdog so a runner cannot hang, and the exit
    # code says whether a window was ever created.
    if "--window-proof" in sys.argv:
        watch = float(os.environ.get("AEGIS_WINDOW_PROOF_SECONDS", "25"))

        def _watchdog() -> None:
            try:
                time.sleep(watch)
            finally:
                _write(f"window-proof: giving up after {watch:.0f}s")
                os._exit(3)  # no window, and no clean shutdown to wait for

        import threading
        import time

        threading.Thread(target=_watchdog, name="aegis-window-proof", daemon=True).start()
        _write(f"window-proof: launching the real window (watchdog {watch:.0f}s)")

    try:
        _write("app:      handing over to run.py")
        _write("app:      importing the server and opening the window")
        return run_main()
    except SystemExit as exc:  # argparse --help, --self-check, etc.
        _write(f"app:      exited with {exc.code}")
        return int(exc.code or 0)
    except BaseException as exc:  # noqa: BLE001 - last line of defence
        _crash("Aegis stopped with an unexpected error.", exc)
        return 1


def _load_run_py():
    """Load ``main`` out of run.py, from the repository or the bundle."""
    import runpy
    from pathlib import Path

    candidates = []
    # Source layout: packaging/entry.py next to run.py.
    candidates.append(Path(__file__).resolve().parent.parent / "run.py")
    # Frozen layout: the contents of a --add-data "run.py;." bundle.
    bundle = getattr(sys, "_MEIPASS", None)
    if bundle:
        candidates.append(Path(bundle) / "run.py")
    candidates.append(Path(__file__).resolve().parent / "run.py")

    for candidate in candidates:
        if candidate.is_file():
            # Running entry.py as a script puts packaging/ (not the repository)
            # on sys.path, so the app package would not be importable from it.
            repo = str(candidate.parent)
            if repo not in sys.path:
                sys.path.insert(0, repo)
            return runpy.run_path(str(candidate))["main"]
    raise ImportError("run.py is missing from this build")


if __name__ == "__main__":
    sys.exit(main())
