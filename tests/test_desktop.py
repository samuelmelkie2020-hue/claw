"""The desktop shell.

The window itself cannot be opened in CI (no display, and WebKitGTK is not
installed), so these tests drive the shell with a fake webview. That covers the
parts that actually break: the threading model, port selection, readiness
polling, the JS bridge, and shutdown.

`run.py --self-check` covers the rest against a real frozen build.
"""

from __future__ import annotations

import sys
import threading
import types
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Paths: a bundled app must not write into its own bundle
# ---------------------------------------------------------------------------

def test_source_mode_keeps_config_beside_the_repo(monkeypatch):
    """From source, settings stay in the checkout — not in a per-user folder.

    Asserted by comparing against the package root, not by rejecting the name
    "Aegis": the repository is called Aegis now, so a CI checkout legitimately
    ends in a directory of that name and a name-based assertion was asserting
    the old repo's name.
    """
    from aegis import config

    monkeypatch.delenv("AEGIS_DATA_DIR", raising=False)
    monkeypatch.setattr(config, "is_frozen", lambda: False)

    source_root = Path(config.__file__).resolve().parent.parent
    assert config.user_data_dir() == source_root
    assert "Claw" not in config.user_data_dir().parts


@pytest.mark.parametrize(
    "platform_name,env,expected_parts",
    [
        ("Windows", {"APPDATA": "/fake/appdata"}, ("Aegis",)),
        ("Darwin", {}, ("Library", "Application Support", "Aegis")),
        ("Linux", {"XDG_CONFIG_HOME": "/fake/xdg"}, ("fake", "xdg", "Aegis")),
    ],
)
def test_frozen_app_uses_the_per_user_location(monkeypatch, platform_name, env, expected_parts):
    from aegis import config

    monkeypatch.delenv("AEGIS_DATA_DIR", raising=False)
    monkeypatch.setattr(config, "is_frozen", lambda: True)
    monkeypatch.setattr(config.platform, "system", lambda: platform_name)
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    if platform_name == "Linux":
        monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
        monkeypatch.setenv("XDG_CONFIG_HOME", "/fake/xdg")

    path = config.user_data_dir()
    for part in expected_parts:
        assert part in path.parts, f"{path} missing {part}"
    # never inside the bundle / site-packages
    assert "site-packages" not in str(path)


def test_data_dir_can_be_overridden(monkeypatch, tmp_path):
    from aegis import config

    monkeypatch.setenv("AEGIS_DATA_DIR", str(tmp_path / "custom"))
    assert config.user_data_dir() == tmp_path / "custom"


def test_is_frozen_reads_pyinstaller_marker(monkeypatch):
    from aegis import config

    monkeypatch.delattr(sys, "frozen", raising=False)
    assert config.is_frozen() is False
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    assert config.is_frozen() is True


# ---------------------------------------------------------------------------
# Port selection
# ---------------------------------------------------------------------------

def test_preferred_port_is_used_when_free():
    from aegis.desktop import find_free_port

    port = find_free_port(0)
    assert 1024 < port < 65536
    assert find_free_port(port) == port


def test_busy_port_falls_back_instead_of_crashing():
    """A second launch used to die with "address already in use"."""
    import socket

    from aegis.desktop import find_free_port

    taken = socket.socket()
    taken.bind(("127.0.0.1", 0))
    taken.listen(1)
    busy = taken.getsockname()[1]
    try:
        chosen = find_free_port(busy)
        assert chosen != busy
        assert chosen > 0
    finally:
        taken.close()


# ---------------------------------------------------------------------------
# Server lifecycle
# ---------------------------------------------------------------------------

