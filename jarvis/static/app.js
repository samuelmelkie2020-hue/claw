/* ============ Claw / Jarvis — front-end logic ============ */
"use strict";

// ---------------------------------------------------------------------------
// Elements
// ---------------------------------------------------------------------------
const chatLog = document.getElementById("chatLog");
const userInput = document.getElementById("userInput");
const sendBtn = document.getElementById("sendBtn");
const micBtn = document.getElementById("micBtn");
const orbLabel = document.getElementById("orbLabel");
const screenImg = document.getElementById("screenImg");
const screenOff = document.getElementById("screenOff");
const refreshScreen = document.getElementById("refreshScreen");
const safeModeEl = document.getElementById("safeMode");
const voiceRepliesEl = document.getElementById("voiceReplies");
const assistantNameEl = document.getElementById("assistantName");
const composerHint = document.getElementById("composerHint");

const settingsModal = document.getElementById("settingsModal");
const settingsBtn = document.getElementById("settingsBtn");
const closeSettings = document.getElementById("closeSettings");
const cancelSettings = document.getElementById("cancelSettings");
const saveSettings = document.getElementById("saveSettings");
const setName = document.getElementById("setName");
const setProvider = document.getElementById("setProvider");
const setBaseUrl = document.getElementById("setBaseUrl");
const setApiKey = document.getElementById("setApiKey");
const setModel = document.getElementById("setModel");

// ---------------------------------------------------------------------------
// State
// ---------------------------------------------------------------------------
const state = {
  history: [],            // [{role, content}] — text-only conversation history
  busy: false,
  orb: "idle",            // idle | listening | thinking | speaking
  settings: {
    assistant_name: "Jarvis",
    safe_mode: true,
    voice_replies: true,
    llm: { base_url: "", api_key: "", model: "" },
  },
};

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------
function esc(s) {
  return String(s ?? "")
    .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;").replace(/'/g, "&#39;");
}

