# 🛡 Aegis — your own AI assistant for the PC

A personal AI assistant that can **see your screen** and **control your computer** — like a JARVIS.

Ask it in plain English (or by voice) and it will look at your screen, run commands, open apps, type, click, manage files and report system status.

> *"What's on my screen?" · "Open Spotify and play something" · "Run the tests and tell me what failed" · "What's eating my memory?"*

---

## ✨ Features

| | |
|---|---|
| 👀 **Sees your PC** | Captures your screen and analyzes it with a vision model |
| 🔴 **Live view** | Watch your own screen in the app at 2 fps — or let it watch while you talk to it |
| 🔄 **Updates itself** | Sees a new release, downloads it, checks it, and installs it on restart — no zip again |
| 💻 **Controls your PC** | Runs shell commands, opens apps, types, presses shortcuts, clicks |
| 📂 **File assistant** | Lists, reads, writes and searches files |
| 🖥 **System monitor** | CPU, memory, disk, battery, uptime, top processes |
| 🎙 **Voice in, voice out** | Talk to it (browser speech recognition), it talks back (TTS) |
| 🧠 **Runs on your PC** | The AI model lives on your computer (**Ollama** / LM Studio). No API key, no account, nothing leaves the machine |
| 📦 **Installs its own model** | Aegis checks your CPU, RAM and GPU, recommends a model that fits, and downloads it from inside the app |
| 🛡 **Safe mode** | Asks your approval before touching your PC (on by default) |
| 🔌 **Cloud is optional** | OpenAI, Gemini, Groq and OpenRouter still work if you prefer — your choice, never required |

---

## 🚀 Quick start

### 💻 The easy way — download the app

