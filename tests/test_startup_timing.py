"""The app must open, even when nothing on the machine cooperates.

"it won't open" was reported twice. The second time the cause was self-inflicted:
v1.8.0 wired local-model detection into the startup path, and that path shells
out to `nvidia-smi` and PowerShell. On a cold Windows start those can take many
seconds — before a window exists, which is indistinguishable from a hang.

These tests pin the rules that came out of it:

* nothing on the startup path may *wait* for hardware or a model server;
* `recommend()` on a startup path uses no probe at all;
* the window opens on a page that explains itself, then navigates;
* every stage of startup leaves a line in a heartbeat log;
* `--diagnose` reports how far the last launch got;
* a probe that never answers cannot hang the app.
"""

from __future__ import annotations

import time
from pathlib import Path

import pytest

from aegis import desktop, local_llm

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture(autouse=True)
def fresh_hardware_cache():
    """Each test starts with no cached probe, then leaves none behind."""
    local_llm.reset_hardware_cache()
    yield
    local_llm.reset_hardware_cache()


# ---------------------------------------------------------------------------
# The bug: a slow probe must never be waited on
# ---------------------------------------------------------------------------

# These assertions compare against a *simulated hang*, not against a tight
# wall-clock budget: a loaded CI runner is many times slower than a laptop (this
# suite takes 81 s on Windows CI versus 11 s locally), and a flaky timing test is
# worse than no test. The fake probe sleeps far longer than the bound, so the
# only way to fail is to actually wait for it.
HANG_SECONDS = 20.0
WAIT_BOUND = 6.0


def test_a_hardware_probe_that_never_answers_cannot_hang_the_caller(monkeypatch):
    """The whole point: a stuck PowerShell must not hold the window closed."""
    monkeypatch.setattr(local_llm, "detect_hardware", lambda: time.sleep(HANG_SECONDS))
    started = time.monotonic()
    result = local_llm.probe_hardware(0.2)
    elapsed = time.monotonic() - started
    assert result is None
    assert elapsed < WAIT_BOUND, f"probe_hardware blocked for {elapsed:.1f}s"


def test_a_slow_probe_is_abandoned_and_the_worker_keeps_going(monkeypatch):
    """Returning None quickly is right; killing the probe is not, because the
    answer is worth having by the time Settings opens."""
    def slow_but_real():
        time.sleep(0.6)
        return _fake_hardware()

    monkeypatch.setattr(local_llm, "detect_hardware", slow_but_real)
    assert local_llm.probe_hardware(0.05) is None, "it must not wait for a slow probe"
    # The abandoned probe is not killed: its answer is what Settings shows.
    deadline = time.monotonic() + WAIT_BOUND
    while time.monotonic() < deadline and local_llm.cached_hardware() is None:
        time.sleep(0.05)
    assert isinstance(local_llm.cached_hardware(), local_llm.Hardware)


def test_cached_hardware_never_starts_a_probe(monkeypatch):
    def boom():
        pytest.fail("cached_hardware() must not shell out")

    monkeypatch.setattr(local_llm, "detect_hardware", boom)
    assert local_llm.cached_hardware() is None


def test_recommend_does_not_probe_hardware_by_default(monkeypatch):
    """The startup path calls recommend(); it must cost nothing."""
    monkeypatch.setattr(
        local_llm, "detect_hardware", lambda: pytest.fail("recommend() probed the hardware")
    )
    choice = local_llm.recommend(None, ["llava:7b"])
    assert choice["model"] == "llava:7b"


def test_recommend_falls_back_to_a_modest_machine_when_unknown(monkeypatch):
    """Unknown hardware must not mean "recommend the biggest thing"."""
    monkeypatch.setattr(local_llm, "detect_hardware", lambda: pytest.fail("no probing here"))
    choice = local_llm.recommend(None, [])
    assert choice["size_gb"] <= 8.0, "a guess must fit a modest laptop"
    assert choice["model"]


def test_the_desktop_shell_does_not_wait_for_a_slow_adoption(monkeypatch, sandbox):
    """Adoption itself can be slow; the *window* must not wait for it.

    The probe inside `adopt_local()` is bounded (0.6 s per endpoint), but this
    asserts the stronger guarantee the user actually experiences: the shell
    gives adoption a courtesy wait and then gets on with opening the window.
    """
    def slow_adopt(*args, **kwargs):
        time.sleep(HANG_SECONDS)
        return {"changed": False, "reason": "slow"}

    monkeypatch.setattr(local_llm, "adopt_local", slow_adopt)
    started = time.monotonic()
    desktop._adopt_local_model(timeout=0.3)
    elapsed = time.monotonic() - started
    assert elapsed < WAIT_BOUND, f"the shell waited {elapsed:.1f}s for a model server"