function mdLite(text) {
  // very small markdown-ish renderer: code blocks, inline code, bold, italics
  let out = esc(text);
  out = out.replace(/```([\s\S]*?)```/g, (_, code) => `<pre><code>${code.trim()}</code></pre>`);
  out = out.replace(/`([^`\n]+)`/g, "<code>$1</code>");
  out = out.replace(/\*\*([^*]+)\*\*/g, "<b>$1</b>");
  out = out.replace(/(^|[\s(])\*([^*\n]+)\*/g, "$1<i>$2</i>");
  return out;
}

function setOrb(mode) {
  state.orb = mode;
  const labels = { idle: "Standing by", listening: "Listening…", thinking: "Thinking…", speaking: "Speaking…" };
  orbLabel.textContent = labels[mode] || "Standing by";
}

function scrollBottom() {
  chatLog.scrollTop = chatLog.scrollHeight;
}

function addMessage(role, html) {
  const wrap = document.createElement("div");
  wrap.className = `msg ${role}`;
  const avatar = role === "user" ? "🧑" : "🦞";
  wrap.innerHTML = `<div class="avatar">${avatar}</div><div class="bubble">${html}</div>`;
  chatLog.appendChild(wrap);
  scrollBottom();
  return wrap.querySelector(".bubble");
}

function addStatus(text) {
  const pill = document.createElement("div");
  pill.className = "status-pill";
  pill.innerHTML = `<span class="dot"></span><span>${esc(text)}</span>`;
  chatLog.appendChild(pill);
  scrollBottom();
  return pill;
}

function addToolCard(name, args) {
  const card = document.createElement("div");
  card.className = "tool-card";
  const argsStr = JSON.stringify(args || {});
  card.innerHTML = `
    <div class="tool-name">🔧 ${esc(name)}</div>
    <div class="tool-args">${esc(argsStr.length > 160 ? argsStr.slice(0, 160) + "…" : argsStr)}</div>
    <details><summary>result</summary><div class="tool-result">running…</div></details>`;
  chatLog.appendChild(card);
  scrollBottom();
  return card.querySelector(".tool-result");
}

function addApprovalCard(data) {
  const card = document.createElement("div");
  card.className = "approval-card";
  card.innerHTML = `
    <h4>🛡 Approval needed</h4>
    <p>Jarvis wants to act on your PC:</p>
    <div class="approval-desc">${esc(data.description || data.name)}</div>
    <div class="approval-actions">
      <button class="btn approve">✅ Approve &amp; run</button>
      <button class="btn deny">✖ Deny</button>
    </div>`;
  chatLog.appendChild(card);
  scrollBottom();

  const [approveBtn, denyBtn] = card.querySelectorAll("button");
  approveBtn.disabled = denyBtn.disabled = false;
  approveBtn.onclick = async () => {
    approveBtn.disabled = denyBtn.disabled = true;
    approveBtn.textContent = "Running…";
    try {
      const res = await fetch("/api/approve", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name: data.name, args: data.args || {} }),
      });
      const result = await res.json();
      card.querySelector(".approval-desc").textContent = result.result || "(done)";
      approveBtn.textContent = "✅ Done";
      // let Jarvis continue with the result
      await sendMessage(
        `(system) I approved and ran the action you requested (${data.description}). Result:\n${result.result || "(ok)"}\nContinue helping me.`,
        { hiddenUser: true }
      );
    } catch (err) {
      approveBtn.textContent = "⚠ Failed";
      card.querySelector(".approval-desc").textContent = String(err);
    }
  };
  denyBtn.onclick = () => {
    approveBtn.disabled = denyBtn.disabled = true;
    approveBtn.textContent = "✅ Approve";
    denyBtn.textContent = "Denied";
    addMessage("user", "🚫 Action denied.");
    state.history.push({ role: "user", content: "(system) I denied that action. Don't retry it." });
  };
}

function setScreenImage(b64) {
  screenImg.src = `data:image/png;base64,${b64}`;
  screenOff.style.display = "none";
}

// ---------------------------------------------------------------------------
// Chat — send + SSE consume
// ---------------------------------------------------------------------------
async function sendMessage(text, opts = {}) {
  const message = (text ?? userInput.value).trim();
  if (!message || state.busy) return;

  if (!opts.hiddenUser) {
    addMessage("user", mdLite(message));
    state.history.push({ role: "user", content: message });
    userInput.value = "";
    userInput.style.height = "auto";
  }

  state.busy = true;
  sendBtn.disabled = true;
  setOrb("thinking");

  const statusPill = addStatus("Thinking…");
  const bubble = addMessage("assistant", "");
  let fullText = "";

  try {
    const res = await fetch("/api/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        message,
        history: state.history.slice(0, -0), // whole history (the server trims)
        settings: {
          assistant_name: state.settings.assistant_name,
          safe_mode: safeModeEl.checked,
          voice_replies: voiceRepliesEl.checked,
          llm: state.settings.llm,
        },
      }),
    });

    if (!res.ok || !res.body) throw new Error(`Server error ${res.status}`);

    const reader = res.body.getReader();
    const decoder = new TextDecoder();
    let buf = "";

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buf += decoder.decode(value, { stream: true });

      let idx;
      while ((idx = buf.indexOf("\n\n")) !== -1) {
        const chunk = buf.slice(0, idx);
        buf = buf.slice(idx + 2);
        const line = chunk.split("\n").find((l) => l.startsWith("data: "));
        if (!line) continue;
        let ev;
        try { ev = JSON.parse(line.slice(6)); } catch { continue; }

        switch (ev.type) {
          case "status":
            statusPill.querySelector("span:last-child").textContent = ev.message || "Working…";
            break;

          case "tool_start": {
            statusPill.remove();
            const resultEl = addToolCard(ev.name, ev.args);
            ev._resultEl = resultEl;
            // keep a rolling reference so tool_result can fill it
            window._lastToolResultEl = resultEl;
            break;
          }

          case "tool_result": {
            if (window._lastToolResultEl) {
              window._lastToolResultEl.textContent = ev.result || "(no output)";
              window._lastToolResultEl = null;
            }
            break;
          }

          case "approval":
            statusPill.remove();
            addApprovalCard(ev);
            break;

          case "screenshot":
            setScreenImage(ev.data);
            break;

          case "message":
          case "token":
            statusPill.remove();
            fullText += ev.text || "";
            bubble.innerHTML = mdLite(fullText);
            scrollBottom();
            break;

          case "error":
            statusPill.remove();
            addMessage("assistant", `⚠ ${mdLite(ev.message || "Unknown error")}`);
            break;

          case "done":
            statusPill.remove();
            if (ev.text && !fullText) {
              fullText = ev.text;
              bubble.innerHTML = mdLite(fullText);
            }
            break;
        }
      }
    }
  } catch (err) {
    statusPill.remove();
    bubble.innerHTML = mdLite(`⚠ Something went wrong: ${err.message || err}`);
  } finally {
    if (!fullText) bubble.innerHTML = mdLite("(no response)");
    state.history.push({ role: "assistant", content: fullText || "(no response)" });
    state.busy = false;
    sendBtn.disabled = false;
    setOrb("idle");
    scrollBottom();
    if (fullText && voiceRepliesEl.checked) speak(fullText);
  }
}

// ---------------------------------------------------------------------------
// Voice output (TTS)
// ---------------------------------------------------------------------------
function speak(text) {
  try {
    const synth = window.speechSynthesis;
    if (!synth) return;
    synth.cancel();
    // strip markdown/emoji-heavy symbols for cleaner speech
    const clean = text
      .replace(/```[\s\S]*?```/g, " code block omitted. ")
      .replace(/[*_#>`]/g, "")
      .replace(/https?:\/\/\S+/g, "link")
      .slice(0, 1200);
    const u = new SpeechSynthesisUtterance(clean);
    const voices = synth.getVoices();
    const pref = voices.find((v) => v.lang.startsWith(navigator.language || "en") && !v.name.includes("Google")) ||
                 voices.find((v) => v.lang.startsWith("en")) || voices[0];
    if (pref) u.voice = pref;
    u.rate = 1.03;
    u.onstart = () => setOrb("speaking");
    u.onend = () => setOrb(state.busy ? "thinking" : "idle");
    synth.speak(u);
  } catch { /* TTS is best-effort */ }
}