def test_server_thread_serves_the_app_and_stops_cleanly():
    from aegis.desktop import find_free_port, start_server, stop_server

    handle = start_server(find_free_port(0))
    try:
        import urllib.error
        import urllib.request

        from aegis.security import get_token

        # unauthenticated: the socket is live and correctly refuses
        with pytest.raises(urllib.error.HTTPError) as excinfo:
            urllib.request.urlopen(f"{handle.base_url}/api/health", timeout=5)
        assert excinfo.value.code == 401

        request = urllib.request.Request(
            f"{handle.base_url}/api/health", headers={"X-Aegis-Token": get_token()}
        )
        with urllib.request.urlopen(request, timeout=5) as response:
            assert response.status == 200
    finally:
        stop_server(handle)
    assert not handle.thread.is_alive()


def test_server_runs_in_a_background_thread():
    from aegis.desktop import find_free_port, start_server, stop_server

    handle = start_server(find_free_port(0))
    try:
        assert handle.thread.daemon is True
        assert handle.thread is not threading.main_thread()
    finally:
        stop_server(handle)


def test_stop_server_is_idempotent():
    from aegis.desktop import stop_server

    stop_server(None)  # must not raise


# ---------------------------------------------------------------------------
# The JS bridge
# ---------------------------------------------------------------------------

class FakeWindow:
    def __init__(self):
        self.shown = False
        self.minimized = False
        self.evaluated: list[str] = []
        self.exposed = []
        self.loaded_urls: list[str] = []

    def load_url(self, url):
        """The real app opens on a "starting" page and swaps in the app URL."""
        self.loaded_urls.append(url)

    def show(self):
        self.shown = True

    def restore(self):
        self.minimized = False

    def evaluate_js(self, script):
        self.evaluated.append(script)

    def expose(self, *funcs):
        self.exposed.extend(funcs)


def test_bridge_reports_desktop_and_version():
    from aegis.desktop import DesktopAPI

    info = DesktopAPI().info()
    assert info["desktop"] is True
    assert "version" in info


def test_bridge_drives_the_page_not_the_other_way_round():
    from aegis.desktop import DesktopAPI

    api = DesktopAPI()
    window = FakeWindow()
    api.attach(window)

    api.open_settings()
    api.new_conversation()

    assert window.shown
    assert any("OpenSettings" in s for s in window.evaluated)
    assert any("NewChat" in s for s in window.evaluated)


def test_bridge_is_a_no_op_before_the_window_exists():
    from aegis.desktop import DesktopAPI

    api = DesktopAPI()
    api.open_settings()      # must not raise
    api.new_conversation()


def test_bridge_survives_a_failing_page():
    from aegis.desktop import DesktopAPI

    class Broken(FakeWindow):
        def evaluate_js(self, script):
            raise RuntimeError("no page yet")

    api = DesktopAPI()
    api.attach(Broken())
    api.open_settings()  # must not raise


# ---------------------------------------------------------------------------
# Startup path, with a fake webview
# ---------------------------------------------------------------------------

@pytest.fixture()
def fake_webview(monkeypatch):
    """A stand-in for pywebview that records how it was started."""
    recorded = {}

    module = types.ModuleType("webview")
    menu_module = types.ModuleType("webview.menu")

    class _Action:
        def __init__(self, title, func):
            self.title, self.func = title, func

    class _Menu:
        def __init__(self, title, items):
            self.title, self.items = title, items

    menu_module.Menu = _Menu
    menu_module.MenuAction = _Action
    menu_module.MenuSeparator = lambda: object()

    class Window(FakeWindow):
        pass

    created: list[Window] = []

    def create_window(**kwargs):
        recorded["window_kwargs"] = kwargs
        window = Window()
        created.append(window)
        recorded["window"] = window
        return window

    def start(**kwargs):
        recorded["start_kwargs"] = kwargs
        # The window opens on a local "starting" page and is navigated to the app
        # once the server answers, so that is where the token handshake lives.
        import time

        deadline = time.time() + 5
        while not created[0].loaded_urls and time.time() < deadline:
            time.sleep(0.02)
        recorded["url_opened"] = created[0].loaded_urls[0] if created[0].loaded_urls else None
        if recorded["url_opened"]:
            import urllib.request

            try:
                urllib.request.urlopen(recorded["url_opened"], timeout=5)
            except Exception:
                pass

    module.create_window = create_window
    module.start = start
    module.menu = menu_module
    module.Window = Window

    monkeypatch.setitem(sys.modules, "webview", module)
    monkeypatch.setitem(sys.modules, "webview.menu", menu_module)
    return recorded