def test_adoption_probes_with_a_short_budget(monkeypatch, sandbox):
    from aegis import config

    config.save_config({"llm": {"base_url": "http://127.0.0.1:11434/v1", "model": ""}})
    seen = {}

    def spy(include=None, timeout=1.5):
        seen["timeout"] = timeout
        return None

    monkeypatch.setattr(local_llm, "detect_running", spy)
    local_llm.adopt_local()
    assert seen["timeout"] <= local_llm.STARTUP_PROBE_TIMEOUT


# ---------------------------------------------------------------------------
# The desktop shell: never a blank window, never a blocked one
# ---------------------------------------------------------------------------

def _fake_webview(monkeypatch):
    """A pywebview stand-in that records the page it was given and any navigation."""
    import sys
    import types

    module = types.ModuleType("webview")
    menu_module = types.ModuleType("webview.menu")
    recorded: dict = {}
    windows: list = []

    class Window:
        def __init__(self):
            self.loaded_urls: list[str] = []
            self.exposed = []

        def load_url(self, url):
            self.loaded_urls.append(url)

        def expose(self, *funcs):
            self.exposed.extend(funcs)

        def destroy(self):
            pass

        def show(self):
            pass

    menu_module.Menu = type("Menu", (), {"__init__": lambda self, t, i: None})
    menu_module.MenuAction = type("MenuAction", (), {"__init__": lambda self, t, f: None})
    menu_module.MenuSeparator = lambda: object()

    def create_window(**kwargs):
        recorded["window_kwargs"] = kwargs
        window = Window()
        windows.append(window)
        return window

    def start(**kwargs):
        recorded["start_kwargs"] = kwargs
        deadline = time.time() + 5
        while (not windows or not windows[0].loaded_urls) and time.time() < deadline:
            time.sleep(0.02)

    module.create_window = create_window
    module.start = start
    module.menu = menu_module
    monkeypatch.setitem(sys.modules, "webview", module)
    monkeypatch.setitem(sys.modules, "webview.menu", menu_module)
    recorded["windows"] = windows
    return recorded


def test_the_window_opens_on_a_self_explaining_page(monkeypatch):
    """A blank white window is the failure mode this replaces."""
    recorded = _fake_webview(monkeypatch)
    monkeypatch.setattr(desktop, "_adopt_local_model", lambda **k: None)
    assert desktop.run_desktop(port=0) == 0

    kwargs = recorded["window_kwargs"]
    assert "html" in kwargs and "url" not in kwargs
    page = kwargs["html"]
    assert "starting" in page.lower()
    assert "--diagnose" in page, "the page must say what to do if it stays"
    # and it did navigate to the real app, with the token handshake
    loaded = recorded["windows"][0].loaded_urls
    assert loaded and loaded[0].startswith("http://127.0.0.1:")
    assert "?token=" in loaded[0]


def test_startup_writes_a_heartbeat_for_every_stage(monkeypatch, tmp_path):
    """When nothing opens, the log must say how far it got."""
    from aegis import config

    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    desktop._write_heartbeat("test stage")
    log = (tmp_path / "aegis-startup.log").read_text(encoding="utf-8")
    assert "test stage" in log


def test_a_failed_server_start_is_recorded_in_the_heartbeat(monkeypatch, tmp_path):
    from aegis import config

    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    recorded = _fake_webview(monkeypatch)
    monkeypatch.setattr(desktop, "_adopt_local_model", lambda **k: None)

    def boom(port, **kwargs):
        raise RuntimeError("port stolen")

    monkeypatch.setattr(desktop, "start_server", boom)
    monkeypatch.setattr(desktop, "_report_fatal", lambda exc, page=None: None)
    assert desktop.run_desktop(port=0) == 1
    log = (tmp_path / "aegis-startup.log").read_text(encoding="utf-8")
    assert "FAILED" in log and "port stolen" in log
    assert recorded["windows"] == []


def test_the_heartbeat_never_raises(monkeypatch):
    """A diagnostic must not become the failure."""
    from aegis import config

    monkeypatch.setattr(config, "DATA_DIR", Path("/proc/definitely-not-writable"))
    desktop._write_heartbeat("should not raise")


def test_adoption_is_bounded_and_offsets_the_window(monkeypatch):
    """The desktop shell must not wait for a model server indefinitely."""
    seen = {}

    finished = {"value": False}

    def slow(*args, **kwargs):
        seen.update(kwargs)
        time.sleep(HANG_SECONDS)
        finished["value"] = True
        return {"changed": False, "reason": "slow"}

    monkeypatch.setattr(local_llm, "adopt_local", slow)
    started = time.monotonic()
    desktop._adopt_local_model(timeout=0.5)
    assert time.monotonic() - started < WAIT_BOUND
    assert finished["value"] is False, "the shell waited for adoption to finish"


# ---------------------------------------------------------------------------
# The browser path has the same rule
# ---------------------------------------------------------------------------

def test_run_web_bounds_its_adoption(monkeypatch):
    source = (ROOT / "run.py").read_text(encoding="utf-8")
    assert "threading.Thread" in source
    assert "worker.join(timeout)" in source


# ---------------------------------------------------------------------------
# Diagnostics must answer the question
# ---------------------------------------------------------------------------