// ---------------------------------------------------------------------------
// Voice input (Web Speech API)
// ---------------------------------------------------------------------------
let recognition = null;
const SpeechRec = window.SpeechRecognition || window.webkitSpeechRecognition;

micBtn.addEventListener("click", () => {
  if (!SpeechRec) {
    composerHint.textContent = "Voice input isn't supported in this browser — try Chrome or Edge.";
    return;
  }
  if (recognition && state.orb === "listening") {
    recognition.stop();
    return;
  }
  recognition = new SpeechRec();
  recognition.lang = navigator.language || "en-US";
  recognition.interimResults = true;
  recognition.continuous = false;

  const finalText = { value: "" };
  recognition.onstart = () => {
    micBtn.classList.add("listening");
    setOrb("listening");
    composerHint.textContent = "Listening… speak now (click 🎙 again to stop)";
  };
  recognition.onresult = (e) => {
    let interim = "";
    for (const res of e.results) {
      if (res.isFinal) finalText.value += res[0].transcript;
      else interim += res[0].transcript;
    }
    userInput.value = finalText.value + interim;
  };
  recognition.onerror = () => {
    micBtn.classList.remove("listening");
    setOrb("idle");
    composerHint.textContent = "Voice input error — type instead.";
  };
  recognition.onend = () => {
    micBtn.classList.remove("listening");
    setOrb("idle");
    composerHint.textContent = "Enter to send · Shift+Enter for a new line · Voice works in Chrome/Edge";
    const t = userInput.value.trim();
    if (t) sendMessage(t);
  };
  recognition.start();
});

// ---------------------------------------------------------------------------
// Composer
// ---------------------------------------------------------------------------
sendBtn.addEventListener("click", () => sendMessage());

userInput.addEventListener("keydown", (e) => {
  if (e.key === "Enter" && !e.shiftKey) {
    e.preventDefault();
    sendMessage();
  }
});
userInput.addEventListener("input", () => {
  userInput.style.height = "auto";
  userInput.style.height = Math.min(userInput.scrollHeight, 160) + "px";
});

document.querySelectorAll(".chip").forEach((chip) => {
  chip.addEventListener("click", () => sendMessage(chip.dataset.say));
});

// ---------------------------------------------------------------------------
// Screen panel
// ---------------------------------------------------------------------------
function refreshScreenImage() {
  screenImg.src = `/api/screenshot?t=${Date.now()}`;
  screenImg.onload = () => { screenOff.style.display = "none"; };
}
screenImg.addEventListener("load", () => { screenOff.style.display = "none"; });
refreshScreen.addEventListener("click", refreshScreenImage);