def test_desktop_opens_a_window_on_a_loopback_token_url(fake_webview):
    from aegis.desktop import run_desktop

    assert run_desktop(port=0) == 0

    url = fake_webview["url_opened"]
    assert url.startswith("http://127.0.0.1:")
    assert "?token=" in url, "the desktop shell must take the token handshake itself"

    kwargs = fake_webview["start_kwargs"]
    assert kwargs["http_server"] is False, "uvicorn serves the app, not pywebview"
    assert kwargs["private_mode"] is False


def test_window_title_is_just_the_app_name(fake_webview):
    """Taskbars and the Dock already show the icon; a suffix just truncates."""
    from aegis.desktop import run_desktop

    run_desktop(port=0)
    assert fake_webview["window_kwargs"]["title"] == "Aegis"


def test_desktop_window_is_configured_as_an_app(fake_webview):
    from aegis.desktop import MIN_SIZE, run_desktop

    run_desktop(port=0)
    kwargs = fake_webview["window_kwargs"]
    assert kwargs["min_size"] == MIN_SIZE
    assert kwargs["confirm_close"] is True
    assert kwargs["js_api"] is not None
    assert kwargs["title"].startswith("Aegis")


def test_missing_pywebview_explains_the_two_options(monkeypatch, capsys):
    from aegis.desktop import run_desktop

    monkeypatch.setitem(sys.modules, "webview", None)
    assert run_desktop(port=0) == 1
    out = capsys.readouterr().out
    assert "pip install pywebview" in out
    assert "--web" in out


def test_self_check_writes_a_report_for_console_less_builds(capsys):
    """A `console=False` bundle has nowhere to print, so the result lands on disk."""
    from aegis.config import DATA_DIR
    from aegis.desktop import self_check

    assert self_check() == 0
    capsys.readouterr()

    report = (DATA_DIR / "self-check.txt").read_text(encoding="utf-8")
    assert "Aegis" in report
    assert "frozen:" in report
    assert "All checks passed" in report


def test_ensure_streams_survives_a_windowed_build(monkeypatch):
    """PyInstaller's windowed build sets sys.stdout/stderr to None; printing must not crash."""
    import aegis.desktop as desktop

    monkeypatch.setattr(sys, "stdout", None)
    monkeypatch.setattr(sys, "stderr", None)
    desktop._ensure_streams()
    assert sys.stdout is not None and sys.stderr is not None
    print("ok")  # would raise AttributeError without the fix


def test_self_check_entry_point_runs(capsys):
    from aegis.desktop import self_check

    assert self_check() == 0
    out = capsys.readouterr().out
    assert "All checks passed" in out
    assert "settings:" in out


# ---------------------------------------------------------------------------
# Startup failures must be visible in a windowed (no-console) build
# ---------------------------------------------------------------------------

class _RecordingWebview(types.ModuleType):
    """pywebview stand-in that records windows and can fail to start."""

    def __init__(self, start_error=None):
        super().__init__("webview")
        self.windows: list[dict] = []
        self.start_calls: list[dict] = []
        self.start_error = start_error

    def create_window(self, *args, **kwargs):
        self.windows.append({"args": args, **kwargs})
        return FakeWindow()

    def start(self, **kwargs):
        self.start_calls.append(kwargs)
        if self.start_error:
            raise self.start_error


