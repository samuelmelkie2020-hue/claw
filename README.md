# 🦞 Claw — Your own Jarvis for the PC

A personal AI assistant that can **see your screen** and **control your computer** — like Jarvis.

Ask it in plain English (or by voice) and it will look at your screen, run commands, open apps, type, click, manage files and report system status.

> *"What's on my screen?" · "Open Spotify and play something" · "Run the tests and tell me what failed" · "What's eating my memory?"*

---

## ✨ Features

| | |
|---|---|
| 👀 **Sees your PC** | Captures your screen and analyzes it with a vision model |
| 💻 **Controls your PC** | Runs shell commands, opens apps, types, presses shortcuts, clicks |
| 📂 **File assistant** | Lists, reads, writes and searches files |
| 🖥 **System monitor** | CPU, memory, disk, battery, uptime, top processes |
| 🎙 **Voice in, voice out** | Talk to it (browser speech recognition), it talks back (TTS) |
| 🧠 **Bring your own brain** | Works with OpenAI, Gemini, Groq, OpenRouter — or fully local **Ollama** |
| 🛡 **Safe mode** | Asks your approval before touching your PC (on by default) |
| 🤖 **Demo brain** | Works instantly with *no* API key for basic commands |

---

## 🚀 Quick start

Requires **Python 3.9+**.

```bash
# 1. Get the code onto your PC
git clone https://github.com/samuelmelkie2020-hue/claw.git
cd claw

# 2. (recommended) create a virtual environment
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate

# 3. install
pip install -r requirements.txt

# 4. run
python run.py
```

Open **http://localhost:8000** — Jarvis is awake. 🎉

It works immediately with the built-in **demo brain** (try *"what's on my screen?"*, *"run dir"*, *"open notepad"*).

---

## 🧠 Connect a real AI model (30 seconds)

Click **⚙️ Settings** in the app and fill in any OpenAI-compatible provider:

| Provider | API base URL | Example model |
|---|---|---|
| **OpenAI** | `https://api.openai.com/v1` | `gpt-4o-mini`, `gpt-4o` |
| **Google Gemini** | `https://generativelanguage.googleapis.com/v1beta/openai/` | `gemini-2.0-flash` |
| **Groq** | `https://api.groq.com/openai/v1` | `llama-3.3-70b-versatile` |
| **OpenRouter** | `https://openrouter.ai/api/v1` | `openai/gpt-4o-mini` |
| **Ollama (local, free)** | `http://localhost:11434/v1` | `llama3.2-vision` |

Paste your API key and **Save**. Use a **vision-capable model** so Jarvis can see your screen.

> 🔑 Your key is stored only on your machine in `jarvis_config.json` (git-ignored, chmod 600).

---

## 🗣 How to talk to it

- **Type** in the chat box — Enter sends.
- **🎙 Voice** — click the mic and speak (Chrome/Edge; it also reads replies aloud — toggle with *Speak replies*).
- **Quick actions** — the chips on the left for common requests.

Things you can say:

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

## 🛡 Safety

- **Ask before acting** (safe mode) is ON by default: Jarvis pauses before running commands, opening apps, typing, clicking or writing files, and shows an **Approve / Deny** card. Turn it off only on machines you fully trust it with.
- It refuses destructive commands (deleting system files, formatting disks…) unless you explicitly ask.
- The server binds to `0.0.0.0:8000` so it works with local network devices too — but that also means anyone on your network can reach it. Keep your PC behind a firewall, or set `JARVIS_HOST=127.0.0.1` to restrict it to your machine only.

---

## ⚙️ Configuration

Everything is editable in the app's Settings. Power users can edit `jarvis_config.json` directly:

```json
{
  "assistant_name": "Jarvis",
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
| `JARVIS_PORT` | `8000` | Port to serve on |
| `JARVIS_HOST` | `0.0.0.0` | Bind address |
| `JARVIS_CONFIG` | `./jarvis_config.json` | Path to the config file |

---

## 🧩 How it works

```
┌──────────────┐   chat / voice    ┌────────────────────────────┐
│  Web UI      │ ◄───────────────► │  FastAPI server (run.py)   │
│  (browser)   │   live SSE stream │                            │
└──────────────┘                   │   ┌────────────────────┐   │
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

1. You ask something (text or voice).
2. The request goes to a vision-capable LLM with a set of **tools**.
3. The LLM decides what to do — e.g. `see_screen` → look at the screenshot → `click(512, 340)` → `type_text("hello")`.
4. Results (including screenshots) stream back to the chat in real time.

Without an API key, a built-in **demo brain** handles simple intents so you can try everything right away.

---

## 🖥 Platform notes

- **Windows** — fully supported. If typing/shortcuts don't land, run the terminal as your user (not as a service) and give Python accessibility permissions.
- **macOS** — grant **Screen Recording** + **Accessibility** permissions to your terminal in *System Settings → Privacy & Security*, or screenshots/typing will be blocked.
- **Linux** — needs an X11/Wayland session with `xdg-utils` for opening apps; works out of the box on desktops.

---

## 🧪 Troubleshooting

| Problem | Fix |
|---|---|
| "Screen capture unavailable" | Run it on a machine with a real display; on macOS grant Screen Recording permission. |
| Mic button says unsupported | Voice input needs Chrome or Edge (Web Speech API). |
| "I couldn't reach the AI model" | Check base URL / key / model in ⚙️ Settings. Ollama users: make sure `ollama serve` is running and you `ollama pull llama3.2-vision`. |
| Jarvis acts but nothing types | Focus the window you want to type into — typing goes to whatever is focused. |
| Port already in use | `JARVIS_PORT=8080 python run.py` |

---

Made with 🦞 — your friendly neighborhood claw.