// ---------------------------------------------------------------------------
// Settings
// ---------------------------------------------------------------------------
const PROVIDERS = {
  openrouter: { base: "https://openrouter.ai/api/v1", model: "openai/gpt-4o-mini" },
  openai:     { base: "https://api.openai.com/v1", model: "gpt-4o-mini" },
  gemini:     { base: "https://generativelanguage.googleapis.com/v1beta/openai/", model: "gemini-2.0-flash" },
  groq:       { base: "https://api.groq.com/openai/v1", model: "llama-3.3-70b-versatile" },
  ollama:     { base: "http://localhost:11434/v1", model: "llama3.2-vision" },
  custom:     { base: "", model: "" },
};
const KNOWN_MODELS = Object.values(PROVIDERS).map((p) => p.model).filter(Boolean);

function inferProvider(baseUrl) {
  const b = (baseUrl || "").toLowerCase();
  for (const [id, p] of Object.entries(PROVIDERS)) {
    if (p.base && b.startsWith(p.base.toLowerCase())) return id;
  }
  return "custom";
}

setProvider.addEventListener("change", () => {
  const p = PROVIDERS[setProvider.value];
  if (!p) return;
  if (setProvider.value !== "custom") setBaseUrl.value = p.base;
  if (!setModel.value.trim() || KNOWN_MODELS.includes(setModel.value.trim())) setModel.value = p.model;
});

async function loadSettings() {
  try {
    const res = await fetch("/api/settings");
    const cfg = await res.json();
    state.settings = cfg;
    safeModeEl.checked = cfg.safe_mode !== false;
    voiceRepliesEl.checked = cfg.voice_replies !== false;
    assistantNameEl.textContent = cfg.assistant_name || "Jarvis";
    setName.value = cfg.assistant_name || "";
    setBaseUrl.value = cfg.llm?.base_url || "";
    setProvider.value = inferProvider(cfg.llm?.base_url);
    setApiKey.value = cfg.llm?.api_key || "";
    setModel.value = cfg.llm?.model || "";
    document.querySelector(".brand-sub").textContent =
      (cfg.llm?.api_key || "").length > 0 ? `Claw · ${cfg.llm.model || "AI"} connected` : "Claw · demo brain";
  } catch { /* keep defaults */ }
}

function openSettings() {
  settingsModal.classList.remove("hidden");
}
function hideSettings() {
  settingsModal.classList.add("hidden");
}
settingsBtn.addEventListener("click", openSettings);
closeSettings.addEventListener("click", hideSettings);
cancelSettings.addEventListener("click", hideSettings);
settingsModal.addEventListener("click", (e) => { if (e.target === settingsModal) hideSettings(); });