def test_fatal_server_error_leaves_a_log_and_does_not_hang(monkeypatch, tmp_path):
    """A server that cannot start must explain itself, with or without a display."""
    import aegis.desktop as desktop

    shown = []

    class _QuietWebview(types.ModuleType):
        """Records the error window; `start` returns immediately, as in CI."""

        def __init__(self):
            super().__init__("webview")

        def create_window(self, *args, **kwargs):
            shown.append({"args": args, **kwargs})
            return FakeWindow()

        def start(self, **kwargs):
            return None

    monkeypatch.setitem(sys.modules, "webview", _QuietWebview())
    monkeypatch.setattr(desktop, "start_server", _raise(RuntimeError("boom")))
    monkeypatch.setattr("aegis.config.DATA_DIR", tmp_path)

    assert desktop.run_desktop(port=0) == 1

    assert "RuntimeError: boom" in (tmp_path / "aegis-crash.log").read_text(encoding="utf-8")
    # A display may or may not be available; if a window was opened it must be
    # the explanation, never the app.
    assert [w["args"][0] for w in shown] in ([], ["Aegis could not start"])


def test_webview_failure_falls_back_to_the_browser(monkeypatch, tmp_path):
    """No native window is not a dead end.

    A missing/broken WebView2, a locked-down machine or an antivirus can all stop
    the native window while the server is perfectly healthy. The user must end up
    with a working app *and* a plain-language reason, not a process that exits.
    """
    import aegis.desktop as desktop

    fake = _RecordingWebview(start_error=RuntimeError("no display"))
    monkeypatch.setitem(sys.modules, "webview", fake)
    monkeypatch.setitem(sys.modules, "tkinter", None)
    monkeypatch.setitem(sys.modules, "tkinter.messagebox", None)
    monkeypatch.setattr("aegis.config.DATA_DIR", tmp_path)
    opened: list[str] = []
    monkeypatch.setattr(desktop, "_open_in_browser", lambda url: opened.append(url) or True)
    monkeypatch.setattr(desktop, "_keep_serving", lambda handle, **k: True)

    assert desktop.run_desktop(port=0, keep_serving=False) == 0

    assert fake.windows[0]["title"] == "Aegis"
    assert opened and opened[0].startswith("http://127.0.0.1:")
    assert "?token=" in opened[0], "the browser tab needs the token handshake"
    log = (tmp_path / "aegis-startup.log").read_text(encoding="utf-8")
    assert "window FAILED" in log and "no display" in log
    assert "using the browser instead" in log


def test_with_no_browser_either_the_url_is_written_down(monkeypatch, tmp_path):
    """The server is alive; the address must not be lost with the process."""
    import aegis.desktop as desktop

    fake = _RecordingWebview(start_error=RuntimeError("WebView2 missing"))
    monkeypatch.setitem(sys.modules, "webview", fake)
    monkeypatch.setattr("aegis.config.DATA_DIR", tmp_path)
    monkeypatch.setattr(desktop, "_open_in_browser", lambda url: False)
    monkeypatch.setattr(desktop, "_keep_serving", lambda handle, **k: True)

    assert desktop.run_desktop(port=0, keep_serving=False) == 0
    note = (tmp_path / "aegis-open-me.txt").read_text(encoding="utf-8")
    assert "WebView2 missing" in note
    assert "http://127.0.0.1:" in note and "?token=" in note


def test_a_failing_page_bridge_cannot_stop_the_window(monkeypatch, tmp_path):
    """Losing the JS bridge or the menu is a nuisance, not a broken app."""
    import aegis.desktop as desktop

    class _BadBridge(FakeWindow):
        def expose(self, *funcs):
            raise RuntimeError("inspect failed on a partially built window")

        def load_url(self, url):
            raise RuntimeError("window not ready")

    class _Module(types.ModuleType):
        def __init__(self):
            super().__init__("webview")
            self.windows = []

        def create_window(self, *args, **kwargs):
            self.windows.append(kwargs)
            return _BadBridge()

        def start(self, **kwargs):
            pass

    fake = _Module()
    monkeypatch.setitem(sys.modules, "webview", fake)
    monkeypatch.setattr("aegis.config.DATA_DIR", tmp_path)
    opened: list[str] = []
    monkeypatch.setattr(desktop, "_open_in_browser", lambda url: opened.append(url) or True)

    # The window "opens" even though every optional step failed; no fallback.
    assert desktop.run_desktop(port=0) == 0
    assert opened == []