Grab the build for your OS from **[Releases](https://github.com/samuelmelkie2020-hue/Aegis/releases)** and run it:

| OS | File | Then |
|---|---|---|
| **Windows** | `Aegis-windows.zip` | Unzip → double-click **`Aegis.exe`** |
| **macOS** | `Aegis-macos.zip` | Unzip → drag **`Aegis.app`** to Applications → open it |
| **Linux** | `Aegis-linux.zip` | Unzip → `chmod +x Aegis` → run `./Aegis` |

No Python, no terminal, no browser tab. Aegis opens in **its own window**, and that window *is* the app. 🎉

> **First launch on macOS:** the builds are unsigned, so Gatekeeper will complain. Right-click the app → **Open** → **Open**, or run `xattr -dr com.apple.quarantine /Applications/Aegis.app`. You only do this once.
>
> **First launch on Windows:** SmartScreen may show *"Windows protected your PC"* — click **More info** → **Run anyway**.

### 🧑‍💻 Running from source

Requires **Python 3.10+** (3.11 or newer recommended).

```bash
git clone https://github.com/samuelmelkie2020-hue/Aegis.git
cd aegis

python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate

pip install -r requirements.txt
python run.py                    # desktop window
```

Or skip the typing: double-click **`start.bat`** (Windows) / run **`bash start.sh`** (Mac & Linux) — they set up the virtualenv, install what's missing, and launch the desktop app. Both scripts fall back to the browser automatically if a native webview isn't available.

It works immediately with the built-in **demo brain** (try *"what's on my screen?"*, *"run dir"*, *"open notepad"*).

### 🌐 Prefer the browser?

```bash
python run.py --web              # serves http://127.0.0.1:8000 and opens your browser
python run.py --web --no-open    # just serve, don't open anything
```

The web UI is the same app, and it is still handy for LAN use (see [Safety](#-safety)) or for debugging the frontend with devtools. `start.sh --web` and `start.bat --web` do the same thing.

### 🧰 Command-line flags

| Flag | What it does |
|---|---|
| *none* | Opens the native desktop window (default) |
| `--web` | Serve in the browser instead of a native window |
| `--no-open` | With `--web`: don't launch a browser tab |
| `--port N` | Fixed port instead of a free one (default `8000`) |
| `--host H` | Bind address, e.g. `0.0.0.0` for LAN (default `127.0.0.1`) |
| `--debug` | Verbose logging |
| `--self-check` | Verify the install works: frozen vs source, data dir, server start/stop, webview availability |
| `--diagnose` | Explain **why the window does not open**: WebView2 version, whether another copy holds the port, pywebview, **how far the last launch got** (1/4 → 4/4), the local-model state, and the tail of any crash log — with no key or token in the output, so it is safe to paste |

---

## 🧠 Connect a real AI model (no key, ~5 minutes)

**Aegis runs the AI on your own computer.** There is no sign-up, no API key, and
no bill. The model reads your screen and answers locally — nothing is uploaded.

1. **Install a local model server** — [Ollama](https://ollama.com/download) is the
   easiest (one installer, Windows/macOS/Linux). LM Studio and llama.cpp also work.
2. **Open Aegis → ⚙️ Settings → 💻 This computer.** It shows your CPU, memory and
   graphics card, and what it recommends for that machine:
   - ~8 GB of RAM → `qwen2.5vl:3b` (about 3 GB)
   - 16 GB or a modest GPU → `qwen2.5vl:7b` or `llava:7b`
   - very little memory → `moondream` (about 1.7 GB)
3. Press **Download** (or **Use this model**). Progress is shown in the panel and
   can be cancelled. When it finishes, press **Save settings**.

That's it — Aegis now thinks on your PC. Vision models (the ones marked 👁) can
also *see* your screen; a text-only model works too, just without the eyes.

If a model is already installed, Aegis finds it at startup and uses it — no setup
at all. The default provider is `http://127.0.0.1:11434/v1` with no key.

> ⚡ **Startup never waits for it.** The window opens first and the lookup happens
> in the background (0.6 s per endpoint, no GPU probe); if nothing answers, you get
> the demo brain and the Settings panel, not a splash screen that never leaves.

### Cloud is still optional

Pick a provider under *Use a cloud provider instead* if you prefer one:

| Provider | API base URL | Example model |
|---|---|---|
| **OpenAI** | `https://api.openai.com/v1` | `gpt-4o-mini`, `gpt-4o` |
| **Google Gemini** | `https://generativelanguage.googleapis.com/v1beta/openai/` | `gemini-2.0-flash` |
| **Groq** | `https://api.groq.com/openai/v1` | `llama-3.3-70b-versatile` |
| **OpenRouter** | `https://openrouter.ai/api/v1` | `openai/gpt-4o-mini` |
| **Ollama / LM Studio** | `http://127.0.0.1:11434/v1` · `http://127.0.0.1:1234/v1` | any installed model |

Paste your API key and **Save**. Use a **vision-capable model** so Aegis can see your screen.

> 🔒 **Nothing labelled "on this PC" ever leaves the machine.** Aegis only treats
> an address as local when it is loopback (`127.0.0.1`, `localhost`, `::1`) — a LAN
> IP or a lookalike hostname is rejected, so a "local" provider cannot silently
> upload a screenshot. A model download is only ever aimed at a local server.

> 🔑 Your key is stored only on your machine — `aegis_config.json` in the app's data folder (**Windows** `%APPDATA%\Aegis`, **macOS** `~/Library/Application Support/Aegis`, **Linux** `~/.config/Aegis`; the repo folder when running from source — override with `AEGIS_DATA_DIR`) (git-ignored, `chmod 600`) and is never sent back to the browser.

---

## 🗣 How to talk to it

- **Type** in the chat box — Enter sends.
- **🎙 Voice** — click the mic and speak (Chrome/Edge; it also reads replies aloud — toggle with *Speak replies*).
- **Quick actions** — the chips on the left for common requests.

Things you can say:

**Watching your screen live.** The ⏺ button on the screen panel streams your display
into the app at 2 frames a second, so you can narrate what you are doing while Aegis
follows along. It is off until you press it, and it stops itself when the tab goes to
the background, after four failed frames, or after 30 minutes — a live view nobody is
looking at is just a screen recorder. Frames are JPEG, sent to your browser only, and
marked `no-store` so nothing is left in the cache.

```
What's on my screen?
Click the blue button in the middle of the screen
Open Chrome and go to youtube.com
Run "git status" and explain it
Write a note to my desktop called todo.txt with my shopping list
Find all PDF files in my Downloads folder
How is my PC doing?
```

---

### 🔄 Updating

Aegis checks for a new release when it starts (and every six hours) and offers it
in the sidebar. **Get it** downloads in the background; **Restart & install**
closes the app and reopens it on the new version. No zip, no replacing files by
hand, and your settings, token and conversations are untouched because they live
outside the app.

An updater downloads an executable, so the checks are the point:

| Check | Why |
|---|---|
| Only `https://github.com/…` and GitHub's asset CDN | The URL comes from the GitHub API, but a compromised release would point anywhere |
| **SHA-256 must match the digest GitHub publishes** | A truncated, corrupted or swapped download is deleted, never unpacked |
| 250 MB ceiling, exact byte count | The real asset is ~28 MB |
| The new build must pass its own `--self-check` | A build that cannot start must never replace one that can |
| HTTPS only, no downgrade | — |

And it is deliberate: the download is a click, the install is a second click, and
the install itself goes through the same **Approve / Deny** path as a shell
command — the page can only redeem an id the server issued, once, for its own
session. The payload and version are chosen by the server, never by the request.

Installing from source is refused on purpose: replacing a git checkout would
destroy work. `git pull` instead. Updates can be turned off completely with
`AEGIS_NO_UPDATES=1`.

If something goes wrong, the previous build is kept as `Aegis.old` next to the new
one, and the helper's log is at `<data dir>/update/update.log` (or
`relaunch.log`).

---

## 🛡 Safety

- **Ask before acting** (safe mode) is ON by default: Aegis pauses before running commands, opening apps, typing, clicking or writing files, and shows an **Approve / Deny** card. Turn it off only on machines you fully trust it with.
- **Safe mode cannot be disabled by a browser.** It is read from `aegis_config.json` on every turn; the page can only *save* a new value, and only through an authenticated request.
- It refuses destructive commands (deleting system files, formatting disks…) unless you explicitly ask.
- **Localhost only by default.** The server binds to `127.0.0.1`, so it is not reachable from your network.
- **Every `/api` call needs an access token.** Aegis runs commands and reads files, so the API is not open. A random token is generated on first run and stored in `.aegis_token` (next to your config, `chmod 600`). The desktop window loads `http://127.0.0.1:<port>/?token=…` once and the page trades it for an HttpOnly session cookie; in `--web` mode the terminal prints that URL for you to open.
- **Your API key never leaves the server.** The Settings dialog shows only whether a key is saved, plus a masked hint (`sk-…1234`). Leaving the key field blank keeps the saved key; tick **Forget the saved key** to delete it.
- **A local model has no key and no network.** `local` is derived from the base URL on the server (loopback only) and is never trusted from the client, so a cloud endpoint cannot pretend to be local — and a "local" provider cannot point at a LAN machine.
- **Live view is opt-in and limits itself.** Off by default, token-gated, capped at 4 fps **by the server** rather than the page, stopped when the tab goes to the background, and ended after 30 minutes. The panel shows a red **Live** badge that turns amber **Stalled** if frames stop arriving — the badge never claims to be watching a screen it is not reading.
- Requests whose `Host` header is not this machine are rejected, which blocks DNS-rebinding attacks from a web page you happen to visit.

### What Aegis will not do

- **Read your credentials.** `~/.ssh`, `~/.aws`, `~/.gnupg`, `.env` files, private keys, `.netrc`, and Aegis's own config/token are refused by the file tools, whichever way the path is spelled (symlinks are resolved first). Reads outside your home folder are refused too.
- **Write outside your home folder** — and never to its own config or an `authorized_keys`-style file.
- **Repeat a credential into the model.** Anything that looks like a key, token, PEM block, or a password inside a URL is masked (`sk-abc… [redacted]`) before tool output reaches the AI provider.
- **Run an approved action twice.** Approvals live on the server, are bound to your session, expire after 5 minutes, and are consumed on use. The page only ever sends the approval *id*; it cannot change the command.
- **Be nudged into clicking the wrong thing.** Screenshots are downscaled for the model, and `click` maps the coordinates back to your real screen (and refuses points outside it).
- **Hang or run away.** A turn has a 5-minute budget; if you close the tab, the agent stops at its next step instead of working on into the void. Tool results are capped, searches are bounded, and only the newest screenshot is kept in context.
- **Lose your settings silently.** A settings file that cannot be parsed is moved aside (`aegis_config.json.corrupt-<timestamp>`) and reported in the app, rather than quietly reset to defaults and overwritten.

### If you really want it on your LAN

```bash
AEGIS_HOST=0.0.0.0 AEGIS_ALLOWED_HOSTS=192.168.1.50 python run.py --web
```

The token is still required, so only devices that can read the URL (or the `.aegis_token` file) can control the PC. Add your host or IP to `AEGIS_ALLOWED_HOSTS`, otherwise the `Host` check rejects it. Only do this on a network you trust.

---

## ⚙️ Configuration

Everything is editable in the app's Settings. Power users can edit `aegis_config.json` directly:

```json
{
  "assistant_name": "Aegis",
  "llm": {
    "base_url": "https://api.openai.com/v1",
    "api_key": "sk-...",
    "model": "gpt-4o"
  },
  "safe_mode": true,
  "voice_replies": true
}
```

Environment variables:

| Variable | Default | Meaning |
|---|---|---|
| `AEGIS_PORT` | `8000` | Port to serve on |
| `AEGIS_HOST` | `127.0.0.1` | Bind address. `0.0.0.0` exposes it on your network (token still required) |
| `AEGIS_NO_UPDATES` | unset | Set to `1` to disable update checks and installs entirely |
| `AEGIS_DATA_DIR` | per-OS | Where settings, the token and update files live |
| `AEGIS_CONFIG` | `./aegis_config.json` | Path to the config file |
| `AEGIS_TOKEN` | *(generated)* | Use a fixed access token instead of `.aegis_token` |
| `AEGIS_TOKEN_FILE` | `./.aegis_token` | Where the generated token is stored |
| `AEGIS_ALLOWED_HOSTS` | *(loopback + preview)* | Comma-separated extra `Host` values to accept |
| `AEGIS_EMBED_TOKEN` | `true` on localhost | Force embedding (or not embedding) the token in the served page |
| `AEGIS_NO_GUI_ERRORS` | off | `1` skips the crash window and only writes `aegis-crash.log` (used by CI and headless machines) |
| `AEGIS_DATA_DIR` | platform data folder | Where the config, token and clapboard files live (ignored when `AEGIS_CONFIG` is set) |
| `AEGIS_ALLOW_READ_OUTSIDE_HOME` | off | `1` lets the file tools read outside your home folder (credentials stay blocked) |
| `AEGIS_ALLOW_WRITE_OUTSIDE_HOME` | off | `1` lets `write_file` write outside your home folder (config and tokens stay blocked) |

---

## 🧑‍💻 Development

```bash
pip install -r requirements-dev.txt   # runtime deps + pytest + ruff
python -m pytest -q                   # 445 tests, ~13s, no display, no API key, no internet
ruff check .                          # lint (config lives in pyproject.toml)
python run.py --self-check            # diagnose a machine: data dir, server, webview
node --check aegis/static/app.js      # front-end syntax
```

The suite runs headless: it redirects `HOME`, the config file and the token file
to a temp directory before any `aegis` module is imported, so it can never
touch your real settings, and it fakes the display, the model and the mouse.
CI runs the tests on 3.10–3.12 plus lint and a JS syntax check (`.github/workflows/ci.yml`).
A second workflow (`.github/workflows/desktop.yml`) freezes the app with PyInstaller on
Windows, macOS and Linux, smoke-tests each binary with `--self-check`, and attaches the
archives to the GitHub Release whenever a `v*` tag is pushed.

Front-end changes are covered by `tests/test_frontend.py`, which asserts that
every element id the script uses exists, that the UI keeps its accessibility
contract (live regions, dialog semantics, visible focus), and that no API call
is hardcoded to `localhost` (which would break behind the preview proxy).

| Area | Where |
|---|---|
| Access control (token, Host/Origin) | `aegis/security.py`, `tests/test_security.py` |
| Settings validation + secret masking | `aegis/config.py`, `tests/test_config.py` |
| Path policy + redaction | `aegis/safety.py`, `tests/test_tools.py` |
| Agent loop, safe mode, approvals | `aegis/llm.py`, `aegis/approvals.py`, `tests/test_agent.py` |
| SSE contract | `aegis/server.py`, `tests/test_streaming.py` |
| Desktop shell, port/server lifecycle, packaging | `aegis/desktop.py`, `packaging/aegis.spec`, `tests/test_desktop.py` |

### Building the desktop app yourself

```bash
pip install -r requirements-dev.txt pyinstaller
bash packaging/build.sh          # Windows: packaging\build.ps1
```

The result lands in `dist/` — `Aegis.exe`, `Aegis.app`, or a `Aegis` binary. The spec is
`packaging/aegis.spec`: one-file, windowed (no console), with `aegis/static` bundled.
The application icon is code, not a binary blob: `python packaging/make_icon.py`
regenerates `packaging/assets/aegis.ico|icns|png` and the runtime copy in
`aegis/static/`. Small sizes are drawn separately rather than downscaled, so the
16 px taskbar icon stays legible. CI fails the build if an icon asset is missing.

Always run `dist/Aegis --self-check` after freezing — a build that works from source but
not frozen is the most common packaging failure.

## 🧩 How it works

```
┌──────────────┐   chat / voice    ┌────────────────────────────┐
│  Web UI      │ ◄───────────────► │  FastAPI server            │
│  (desktop    │   live SSE stream │  (uvicorn, own thread)     │
│   window or  │                   │                            │
│   browser)   │                   │   ┌────────────────────┐   │
                                   │   │  Agent loop (LLM)  │   │
                                   │   └─────────┬──────────┘   │
                                   │             │ tool calls   │
                                   │   ┌─────────▼──────────┐   │
                                   │   │  Tools             │   │
                                   │   │  see_screen        │   │
                                   │   │  run_command       │   │
                                   │   │  open_app / type   │   │
                                   │   │  click / keys      │   │
                                   │   │  files / system    │   │
                                   │   └────────────────────┘   │
                                   └────────────────────────────┘
```

0. `run.py` picks a free port, starts uvicorn on `127.0.0.1` in a background thread, then
   hands that URL to a native window via **pywebview** (`aegis/desktop.py`). The web UI in
   that window is the same one `--web` serves; it talks to the server over loopback, so no
   code is duplicated between the desktop and browser versions.
1. You ask something (text or voice). The request carries only your message and the conversation — never settings.
2. The server checks your session, then calls a vision-capable LLM with a set of **tools**, using the policy (safe mode, provider) it loaded from disk.
3. The LLM decides what to do — e.g. `see_screen` → look at the screenshot → `click(512, 340)` → `type_text("hello")`.
4. Results (including screenshots) stream back to the chat in real time.
5. If an action needs approval, the server registers it, shows a card, and — once you click — runs that stored action itself, exactly once, then resumes the conversation with the result.

### Live frames (alternate clients)

`GET /api/live/frame?fps=2` returns `image/jpeg` — one frame of the display, token-gated
like everything else. `Cache-Control: no-store` always; `X-Aegis-Tick` increments per
*new* frame (a repeated value means the frame was re-sent because you asked faster than
the limit); `X-Aegis-Capture: fresh|reused`. The server clamps `fps` to 4, stops a run
after 30 minutes, and treats a gap of 2 minutes as a new run. `503` carries a JSON
`{reason, detail}` when there is no display or the run ended.

### Streaming protocol (for alternate clients)

`POST /api/chat` returns `text/event-stream`. Each event is one `data:` line of JSON with a `type`:

| `type` | Meaning |
|---|---|
| `status` | `{message}` — keep-alive-ish progress note |
| `tool_start` / `tool_result` | `{name, args}` then `{name, result, ok}` |
| `approval` | `{approval_id, name, args, description}` — POST the id to `/api/approve` |
| `screenshot` | `{data}` — base64 PNG |
| `message` | `{text}` — markdown-ish reply text |
| `error` | `{message}` — the only failure event; render this text once |
| `done` | `{ok, text}` — exactly one per stream, always last |

`: ping` comment lines are sent every 15 s so proxies do not drop a stream during a slow model call.

The brain is a **local model** by default (`aegis/local_llm.py`): at startup Aegis
probes `127.0.0.1:11434` (Ollama), `:1234` (LM Studio) and `:8080` (llama.cpp), and
if a model is already installed it wires itself up — no key, no config file to edit.

Without any local model, a built-in **demo brain** handles simple intents so you can
try everything right away, and the app tells you exactly how to fix that rather
than asking for an API key.

---

## 🖥 Platform notes

- **Windows** — fully supported. If typing/shortcuts don't land, run the terminal as your user (not as a service) and give Python accessibility permissions.
- **macOS** — grant **Screen Recording** + **Accessibility** permissions to **Aegis** (or your terminal,
  when running from source) in *System Settings → Privacy & Security*, or screenshots/typing will be blocked.
- **Linux** — needs `WebKitGTK` for the desktop window (`libwebkit2gtk-4.1-0`, plus `python3-gi`) and
  an X11/Wayland session with `xdg-utils` for opening apps. If the webview is missing, `start.sh`
  falls back to the browser; `python run.py --self-check` tells you which pieces are present.
- **Desktop window vs browser** — the window is Chrome-less and owns the app lifecycle (closing it
  stops the server). Use `--web` when you want devtools, LAN access from a phone, or a normal tab.

---

## 🧪 Troubleshooting

| Problem | Fix |
|---|---|
| *"Could not open requirements file"* | You are not in the `aegis` folder — run `cd aegis` first, or use **start.bat** (it handles everything). |
| *"TLS/SSL connection has been closed"* / can't reach a **cloud** provider | Your network is blocking it (not your key). Press **🔌 Test connection** in Settings, try another Provider or a VPN — or switch to **💻 Run on this PC**, which needs no network at all. If you're chatting inside the Arena **preview**: that sandbox is always blocked from AI sites, so local is the only option there. |
| "Screen capture unavailable" | Run it on a machine with a real display; on macOS grant Screen Recording permission. |
| Mic button says unsupported | Voice input needs Chrome or Edge (Web Speech API). |
| "No local model is running" | Aegis looks for Ollama on `127.0.0.1:11434`. Start Ollama (open the app, or run `ollama serve`), then ⚙️ Settings → 💻 This computer → **↻ Refresh**. |
| "…does not have *model* (HTTP 404)" | The server is running but that model is not downloaded. Use **Download** in ⚙️ Settings → 💻 This computer, or `ollama pull <model>`. |
| Aegis acts but nothing types | Focus the window you want to type into — typing goes to whatever is focused. |
| Update says "cannot verify" / "does not match the checksum" | The download was corrupted or intercepted. It was deleted, not installed. Try again; if it repeats, download the release manually. |
| Update says it cannot write to the app folder | Aegis lives in a folder you do not own (e.g. `C:\Program Files`). Move the `Aegis` folder to Downloads or Desktop and update again. |
| Update failed to install | The previous build is intact as `Aegis.old`. The helper's log says what happened: `<data dir>/update/update.log`. |
| Port already in use | `python run.py --port 8080` (or `AEGIS_PORT=8080`) — the starters honour it too |
| *"No module named webview"* | `pip install pywebview`; on Linux also install WebKitGTK. Or run `python run.py --web` |
| Desktop window is blank / white | Check `aegis-crash.log` in the data folder; run `python run.py --self-check` and retry with `--debug` |
| **Nothing happens when I double-click `Aegis.exe`** (fixed in 1.8.3) | First, the guaranteed way in: **`Aegis.exe --web`** — same app, in your normal browser, no native window needed. If the window itself refuses to appear, Aegis now falls back to the browser automatically and tells you why. To understand it: run `Aegis.exe --diagnose` and read the report — it names the cause instead of guessing. The three usual ones: **WebView2 is not installed** (fix below), **antivirus quarantined the exe**, or **a window that opened somewhere you are not looking** (a second copy opens on a free port, so check other windows/virtual desktops). Every launch writes `%APPDATA%\Aegis\aegis-startup.log` — `--diagnose` reads it and tells you which stage it reached. |
| *"Aegis needs Microsoft Edge WebView2"* | Install the free runtime once: <https://go.microsoft.com/fwlink/p/?LinkId=2124703> — it is preinstalled on Windows 11 and most Windows 10 PCs. `Aegis.exe --diagnose` tells you the installed version, or that there is none. |
| Desktop window is blank / white | Check `aegis-crash.log` in the data folder; run `python run.py --self-check` and retry with `--debug` |
| macOS says the app is damaged / from an unidentified developer | It is unsigned: right-click → **Open**, or `xattr -dr com.apple.quarantine /Applications/Aegis.app` |
| Where are my settings? | `--self-check` prints the data folder: `%APPDATA%\Aegis`, `~/Library/Application Support/Aegis` or `~/.config/Aegis` |

---

Made with 🛡 — Aegis.

---

## 📄 License

MIT — see [LICENSE](LICENSE). Use it, change it, ship it; the copyright notice
has to travel with it.