saveSettings.addEventListener("click", async () => {
  const payload = {
    assistant_name: setName.value.trim() || "Jarvis",
    safe_mode: safeModeEl.checked,
    voice_replies: voiceRepliesEl.checked,
    llm: {
      base_url: setBaseUrl.value.trim(),
      api_key: setApiKey.value.trim(),
      model: setModel.value.trim(),
    },
  };
  try {
    const res = await fetch("/api/settings", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ settings: payload }),
    });
    state.settings = await res.json();
    assistantNameEl.textContent = state.settings.assistant_name;
    document.querySelector(".brand-sub").textContent =
      (state.settings.llm?.api_key || "").length > 0
        ? `Claw · ${state.settings.llm.model || "AI"} connected`
        : "Claw · demo brain";
    addMessage("assistant", `⚙️ Settings saved. I'm <b>${esc(state.settings.assistant_name)}</b>${
      (state.settings.llm?.api_key || state.settings.llm?.base_url?.includes("localhost"))
        ? ` and I'm thinking with <code>${esc(state.settings.llm.model)}</code>.`
        : " and my demo brain is active — add an API key in Settings to unlock full intelligence."
    }`);
  } catch (err) {
    addMessage("assistant", `⚠ Could not save settings: ${err.message || err}`);
  }
  hideSettings();
});

const testConnBtn = document.getElementById("testConnBtn");
const testResult = document.getElementById("testResult");
testConnBtn.addEventListener("click", async () => {
  testConnBtn.disabled = true;
  testResult.className = "test-result bad";
  testResult.textContent = "🔌 Testing connection…";
  try {
    const res = await fetch("/api/test-connection", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        settings: {
          llm: {
            base_url: setBaseUrl.value.trim(),
            api_key: setApiKey.value.trim(),
            model: setModel.value.trim(),
          },
        },
      }),
    });
    const data = await res.json();
    testResult.textContent = data.detail || "(no response)";
    testResult.className = data.ok ? "test-result ok" : "test-result bad";
  } catch (err) {
    testResult.textContent = "Could not run the test: " + (err.message || err);
    testResult.className = "test-result bad";
  } finally {
    testConnBtn.disabled = false;
  }
});

safeModeEl.addEventListener("change", () => {
  state.settings.safe_mode = safeModeEl.checked;
  fetch("/api/settings", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ settings: { safe_mode: safeModeEl.checked } }),
  });
});

// ---------------------------------------------------------------------------
// Animated orb
// ---------------------------------------------------------------------------
const canvas = document.getElementById("orb");
const ctx = canvas.getContext("2d");
let t = 0;

function drawOrb() {
  t += 0.016;
  const w = canvas.width, h = canvas.height;
  const cx = w / 2, cy = h / 2;
  ctx.clearRect(0, 0, w, h);

  const mode = state.orb;
  const speed = mode === "thinking" ? 2.6 : mode === "listening" ? 1.8 : mode === "speaking" ? 2.1 : 1;
  const breathe = 1 + Math.sin(t * 1.4 * speed) * (mode === "idle" ? 0.03 : 0.07);

  // outer glow
  const glow = ctx.createRadialGradient(cx, cy, 20, cx, cy, 150 * breathe);
  const hue = mode === "listening" ? 330 : mode === "thinking" ? 265 : 195;
  glow.addColorStop(0, `hsla(${hue}, 95%, 65%, 0.55)`);
  glow.addColorStop(0.55, `hsla(${hue + 25}, 90%, 55%, 0.16)`);
  glow.addColorStop(1, "transparent");
  ctx.fillStyle = glow;
  ctx.fillRect(0, 0, w, h);

  // core
  const core = ctx.createRadialGradient(cx - 18, cy - 22, 8, cx, cy, 86 * breathe);
  core.addColorStop(0, "#e0faff");
  core.addColorStop(0.28, `hsla(${hue}, 92%, 62%, 0.95)`);
  core.addColorStop(1, `hsla(${hue + 40}, 85%, 30%, 0.9)`);
  ctx.beginPath();
  ctx.arc(cx, cy, 86 * breathe, 0, Math.PI * 2);
  ctx.fillStyle = core;
  ctx.fill();

  // orbiting rings
  const ringCount = mode === "idle" ? 2 : 3;
  for (let i = 0; i < ringCount; i++) {
    const phase = t * speed * (0.6 + i * 0.35) + i * 2.1;
    const radius = 108 + i * 16 + Math.sin(phase) * 7;
    ctx.beginPath();
    ctx.ellipse(cx, cy, radius, radius * 0.42, phase * 0.45, 0, Math.PI * 2);
    ctx.strokeStyle = `hsla(${hue + i * 18}, 90%, ${62 - i * 8}%, ${0.5 - i * 0.11})`;
    ctx.lineWidth = 1.6;
    ctx.stroke();
  }

  // particles
  const particles = mode === "idle" ? 12 : 22;
  for (let i = 0; i < particles; i++) {
    const a = t * (0.25 + (i % 5) * 0.12) * speed + i * 0.7;
    const r = 60 + ((i * 37) % 90) + Math.sin(t * speed + i) * 10;
    const x = cx + Math.cos(a) * r;
    const y = cy + Math.sin(a * 1.3) * r * 0.62;
    ctx.beginPath();
    ctx.arc(x, y, 1.4 + (i % 3) * 0.8, 0, Math.PI * 2);
    ctx.fillStyle = `hsla(${hue + 40}, 95%, 75%, ${0.25 + 0.3 * Math.abs(Math.sin(a))})`;
    ctx.fill();
  }

  requestAnimationFrame(drawOrb);
}
drawOrb();

// ---------------------------------------------------------------------------
// Boot
// ---------------------------------------------------------------------------
loadSettings();
refreshScreenImage();