def test_a_failing_error_window_still_leaves_a_log(monkeypatch, tmp_path):
    """If even the error window cannot open (headless), the log is the record."""
    import aegis.desktop as desktop

    class _BrokenWebview(types.ModuleType):
        def __init__(self):
            super().__init__("webview")

        def create_window(self, *args, **kwargs):
            raise RuntimeError("no backend")

        def start(self, **kwargs):  # pragma: no cover - never reached
            raise AssertionError("should not start")

    monkeypatch.setitem(sys.modules, "webview", _BrokenWebview())
    monkeypatch.setattr("aegis.config.DATA_DIR", tmp_path)
    opened: list[str] = []
    monkeypatch.setattr(desktop, "_open_in_browser", lambda url: opened.append(url) or True)
    monkeypatch.setattr(desktop, "_keep_serving", lambda handle, **k: True)

    # Even when the window cannot be *constructed*, the app ends up somewhere
    # usable — the same fallback that covers a window that fails to start.
    assert desktop.run_desktop(port=0) == 0
    assert opened and "?token=" in opened[0]
    assert "no backend" in (tmp_path / "aegis-startup.log").read_text(encoding="utf-8")


def test_error_window_cannot_block_forever(monkeypatch):
    """`webview.start()` may hang instead of raising; the crash path must not."""
    import time

    import aegis.desktop as desktop

    class _HangingWebview(types.ModuleType):
        def start(self, **kwargs):
            time.sleep(30)

    monkeypatch.setattr(desktop, "ERROR_WINDOW_TIMEOUT", 0.2)
    started = time.monotonic()
    desktop._show_without_blocking(_HangingWebview("webview"))
    assert time.monotonic() - started < 5


def test_headless_env_skips_the_error_window(monkeypatch, tmp_path):
    """CI has nobody to close a window, so the log is the only useful output."""
    import aegis.desktop as desktop

    fake = _RecordingWebview(start_error=RuntimeError("headless"))
    monkeypatch.setitem(sys.modules, "webview", fake)
    monkeypatch.setenv("AEGIS_NO_GUI_ERRORS", "1")
    monkeypatch.setattr("aegis.config.DATA_DIR", tmp_path)
    monkeypatch.setattr(desktop, "_open_in_browser", lambda url: True)

    # In CI the fallback still runs (the app must be reachable) but it never
    # waits: AEGIS_NO_GUI_ERRORS turns the "keep serving" wait off.
    assert desktop.run_desktop(port=0) == 0
    assert len(fake.windows) == 1                   # only the app window: no dialog...
    assert "headless" in (tmp_path / "aegis-startup.log").read_text(encoding="utf-8")


def test_error_page_escapes_the_message():
    from aegis.desktop import _error_page

    html = _error_page(error="<script>alert(1)</script>", log="/tmp/<x>.log")
    assert "<script>" not in html
    assert "&lt;script&gt;" in html
    assert "/tmp/&lt;x&gt;.log" in html


def _raise(exc):
    def boom(*_args, **_kwargs):
        raise exc

    return boom


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def test_cli_defaults_to_desktop(monkeypatch):
    import run as runner

    calls = {}
    monkeypatch.setattr(
        "aegis.desktop.run_desktop",
        lambda **kwargs: calls.update(kwargs) or 0,
    )
    assert runner.main([]) == 0
    assert "port" in calls and "debug" in calls


def test_cli_web_flag_serves_instead(monkeypatch):
    import run as runner

    calls = {}
    monkeypatch.setattr(
        runner, "run_web", lambda host, port, open_browser: calls.update(
            {"host": host, "port": port, "open": open_browser}) or 0
    )
    assert runner.main(["--web", "--no-open", "--port", "8123"]) == 0
    assert calls == {"host": "127.0.0.1", "port": 8123, "open": False}