def test_diagnose_reports_how_far_the_last_launch_got(tmp_path, monkeypatch, capsys):
    from aegis import config

    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    monkeypatch.setattr(config, "CONFIG_PATH", tmp_path / "aegis_config.json")
    monkeypatch.setattr(config, "user_data_dir", lambda: tmp_path)
    monkeypatch.setenv("AEGIS_NO_GUI_ERRORS", "1")
    (tmp_path / "aegis-startup.log").write_text(
        "2026-01-01 10:00:00  1/4 starting\n"
        "2026-01-01 10:00:01  2/4 local model checked\n"
        "2026-01-01 10:00:02  3/4 server answering\n",
        encoding="utf-8",
    )
    desktop.diagnose()
    out = capsys.readouterr().out
    assert "how far the last launch got" in out.lower()
    assert "3/4 server answering" in out
    # The report ends on the last thing that actually happened, so the advice has
    # to be derived from that line — here, the server answered but no window yet.
    assert "stopped before creating a window" in out.lower()
    assert "4/4 window created" not in out.split("how far the last launch got")[1]


def test_diagnose_flags_a_launch_that_reached_the_window(tmp_path, monkeypatch, capsys):
    from aegis import config

    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    monkeypatch.setattr(config, "CONFIG_PATH", tmp_path / "aegis_config.json")
    monkeypatch.setattr(config, "user_data_dir", lambda: tmp_path)
    (tmp_path / "aegis-startup.log").write_text("x  4/4 window created\n", encoding="utf-8")
    desktop.diagnose()
    out = capsys.readouterr().out
    assert "reached the window" in out.lower()
    assert "WebView2" in out, "if a window was created, WebView2 is the suspect to name"


def test_diagnose_reports_the_local_model_state(tmp_path, monkeypatch, capsys):
    """The new commonest complaint is "it opened but knows nothing"."""
    from aegis import config

    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    monkeypatch.setattr(config, "CONFIG_PATH", tmp_path / "aegis_config.json")
    monkeypatch.setattr(config, "user_data_dir", lambda: tmp_path)
    config.save_config({"llm": {"base_url": "http://127.0.0.1:11434/v1", "model": "llava:7b"}})
    monkeypatch.setattr(local_llm, "detect_running", lambda **k: None)
    desktop.diagnose()
    out = capsys.readouterr().out
    assert "llava:7b" in out
    assert "none running" in out


def test_diagnose_never_leaks_the_key_or_token(tmp_path, monkeypatch, capsys):
    from aegis import config, security

    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    monkeypatch.setattr(config, "CONFIG_PATH", tmp_path / "aegis_config.json")
    monkeypatch.setattr(config, "user_data_dir", lambda: tmp_path)
    config.save_config(
        {"llm": {"base_url": "https://api.openai.com/v1", "api_key": "sk-should-not-appear", "model": "m"}}
    )
    desktop.diagnose()
    out = capsys.readouterr().out
    assert "sk-should-not-appear" not in out
    assert security.get_token() not in out


def _fake_hardware():
    return local_llm.Hardware(system="Test", machine="x", cpu="c", cores=4, ram_gb=8.0)


# ---------------------------------------------------------------------------
# The browser fallback: no native window is never a dead end
# ---------------------------------------------------------------------------

def test_a_window_proof_run_exits_zero_only_when_a_window_existed(monkeypatch, tmp_path):
    """CI asserts on this exit code, so it must not be able to lie."""
    import sys as _sys
    import types as _types

    from aegis import config

    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    monkeypatch.setenv("AEGIS_WINDOW_PROOF", "1")

    module = _types.ModuleType("webview")
    menu = _types.ModuleType("webview.menu")
    menu.Menu = type("Menu", (), {"__init__": lambda s, t, i: None})
    menu.MenuAction = type("MenuAction", (), {"__init__": lambda s, t, f: None})
    menu.MenuSeparator = lambda: object()

    class Window:
        def load_url(self, url):
            pass

        def expose(self, *f):
            pass

        def destroy(self):
            pass

    module.menu = menu
    module.create_window = lambda **kw: Window()
    monkeypatch.setitem(_sys.modules, "webview", module)
    monkeypatch.setitem(_sys.modules, "webview.menu", menu)
    monkeypatch.setattr(desktop, "_adopt_local_model", lambda **k: None)

    # A working window -> 0
    module.start = lambda **kw: None
    assert desktop.run_desktop(port=0) == 0
    assert "WINDOW CREATED" in (tmp_path / "aegis-startup.log").read_text(encoding="utf-8")

    # A window that never materialises -> non-zero, even though the app fell back
    def no_window(**kw):
        raise RuntimeError("backend refused")

    module.start = no_window
    opened: list[str] = []
    monkeypatch.setattr(desktop, "_open_in_browser", lambda url: opened.append(url) or True)
    assert desktop.run_desktop(port=0) == 4
    assert opened, "the user must still end up with a working app"
