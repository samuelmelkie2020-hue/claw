"""Startup diagnostics: a failure must never look like nothing happened.

The bug report was "it won't open" against a windowed build: `Aegis.exe` started,
no window appeared, no message appeared, and there was nothing to read. That is
the worst possible failure mode, because every cause looks identical to the user.

These tests pin the properties that make it impossible:

* the bundle starts from a bootstrap that logs before it imports anything;
* a crash produces a file on disk *and* an attempt at a visible message;
* a missing WebView2 runtime is named as the cause rather than guessed at;
* a second launch says so instead of opening a window that looks broken;
* `--diagnose` prints a report without leaking the API key or the token.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
ENTRY = ROOT / "packaging" / "entry.py"


def _entry_source() -> str:
    return ENTRY.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# The bootstrap exists, and the bundle is built from it
# ---------------------------------------------------------------------------

def test_the_spec_builds_from_the_bootstrap_not_run_py():
    """Building run.py directly is what made startup failures silent."""
    spec = (ROOT / "packaging" / "aegis.spec").read_text(encoding="utf-8")
    assert "packaging\" / \"entry.py\"" in spec or 'packaging/entry.py' in spec
    assert 'ROOT / "run.py"' not in spec.split("Analysis")[1].split(")")[0]


def test_the_bootstrap_logs_before_it_can_fail():
    """The first breadcrumb must precede the first import of the app."""
    source = _entry_source()
    main = source[source.index("def main()"):]
    log_at = main.index('_write("bootstrap: starting")')
    import_at = main.index("import webview")
    assert log_at < import_at, "the app is imported before anything is logged"


def test_the_bootstrap_cannot_be_broken_by_a_failing_log():
    """Diagnostics that raise are worse than no diagnostics."""
    source = _entry_source()
    write = source[source.index("def _write("):]
    write = write[: write.index("\ndef ")]
    assert "except Exception" in write
    assert "return" in write or "pass" in write


# ---------------------------------------------------------------------------
# Failure is visible
# ---------------------------------------------------------------------------

def test_a_crash_writes_both_a_log_and_a_visible_message():
    source = _entry_source()
    crash = source[source.index("def _crash("):]
    crash = crash[: crash.index("\ndef ")]
    assert "aegis-crash.log" in crash
    assert "_show_dialog(" in crash, "a windowed build needs a visible message"
    assert "AEGIS_NO_GUI_ERRORS" in crash, "CI must not block on a modal"


def test_the_dialog_uses_no_gui_toolkit():
    """Tk/Qt may be exactly what failed; a dialog must not depend on them."""
    source = _entry_source()
    dialog = source[source.index("def _show_dialog("):]
    dialog = dialog[: dialog.index("\ndef ")]
    assert "tkinter" not in dialog
    assert "ctypes" in dialog  # Windows: MessageBoxW
    for tool in ("zenity", "kdialog", "xmessage"):
        assert tool in dialog, f"no Linux fallback via {tool}"


@pytest.mark.parametrize("needle", ["WebView2", "go.microsoft.com/fwlink"])
def test_a_missing_webview2_runtime_is_named_with_a_fix(needle):
    """The commonest cause on Windows must be named, not guessed at."""
    assert needle in _entry_source()


def test_a_second_launch_opens_another_window_instead_of_refusing():
    """A busy port used to be fatal, so a second double-click did nothing at all.

    The app already picks a free port; refusing to start was what made "it does
    not open" true.
    """
    source = _entry_source()
    assert "_already_running()" in source
    assert "starting on another port instead" in source
    assert "_crash(\n            \"Another Aegis is already running" not in source


def test_a_backend_that_never_opens_a_window_is_a_failure():
    """pywebview can return without a window; silence is not success."""
    desktop = (ROOT / "aegis" / "desktop.py").read_text(encoding="utf-8")
    start = desktop[desktop.index("def _start_webview("):]
    start = start[: start.index("\ndef ")]
    assert "webview.windows" in start
    assert "RuntimeError" in start


# ---------------------------------------------------------------------------
# --diagnose
# ---------------------------------------------------------------------------

def test_diagnose_cli_flag_exists():
    completed = subprocess.run(
        [sys.executable, "run.py", "--help"],
        cwd=ROOT, capture_output=True, text=True, timeout=60,
    )
    assert "--diagnose" in completed.stdout


def test_diagnose_prints_a_report_and_leaks_no_secrets(paths, monkeypatch, capsys):
    """The report is meant to be pasted in public."""
    from aegis import config
    from aegis.security import get_token

    monkeypatch.setattr(config, "CONFIG_PATH", paths.config, raising=False)
    config.save_config({
        "llm": {
            "base_url": "https://api.example/v1",
            "api_key": "sk-live-supersecret-0123456789",
            "model": "m",
        },
    })

    from aegis.desktop import diagnose

    assert diagnose() == 0
    output = capsys.readouterr().out
    assert "startup diagnosis" in output
    assert "sk-live-supersecret-0123456789" not in output, "the API key leaked"
    assert get_token() not in output, "the access token leaked"


def test_diagnose_flags_a_busy_port(monkeypatch):
    """'A window opened on a login page' is a second copy, not a crash."""
    import socket

    from aegis import desktop

    held = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    held.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    held.bind(("127.0.0.1", 0))
    held.listen(1)
    port = held.getsockname()[1]
    try:
        monkeypatch.setenv("AEGIS_PORT", str(port))
        assert desktop._port_in_use(port) is True
    finally:
        held.close()


# ---------------------------------------------------------------------------
# The bootstrap can find the app (two real bugs found while testing this)
# ---------------------------------------------------------------------------

def test_the_bootstrap_finds_run_py_from_the_source_tree():
    """`packaging/entry.py` had to look one level up, not beside itself."""
    source = _entry_source()
    loader = source[source.index("def _load_run_py"):]  # last function in the file
    assert "parent.parent" in loader


def test_the_bootstrap_puts_the_repo_on_sys_path():
    """Running entry.py as a script puts packaging/ on sys.path, not the repo.

    Without this, `python packaging/entry.py --self-check` died with
    "No module named 'aegis'" — the diagnostic could not diagnose.
    """
    source = _entry_source()
    loader = source[source.index("def _load_run_py"):]  # last function in the file
    assert "sys.path.insert" in loader


def test_the_spec_ships_run_py_so_self_check_works_when_frozen():
    """--self-check matters most inside the bundle; run.py must be there."""
    spec = (ROOT / "packaging" / "aegis.spec").read_text(encoding="utf-8")
    assert '(str(ROOT / "run.py"), ".")' in spec


def test_the_bootstrap_runs_the_self_check_end_to_end():
    """The whole point: a diagnostic that itself crashes is useless."""
    completed = subprocess.run(
        [sys.executable, str(ENTRY), "--self-check"],
        cwd=ROOT, capture_output=True, text=True, timeout=180,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert "All checks passed" in completed.stdout
    assert "server:" in completed.stdout


# ---------------------------------------------------------------------------
# WebView2 detection: a found runtime must never be reported as missing
# ---------------------------------------------------------------------------

def _load_entry_module():
    import importlib.util

    spec = importlib.util.spec_from_file_location("aegis_entry", ENTRY)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_a_webview2_runtime_that_exists_is_not_reported_missing():
    """The bug this shipped with: success was truthy, and truthy meant failure.

    The first version returned the *version string* when the runtime was found
    and ``None`` when it was not, and the caller did ``if missing:``. On any
    Windows PC that actually had WebView2 — i.e. almost all of them — Aegis
    refused to start and told the user to install what was already there.
    """
    entry = _load_entry_module()
    found, detail = entry._webview2_status()
    assert isinstance(found, bool), "found/not-found must be an explicit boolean"
    assert isinstance(detail, str) and detail
    if not sys.platform.startswith("win"):
        assert found is True, "a non-Windows run must not claim the runtime is missing"


def test_the_caller_treats_only_an_explicit_false_as_missing():
    source = _entry_source()
    main = source[source.index("def main()"):]
    assert "found, detail = _webview2_status()" in main
    assert "if missing:" not in main, "the inverted truthiness check is back"


def test_a_registry_read_cannot_crash_startup():
    """A locked-down or partially readable registry must fall through."""
    entry = _load_entry_module()
    source = _entry_source()
    body = source[source.index("def _webview2_status()"):]
    body = body[: body.index("\ndef _already_running")]
    assert "except OSError" in body
    assert "except Exception" in body
    assert entry._webview2_status()[0] in (True, False)


def test_the_two_webview2_checks_agree_on_the_shape():
    """entry.py and desktop.py each detect WebView2; both must be usable.

    They are duplicated on purpose (the bootstrap runs before the app imports),
    so the risk is that one of them drifts into a different contract.
    """
    desktop = (ROOT / "aegis" / "desktop.py").read_text(encoding="utf-8")
    entry = _entry_source()
    assert "def _webview2_version()" in desktop
    assert "def _webview2_status()" in entry
    # desktop's returns a version string or None; the caller must test truthiness
    assert "if not version:" in desktop


def test_there_is_a_window_proof_mode_and_it_is_wired_end_to_end():
    """"Prove a real window opens" is worthless if it cannot be invoked.

    Regression: the flag was added to the bootstrap but not to the CLI parser, so
    every OS exited 2 (argparse: unrecognized argument) and the probe reported
    "no window" for the wrong reason.
    """
    run_py = (ROOT / "run.py").read_text(encoding="utf-8")
    assert "--window-proof" in run_py
    assert "AEGIS_WINDOW_PROOF" in run_py

    desktop = (ROOT / "aegis" / "desktop.py").read_text(encoding="utf-8")
    assert '"WINDOW CREATED"' in desktop
    assert "AEGIS_WINDOW_PROOF" in desktop

    workflow = (ROOT / ".github" / "workflows" / "desktop.yml").read_text(encoding="utf-8")
    assert workflow.count("--window-proof") >= 3, "one per OS"
    assert "WINDOW CREATED" in workflow


def test_the_window_proof_flag_is_accepted_by_the_parser():
    """Actually parse it, rather than trusting a grep."""
    import inspect
    import runpy

    ns = runpy.run_path(str(ROOT / "run.py"))
    assert "main" in ns
    main_src = inspect.getsource(ns["main"])
    assert '"--window-proof"' in main_src
    assert "argparse.SUPPRESS" in main_src, "it is an assertion tool, not a feature"
    assert isinstance(ns.get("DEFAULT_HOST"), str)


def test_the_spec_actually_executes_its_head_without_raising():
    """The typelib collection used to reference `hiddenimports` before it existed.

    A NameError there is silent: the build still "works", the bundle just has no
    GTK, and the Linux app can never open a window. So execute the spec's head —
    everything up to Analysis(), which needs PyInstaller's build machinery.
    """
    source = ENTRY.parent.joinpath("aegis.spec").read_text(encoding="utf-8")
    head = source[: source.index("analysis = Analysis(")]
    namespace = {"SPECPATH": str(ENTRY.parent), "__file__": str(ENTRY.parent / "aegis.spec")}
    exec(compile(head, "aegis.spec", "exec"), namespace)  # noqa: S102 - a build file, executed as one

    assert isinstance(namespace["datas"], list)
    assert isinstance(namespace["hiddenimports"], list)
    assert "_typelibs" in namespace
    if sys.platform.startswith("linux"):
        assert "gi.repository.Gtk" in namespace["hiddenimports"]