def test_cli_host_flag_is_honoured(monkeypatch):
    import run as runner

    seen = {}
    monkeypatch.setattr(runner, "run_web", lambda host, port, open_browser: seen.update(
        {"host": host, "port": port}) or 0)
    runner.main(["--web", "--host", "0.0.0.0", "--no-open"])
    assert seen["host"] == "0.0.0.0"


def test_self_check_flag_short_circuits(monkeypatch):
    import run as runner

    monkeypatch.setattr("aegis.desktop.self_check", lambda: 0)
    assert runner.main(["--self-check"]) == 0


def test_a_test_double_never_blocks_on_a_browser_fallback(monkeypatch, tmp_path):
    """Regression: a fallback that waits can hang CI for the whole job.

    `run_desktop()` defaults to not keeping the server alive, and the CI marker
    forces it off, so no test — present or future — can accidentally wait on a
    browser tab that nobody is going to close.
    """
    import aegis.desktop as desktop

    fake = _RecordingWebview(start_error=RuntimeError("no window backend"))
    monkeypatch.setitem(sys.modules, "webview", fake)
    monkeypatch.setattr("aegis.config.DATA_DIR", tmp_path)
    monkeypatch.setattr(desktop, "_open_in_browser", lambda url: True)
    monkeypatch.setenv("AEGIS_NO_GUI_ERRORS", "1")  # as the build job sets it

    import inspect

    signature = inspect.signature(desktop.run_desktop)
    assert signature.parameters["keep_serving"].default is False

    started = __import__("time").monotonic()
    assert desktop.run_desktop(port=0) == 0
    assert __import__("time").monotonic() - started < 30


# ---------------------------------------------------------------------------
# The bug that made every platform fail: a keyword this pywebview does not have
# ---------------------------------------------------------------------------

def test_window_options_are_filtered_to_what_this_pywebview_accepts():
    """`create_window(icon=...)` raised on every OS and no window ever opened.

    `requirements.txt` allows pywebview 5.x and 6.x, and `icon` moved from
    `create_window()` to `start()` between them. A cosmetic icon must not be able
    to close the window.
    """
    import inspect
    import sys

    from aegis import desktop

    webview = sys.modules.get("webview") or __import__("webview")
    wanted = {"title": "Aegis", "icon": "/tmp/i.png", "nonsense": 1}
    kept = desktop._supported_kwargs(webview.create_window, wanted)

    create_params = inspect.signature(webview.create_window).parameters
    assert "title" in kept
    assert set(kept) <= set(create_params)
    if "icon" not in create_params:
        assert "icon" not in kept


def test_an_unfiltered_keyword_is_exactly_what_broke_it():
    """Pin the failure: passing an unknown keyword raises, filtering does not."""

    def create_window(title, html):  # a 6.x-shaped signature
        return {"title": title, "html": html}

    from aegis import desktop

    with pytest.raises(TypeError):
        create_window(title="Aegis", html="x", icon="/tmp/i.png")

    filtered = desktop._supported_kwargs(create_window, {"title": "Aegis", "html": "x", "icon": "/p"})
    assert create_window(**filtered) == {"title": "Aegis", "html": "x"}


def test_the_desktop_shell_opens_with_the_installed_pywebview_signature(monkeypatch):
    """End to end against the *real* signature, not a fake one that accepts anything."""
    import sys

    from aegis import desktop

    webview = __import__("webview")
    recorded = {}
    real_create = webview.create_window

    def create_window(**kwargs):
        # Enforce the real signature: an extra keyword must raise here, as it did.
        import inspect

        params = inspect.signature(real_create).parameters
        if not any(p.kind is p.VAR_KEYWORD for p in params.values()):
            unexpected = set(kwargs) - set(params)
            assert not unexpected, f"unknown keyword(s): {sorted(unexpected)}"
        recorded["window_kwargs"] = kwargs
        return FakeWindow()

    def start(**kwargs):
        recorded["start_kwargs"] = kwargs

    monkeypatch.setattr(webview, "create_window", create_window)
    monkeypatch.setattr(webview, "start", start)
    monkeypatch.setitem(sys.modules, "webview", webview)
    assert desktop.run_desktop(port=0) == 0
    assert recorded["window_kwargs"]["title"] == "Aegis"
    assert recorded["start_kwargs"]["http_server"] is False


def test_a_legacy_code_page_cannot_stop_the_app_from_opening(monkeypatch):
    """The exact Windows failure: printing the banner raised UnicodeEncodeError.

    A real console on Windows can be cp1252, where U+1F6E1 has no mapping. The
    startup banner was the last line before the window was created, so the app
    died with a perfectly healthy server behind it.
    """
    import io

    from aegis import desktop

    stream = io.TextIOWrapper(io.BytesIO(), encoding="cp1252", errors="strict", newline="")
    monkeypatch.setattr(__import__("sys"), "stdout", stream)

    stream.write("\n  now the banner:\n")  # ascii is fine
    with pytest.raises(UnicodeEncodeError):
        stream.write("\n  🛡 Aegis is running\n")  # this is what used to happen

    desktop._ensure_streams()
    desktop._print_safe("\n  🛡 Aegis is running")  # must not raise
    desktop._print_safe("plain text is unaffected")


def test_the_startup_banner_goes_through_the_safe_printer():
    source = (Path(__file__).resolve().parent.parent / "aegis" / "desktop.py").read_text(
        encoding="utf-8"
    )
    assert "_print_safe(f\"\\n  🛡" in source, "the emoji banner must use _print_safe"
    assert "print(f\"\\n  🛡" not in source


def test_the_linux_bundle_carries_gtk_typelibs():
    """"You must have either QT or GTK …" is a broken bundle, not a broken PC."""
    spec = (Path(__file__).resolve().parent.parent / "packaging" / "aegis.spec").read_text(
        encoding="utf-8"
    )
    assert "collect_typelib_data" in spec
    assert "gi.repository.Gtk" in spec
    assert "WebKit2-4.1" in spec
    assert "list(_typelibs)" in spec, "the typelibs must actually reach datas"


def test_the_window_proof_records_the_window_without_killing_the_process(monkeypatch, tmp_path):
    """A GUI process must not be killed from a thread to "prove" it worked.

    Doing that is what produced a CLR abort on Windows (0xE0434352) and a Cocoa
    loop that refused to end on macOS — both while a real window was open. The
    evidence is the log line; the runner stops the process afterwards.
    """
    import sys
    import types

    from aegis import config, desktop

    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    monkeypatch.setenv("AEGIS_WINDOW_PROOF", "1")
    monkeypatch.setenv("AEGIS_WINDOW_PROOF_SECONDS", "0.05")
    exits: list[int] = []
    monkeypatch.setattr(desktop.os, "_exit", lambda code: exits.append(code))

    module = types.ModuleType("webview")
    menu = types.ModuleType("webview.menu")
    menu.Menu = type("Menu", (), {"__init__": lambda s, t, i: None})
    menu.MenuAction = type("MenuAction", (), {"__init__": lambda s, t, f: None})
    menu.MenuSeparator = lambda: object()

    class Window:
        def load_url(self, url):
            pass

        def expose(self, *f):
            pass

        def destroy(self):
            pass  # deliberately does NOT stop the process: that is the point

    module.menu = menu
    module.create_window = lambda **kw: Window()
    module.start = lambda **kw: __import__("time").sleep(0.4)  # a loop that does not end
    monkeypatch.setitem(sys.modules, "webview", module)
    monkeypatch.setitem(sys.modules, "webview.menu", menu)
    monkeypatch.setattr(desktop, "_adopt_local_model", lambda **k: None)

    assert desktop.run_desktop(port=0) == 0
    log = (tmp_path / "aegis-startup.log").read_text(encoding="utf-8")
    assert "WINDOW CREATED" in log
    assert "window is open and serving" in log
    assert exits == [], "the process must be stopped by the runner, not by itself"
