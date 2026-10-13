"use strict";

/* =========================================================================
 * RAG Learning — Web UI
 *
 * এই ফাইল শুধু backend API কে কল করে আর ফলাফল স্ক্রিনে দেখায় — RAG এর কোনো লজিক এখানে নেই।
 * ব্রাউজার /api/... তে রিকোয়েস্ট পাঠায়, nginx সেটা http://api:8000/... তে পাঠিয়ে দেয়
 * (frontend/nginx.conf দেখো)।
 *
 * কোনো framework (React ইত্যাদি) নেই — সাধারণ JavaScript, যাতে পড়ে বোঝা যায়।
 *
 * ফাইলের সাজানো:
 *   1. helper ফাংশন          4. মেসেজ আঁকা (render)
 *   2. state (অ্যাপের ডাটা)    5. প্রশ্ন পাঠানো (chat / search)
 *   3. API কল + streaming     6. sidebar: stats, upload, ingest, settings
 * ========================================================================= */

const API = "/api";

const SUGGESTIONS = [
  { tag: "সাধারণ RAG", q: "How many days can I work from home?" },
  { tag: "Cross-lingual", q: "আমি কত দিন annual leave পাবো?" },
  { tag: "বাংলা ডকুমেন্ট থেকে", q: "What is the fine for losing my ID card?" },
  { tag: "Hallucination টেস্ট", q: "Who is the CEO of Nexora Tech?" },
];

// ======================================================================
// 1. Helper
// ======================================================================
const $ = (selector) => document.querySelector(selector);

const icon = (name) => `<svg class="icon" aria-hidden="true"><use href="#i-${name}"/></svg>`;

const escapeHtml = (value) =>
  String(value).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);

const seconds = (ms) => `${(ms / 1000).toFixed(ms < 10000 ? 2 : 1)}s`;

const uid = () => Math.random().toString(36).slice(2, 10);

// localStorage ব্রাউজার ভেদে বন্ধ থাকতে পারে (private mode), তাই try/catch
const storage = {
  get(key, fallback) {
    try {
      const value = localStorage.getItem(key);
      return value === null ? fallback : JSON.parse(value);
    } catch {
      return fallback;
    }
  },
  set(key, value) {
    try {
      localStorage.setItem(key, JSON.stringify(value));
    } catch {
      /* সেভ না হলেও অ্যাপ চলবে */
    }
  },
};

// ---- ছোট markdown renderer (LLM এর উত্তরে **bold**, লিস্ট, `code` থাকে)
// আগে পুরো টেক্সট escape করি, তাই LLM এর উত্তরে HTML থাকলেও সেটা চলবে না (XSS নিরাপদ)।
const BN_DIGITS = "০১২৩৪৫৬৭৮৯";
const toLatinDigits = (s) => s.replace(/[০-৯]/g, (d) => BN_DIGITS.indexOf(d));

function inlineMarkdown(text) {
  return text
    .replace(/`([^`]+)`/g, "<code>$1</code>")
    .replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>")
    .replace(/(^|[\s(])\*(?!\s)(.+?)\*(?=[\s).,!?:;।]|$)/g, "$1<em>$2</em>")
    // [1], [2, 3], [১] -> ক্লিক করা যায় এমন citation বাটন
    .replace(/\[([0-9০-৯]+(?:\s*,\s*[0-9০-৯]+)*)\]/g, (_, list) =>
      list
        .split(",")
        .map((n) => {
          const k = toLatinDigits(n.trim());
          return `<button type="button" class="cite" data-cite="${k}" title="সোর্স ${k} দেখাও">${k}</button>`;
        })
        .join("")
    );
}

function renderMarkdown(text) {
  const out = [];
  let paragraph = [];
  let list = null; // "ul" | "ol" | null
  let code = null; // ``` ব্লকের ভেতরে থাকলে লাইনগুলো এখানে জমে

  const flushParagraph = () => {
    if (paragraph.length) out.push(`<p>${inlineMarkdown(paragraph.join("<br>"))}</p>`);
    paragraph = [];
  };
  const closeList = () => {
    if (list) out.push(`</${list}>`);
    list = null;
  };
  const openList = (tag) => {
    if (list !== tag) {
      closeList();
      out.push(`<${tag}>`);
      list = tag;
    }
  };

  for (const line of escapeHtml(text).split("\n")) {
    if (code !== null) {
      if (line.trim().startsWith("```")) {
        out.push(`<pre><code>${code.join("\n")}</code></pre>`);
        code = null;
      } else {
        code.push(line);
      }
      continue;
    }

    let m;
    if (line.trim().startsWith("```")) {
      flushParagraph();
      closeList();
      code = [];
    } else if ((m = line.match(/^#{1,6}\s+(.*)$/))) {
      flushParagraph();
      closeList();
      out.push(`<h4>${inlineMarkdown(m[1])}</h4>`);
    } else if ((m = line.match(/^\s*[-*•]\s+(.*)$/))) {
      flushParagraph();
      openList("ul");
      out.push(`<li>${inlineMarkdown(m[1])}</li>`);
    } else if ((m = line.match(/^\s*\d+[.)]\s+(.*)$/))) {
      flushParagraph();
      openList("ol");
      out.push(`<li>${inlineMarkdown(m[1])}</li>`);
    } else if (!line.trim()) {
      flushParagraph();
      closeList();
    } else {
      closeList();
      paragraph.push(line);
    }
  }

  if (code !== null) out.push(`<pre><code>${code.join("\n")}</code></pre>`);
  flushParagraph();
  closeList();
  return out.join("");
}

// ======================================================================
// 2. State — অ্যাপের সব ডাটা এক জায়গায়
// ======================================================================
const state = {
  mode: storage.get("rag.mode", "chat"), // "chat" (RAG + LLM) | "search" (শুধু retrieval)
  settings: { k: 4, showPrompt: false, ...storage.get("rag.settings", {}) },
  messages: storage.get("rag.messages", []).map((m) =>
    // রিফ্রেশের সময় কোনো উত্তর মাঝপথে থাকলে সেটাকে "থামানো" ধরি
    m.role === "assistant" && !["done", "error", "stopped"].includes(m.phase) ? { ...m, phase: "stopped" } : m
  ),
  stats: null,
  controller: null, // চলমান রিকোয়েস্ট থামানোর জন্য AbortController
};

const els = {
  sidebar: $("#sidebar"),
  chat: $("#chat"),
  messages: $("#messages"),
  form: $("#composer"),
  input: $("#input"),
  send: $("#sendBtn"),
  hint: $("#composerHint"),
  status: $("#status"),
  statFiles: $("#statFiles"),
  statChunks: $("#statChunks"),
  fileList: $("#fileList"),
  dropzone: $("#dropzone"),
  fileInput: $("#fileInput"),
  ingestBtn: $("#ingestBtn"),
  topk: $("#topk"),
  topkValue: $("#topkValue"),
  showPrompt: $("#showPrompt"),
  modelInfo: $("#modelInfo"),
  themeToggle: $("#themeToggle"),
  toasts: $("#toasts"),
};

const persistMessages = () => storage.set("rag.messages", state.messages.slice(-60));

// ======================================================================
// 3. API কল
// ======================================================================
async function errorFrom(res) {
  let detail = `${res.status} ${res.statusText}`;
  try {
    const body = await res.json();
    if (body.detail) detail = typeof body.detail === "string" ? body.detail : JSON.stringify(body.detail);
  } catch {
    /* JSON না হলে status টেক্সটই যথেষ্ট */
  }
  return new Error(detail);
}

async function api(path, options = {}) {
  const res = await fetch(API + path, options);
  if (!res.ok) throw await errorFrom(res);
  return res.json();
}

const postJson = (path, body, signal) =>
  api(path, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body), signal });

/**
 * Server-Sent Events (SSE) পড়া — backend এর /ask/stream থেকে উত্তর টুকরো টুকরো আসে।
 * ব্রাউজারের বিল্ট-ইন EventSource শুধু GET পারে, তাই fetch দিয়ে নিজেই পার্স করি।
 *
 * স্ট্রিমে প্রতিটা event দেখতে এরকম (মাঝে একটা ফাঁকা লাইন):
 *     event: token
 *     data: {"text": "আপনি বছরে"}
 */
async function streamEvents(path, body, onEvent, signal) {
  const res = await fetch(API + path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
    signal,
  });
  if (!res.ok || !res.body) throw await errorFrom(res);

  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  for (;;) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });

    // "\n\n" পেলেই একটা পুরো event হাতে এসেছে
    let end;
    while ((end = buffer.indexOf("\n\n")) !== -1) {
      const raw = buffer.slice(0, end);
      buffer = buffer.slice(end + 2);

      let event = "message";
      let data = "";
      for (const line of raw.split("\n")) {
        if (line.startsWith("event:")) event = line.slice(6).trim();
        else if (line.startsWith("data:")) data += line.slice(5).trim();
      }
      onEvent(event, data ? JSON.parse(data) : {});
    }
  }
}

function friendlyError(err) {
  const msg = err.message || String(err);
  if (/Failed to fetch|NetworkError|502|504/i.test(msg))
    return "API তে পৌঁছানো যাচ্ছে না। `docker compose ps` দিয়ে দেখো api container চলছে কিনা।";
  if (/429|RESOURCE_EXHAUSTED/.test(msg)) return `Gemini এর rate limit ছুঁয়ে গেছে — একটু পরে আবার চেষ্টা করো।\n\n${msg}`;
  if (/503|UNAVAILABLE/.test(msg)) return `Gemini এখন ব্যস্ত — কিছুক্ষণ পরে চেষ্টা করো, বা .env এ CHAT_MODEL বদলাও।\n\n${msg}`;
  if (/API key|PERMISSION_DENIED|401|403/.test(msg)) return `API key এ সমস্যা — .env এর GOOGLE_API_KEY দেখো।\n\n${msg}`;
  return msg;
}

// ======================================================================
// 4. মেসেজ আঁকা
// ======================================================================
function render() {
  els.messages.innerHTML = "";
  if (!state.messages.length) {
    els.messages.append(emptyState());
    return;
  }
  for (const m of state.messages) els.messages.append(messageElement(m));
  scrollToBottom();
}

function emptyState() {
  const el = document.createElement("div");
  el.className = "empty";
  const dbEmpty = state.stats && state.stats.chunks === 0;
  el.innerHTML = `
    <div class="empty-logo">${icon("sparkles")}</div>
    <h1>তোমার ডকুমেন্টকে প্রশ্ন করো</h1>
    <p class="empty-sub">উত্তর আসবে শুধু তোমার ডকুমেন্ট থেকে — সাথে দেখাবে ঠিক কোন অংশ থেকে এসেছে।</p>
    <div class="flow" aria-label="RAG pipeline">
      <span>${icon("file")}ডকুমেন্ট</span><i>→</i>
      <span>${icon("scissors")}চাঙ্ক</span><i>→</i>
      <span>${icon("hash")}Embedding</span><i>→</i>
      <span>${icon("database")}ChromaDB</span><i>→</i>
      <span>${icon("sparkles")}Gemini</span>
    </div>
    ${
      dbEmpty
        ? `<div class="callout">${icon("alert")}<span>Vector DB এখনো খালি। বাম পাশ থেকে ফাইল আপলোড করে <b>Rebuild index</b> চাপো।</span></div>`
        : ""
    }
    <div class="suggestions">
      ${SUGGESTIONS.map(
        (s) => `<button type="button" class="suggestion" data-q="${escapeHtml(s.q)}">
                  <span class="tag">${escapeHtml(s.tag)}</span><span class="q">${escapeHtml(s.q)}</span>
                </button>`
      ).join("")}
    </div>
    <p class="empty-foot">উদাহরণগুলো <code>sample_docs/</code> এর ডকুমেন্টের জন্য</p>`;
  return el;
}

function messageElement(m) {
  const el = document.createElement("div");
  el.className = `msg msg-${m.role}`;
  el.id = `msg-${m.id}`;
  el.innerHTML = m.role === "user" ? userHTML(m) : assistantHTML(m);
  return el;
}

function userHTML(m) {
  const tag = m.mode === "search" ? `<div class="bubble-tag">${icon("search")}শুধু Search</div>` : "";
  return `<div class="bubble">${tag}${escapeHtml(m.content)}</div>`;
}

function assistantHTML(m) {
  const parts = [traceHTML(m)];

  if (m.mode === "chat" && (m.content || m.phase === "generating")) {
    parts.push(`<div class="answer${m.phase === "generating" ? " typing" : ""}">${renderMarkdown(m.content)}</div>`);
  }
  if (m.mode === "search" && m.phase === "done") {
    parts.push(
      m.sources.length
        ? `<p class="note">${icon("info")}শুধু retrieval — LLM কল হয়নি। প্রশ্নের সাথে সবচেয়ে বেশি মেলে এমন চাঙ্কগুলো:</p>`
        : `<p class="note">${icon("info")}কিছু পাওয়া যায়নি — Vector DB খালি কিনা দেখো।</p>`
    );
  }
  if (m.phase === "stopped") parts.push(`<p class="note">${icon("info")}থামানো হয়েছে।</p>`);
  if (m.error) parts.push(`<div class="error-box">${icon("alert")}<div>${renderMarkdown(m.error)}</div></div>`);
  if (m.sources?.length) parts.push(sourcesHTML(m));
  if (state.settings.showPrompt && m.prompt) parts.push(promptHTML(m));
  if (m.phase === "done" && m.mode === "chat" && m.content) parts.push(actionsHTML(m));

  return `<div class="avatar">${icon("sparkles")}</div><div class="msg-body">${parts.join("")}</div>`;
}

// RAG এর ধাপগুলো লাইভ দেখাই: 🔎 Retrieval → ✨ Generation
function traceHTML(m) {
  const t = m.timings || {};
  const step = (status, iconName, text) =>
    `<span class="step ${status}">${status === "active" ? '<span class="spinner"></span>' : icon(iconName)}${text}</span>`;
  const steps = [];

  if (t.retrieval_ms != null) {
    steps.push(step("done", "search", `${m.sources.length}টা চাঙ্ক পাওয়া গেছে · ${seconds(t.retrieval_ms)}`));
  } else if (m.phase === "retrieving") {
    steps.push(step("active", "search", "প্রশ্ন embed করে Vector DB তে খোঁজা হচ্ছে…"));
  }

  if (m.mode === "chat" && t.retrieval_ms != null) {
    if (t.generation_ms != null) {
      steps.push(step("done", "zap", `উত্তর লেখা হয়েছে · ${seconds(t.generation_ms)}`));
    } else if (m.phase === "generating") {
      steps.push(step("active", "zap", `${escapeHtml(m.model || "LLM")} উত্তর লিখছে…`));
    }
  }

  return steps.length ? `<div class="trace">${steps.join('<span class="trace-arrow">→</span>')}</div>` : "";
}

function sourcesHTML(m) {
  const cards = m.sources
    .map((s, i) => {
      const n = i + 1;
      const ext = (s.source.split(".").pop() || "").toLowerCase().replace(/[^a-z0-9]/g, "");
      const width = Math.max(0, Math.min(1, s.similarity)) * 100;
      return `
        <article class="source-card" data-n="${n}">
          <header class="source-head">
            <span class="src-num">${n}</span>
            <span class="file-badge ext-${ext}">${ext.toUpperCase()}</span>
            <span class="src-name" title="${escapeHtml(s.source)}">${escapeHtml(s.source)}</span>
            <span class="src-meta">${s.page ? `পেজ ${s.page} · ` : ""}chunk #${s.chunk_id ?? "?"}</span>
          </header>
          <div class="sim" title="Cosine similarity — 1 এর যত কাছে, প্রশ্নের সাথে তত বেশি মিল">
            <span class="sim-label">similarity</span>
            <div class="sim-track"><div class="sim-fill" style="width:${width.toFixed(1)}%"></div></div>
            <span>${s.similarity.toFixed(3)}</span>
          </div>
          <p class="src-text">${escapeHtml(s.content)}</p>
          <button type="button" class="link-btn" data-action="expand">পুরোটা দেখাও</button>
        </article>`;
    })
    .join("");

  return `
    <details class="sources" data-key="sources"${m.mode === "search" ? " open" : ""}>
      <summary>${icon("database")}<span>${m.sources.length}টা সোর্স চাঙ্ক</span>
        <span class="summary-hint">Vector DB থেকে retrieve করা</span>${icon("chevron")}</summary>
      <div class="source-list">${cards}</div>
    </details>`;
}

function promptHTML(m) {
  return `
    <details class="prompt-box" data-key="prompt">
      <summary>${icon("terminal")}<span>LLM এ পাঠানো আসল prompt</span>${icon("chevron")}</summary>
      <pre>${escapeHtml(m.prompt)}</pre>
    </details>`;
}

function actionsHTML(m) {
  return `
    <div class="msg-actions">
      <button type="button" class="ghost-btn" data-action="copy">${icon("copy")}<span>Copy</span></button>
      <span class="meta">Top-K ${m.k} · ${escapeHtml(m.model || "")}</span>
    </div>`;
}

/** একটা assistant মেসেজ নতুন করে আঁকা — কোন সেকশন খোলা ছিল সেটা মনে রেখে। */
function updateMessage(m) {
  const el = document.getElementById(`msg-${m.id}`);
  if (!el) return;
  const stick = isNearBottom();
  const open = [...el.querySelectorAll("details[data-key]")].filter((d) => d.open).map((d) => d.dataset.key);
  const expanded = [...el.querySelectorAll(".source-card.expanded")].map((c) => c.dataset.n);

  el.innerHTML = assistantHTML(m);

  open.forEach((key) => el.querySelector(`details[data-key="${key}"]`)?.setAttribute("open", ""));
  expanded.forEach((n) => expandCard(el.querySelector(`.source-card[data-n="${n}"]`), true));
  if (stick) scrollToBottom();
}

/** streaming চলাকালীন শুধু উত্তরের অংশটা আপডেট (প্রতি frame এ সর্বোচ্চ একবার) */
let pendingFrame = null;
function scheduleAnswerUpdate(m) {
  if (pendingFrame) return;
  pendingFrame = requestAnimationFrame(() => {
    pendingFrame = null;
    const answer = document.querySelector(`#msg-${m.id} .answer`);
    if (!answer) return updateMessage(m);
    const stick = isNearBottom();
    answer.innerHTML = renderMarkdown(m.content);
    if (stick) scrollToBottom();
  });
}

const isNearBottom = () => els.chat.scrollHeight - els.chat.scrollTop - els.chat.clientHeight < 140;
const scrollToBottom = () => (els.chat.scrollTop = els.chat.scrollHeight);

function expandCard(card, expand) {
  if (!card) return;
  card.classList.toggle("expanded", expand);
  card.querySelector('[data-action="expand"]').textContent = expand ? "কম দেখাও" : "পুরোটা দেখাও";
}

function showSource(msgEl, n) {
  const details = msgEl.querySelector("details.sources");
  const card = msgEl.querySelector(`.source-card[data-n="${n}"]`);
  if (!details || !card) return;
  details.open = true;
  expandCard(card, true);
  card.scrollIntoView({ behavior: "smooth", block: "center" });
  card.classList.add("flash");
  setTimeout(() => card.classList.remove("flash"), 1600);
}

// ======================================================================
// 5. প্রশ্ন পাঠানো
// ======================================================================
async function send(text) {
  const question = text.trim();
  if (!question || state.controller) return;

  closeSidebar();
  if (!state.messages.length) els.messages.innerHTML = "";

  const user = { id: uid(), role: "user", mode: state.mode, content: question };
  const bot = {
    id: uid(),
    role: "assistant",
    mode: state.mode,
    phase: "retrieving", // retrieving -> generating -> done | error | stopped
    content: "",
    sources: [],
    prompt: null,
    timings: {},
    k: state.settings.k,
    model: state.stats?.chat_model,
  };
  state.messages.push(user, bot);
  els.messages.append(messageElement(user), messageElement(bot));
  scrollToBottom();

  els.input.value = "";
  autosize();
  state.controller = new AbortController();
  setBusy(true);

  try {
    if (bot.mode === "search") await runSearch(bot, question);
    else await runChat(bot, question);
  } catch (err) {
    if (err.name === "AbortError") {
      bot.phase = "stopped";
    } else {
      bot.phase = "error";
      bot.error = friendlyError(err);
    }
  } finally {
    cancelAnimationFrame(pendingFrame);
    pendingFrame = null;
    state.controller = null;
    setBusy(false);
    updateMessage(bot);
    persistMessages();
  }
}

/** পুরো RAG: backend আগে retrieve করা চাঙ্ক পাঠায়, তারপর LLM এর উত্তর টুকরো টুকরো */
async function runChat(bot, question) {
  await streamEvents(
    "/ask/stream",
    { question, k: bot.k },
    (event, data) => {
      if (event === "sources") {
        bot.sources = data.sources;
        bot.prompt = data.prompt;
        bot.timings.retrieval_ms = data.retrieval_ms;
        bot.phase = "generating";
        updateMessage(bot);
      } else if (event === "token") {
        bot.content += data.text;
        scheduleAnswerUpdate(bot);
      } else if (event === "done") {
        bot.timings.generation_ms = data.generation_ms;
        bot.phase = "done";
      } else if (event === "error") {
        throw new Error(data.message);
      }
    },
    state.controller.signal
  );
  if (bot.phase !== "done") throw new Error("উত্তর পুরো আসার আগেই সংযোগ বন্ধ হয়ে গেছে।");
}

/** শুধু Retrieval — LLM ছাড়া। কোন চাঙ্কগুলো আসছে সেটা দেখার জন্য। */
async function runSearch(bot, question) {
  const start = performance.now();
  const res = await postJson("/search", { question, k: bot.k }, state.controller.signal);
  bot.sources = res.results;
  bot.timings.retrieval_ms = performance.now() - start;
  bot.phase = "done";
}

function setBusy(busy) {
  els.send.classList.toggle("stop", busy);
  els.send.innerHTML = icon(busy ? "stop" : "arrow-up");
  els.send.setAttribute("aria-label", busy ? "থামাও" : "পাঠাও");
  els.send.disabled = !busy && !els.input.value.trim();
}

function autosize() {
  els.input.style.height = "auto";
  els.input.style.height = `${Math.min(els.input.scrollHeight, 200)}px`;
  if (!state.controller) els.send.disabled = !els.input.value.trim();
}

function setMode(mode) {
  state.mode = mode;
  storage.set("rag.mode", mode);
  document.querySelectorAll(".mode-switch button").forEach((b) => {
    const active = b.dataset.mode === mode;
    b.classList.toggle("active", active);
    b.setAttribute("aria-selected", active);
  });
  els.input.placeholder =
    mode === "chat" ? "তোমার ডকুমেন্ট নিয়ে প্রশ্ন করো…" : "কী খুঁজতে চাও? (শুধু retrieval — LLM কল হবে না)";
  els.hint.textContent =
    mode === "chat"
      ? "Enter = পাঠাও · Shift + Enter = নতুন লাইন · উত্তর আসে শুধু তোমার ডকুমেন্ট থেকে"
      : "Search mode: প্রশ্নের সাথে সবচেয়ে বেশি মেলে এমন চাঙ্কগুলো দেখাবে, LLM ছাড়া";
}

// ======================================================================
// 6. Sidebar: stats, upload, ingest, settings, theme
// ======================================================================
async function refreshStats() {
  try {
    const s = await api("/stats");
    state.stats = s;
    els.statFiles.textContent = s.files.length;
    els.statChunks.textContent = s.chunks;
    els.fileList.innerHTML = s.files.length
      ? s.files
          .map((f) => {
            const ext = (f.split(".").pop() || "").toLowerCase().replace(/[^a-z0-9]/g, "");
            return `<li title="${escapeHtml(f)}"><span class="file-badge ext-${ext}">${ext.toUpperCase()}</span><span>${escapeHtml(f)}</span></li>`;
          })
          .join("")
      : `<li class="empty-files">docs/ ফোল্ডার খালি</li>`;
    els.modelInfo.innerHTML = `
      <div><span>LLM</span><code title="${escapeHtml(s.chat_model)}">${escapeHtml(s.chat_model)}</code></div>
      <div><span>Embedding</span><code>${escapeHtml(s.embedding_model.replace("models/", ""))}</code></div>
      <div><span>Chunk</span><code>${s.chunk_size} / ${s.chunk_overlap}</code></div>`;
    if (!state.messages.length) render();
  } catch {
    /* status pill এ API offline দেখাবে */
  }
}

let apiWasDown = false;
async function checkHealth() {
  try {
    const h = await api("/health");
    const ok = h.chromadb === "ok";
    setStatus(ok ? "ok" : "warn", ok ? "Connected" : "ChromaDB সমস্যা");
    if (apiWasDown) refreshStats();
    apiWasDown = false;
  } catch {
    setStatus("err", "API offline");
    apiWasDown = true;
  }
}

function setStatus(kind, text) {
  els.status.className = `status ${kind}`;
  els.status.querySelector(".status-text").textContent = text;
  els.status.title = text;
}

async function uploadFiles(fileList) {
  const files = [...fileList].filter((f) => /\.(pdf|txt|md|docx)$/i.test(f.name));
  if (!files.length) return toast("শুধু PDF, TXT, MD আর DOCX ফাইল সাপোর্টেড।", "error");

  const form = new FormData();
  files.forEach((f) => form.append("files", f));

  const label = els.dropzone.querySelector(".dropzone-text");
  const original = label.innerHTML;
  els.dropzone.classList.add("busy");
  label.textContent = `${files.length}টা ফাইল আপলোড হচ্ছে…`;
  try {
    const res = await api("/upload", { method: "POST", body: form });
    await refreshStats();
    toast(`${res.saved.length}টা ফাইল আপলোড হয়েছে। এখন “Rebuild index” চাপো।`, "success");
    els.ingestBtn.classList.add("attention");
  } catch (err) {
    toast(friendlyError(err), "error");
  } finally {
    els.dropzone.classList.remove("busy");
    label.innerHTML = original;
  }
}

async function ingest() {
  const btn = els.ingestBtn;
  const original = btn.innerHTML;
  btn.disabled = true;
  btn.classList.remove("attention");
  btn.innerHTML = `<span class="spinner"></span><span>Indexing… (load → chunk → embed)</span>`;
  try {
    const res = await api("/ingest", { method: "POST" });
    await refreshStats();
    toast(`Index তৈরি: ${res.files.length}টা ফাইল → ${res.chunks}টা চাঙ্ক`, "success");
  } catch (err) {
    toast(friendlyError(err), "error", 8000);
  } finally {
    btn.disabled = false;
    btn.innerHTML = original;
  }
}

function toast(message, type = "info", ms = 4500) {
  const el = document.createElement("div");
  el.className = `toast toast-${type}`;
  el.setAttribute("role", type === "error" ? "alert" : "status");
  el.innerHTML = `${icon(type === "error" ? "alert" : type === "success" ? "check" : "info")}<span>${escapeHtml(message)}</span>`;
  els.toasts.append(el);
  setTimeout(() => el.classList.add("hide"), ms);
  setTimeout(() => el.remove(), ms + 400);
}

const currentTheme = () =>
  document.documentElement.dataset.theme || (matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light");

function updateThemeIcon() {
  els.themeToggle.innerHTML = icon(currentTheme() === "dark" ? "sun" : "moon");
}

const openSidebar = () => els.sidebar.classList.add("open");
const closeSidebar = () => els.sidebar.classList.remove("open");

async function copyText(text) {
  try {
    await navigator.clipboard.writeText(text);
  } catch {
    // পুরনো ব্রাউজারের জন্য fallback
    const ta = Object.assign(document.createElement("textarea"), { value: text });
    document.body.append(ta);
    ta.select();
    document.execCommand("copy");
    ta.remove();
  }
}

// ======================================================================
// Event listeners
// ======================================================================
els.form.addEventListener("submit", (e) => {
  e.preventDefault();
  if (state.controller) state.controller.abort(); // চলমান থাকলে বাটন = Stop
  else send(els.input.value);
});

els.input.addEventListener("input", autosize);
els.input.addEventListener("keydown", (e) => {
  // isComposing: বাংলা IME (যেমন Avro) দিয়ে লেখার সময় Enter যেন ভুল করে মেসেজ না পাঠায়
  if (e.key === "Enter" && !e.shiftKey && !e.isComposing) {
    e.preventDefault();
    els.form.requestSubmit();
  }
});

// মেসেজের ভেতরের সব ক্লিক এক জায়গায় (event delegation)
els.messages.addEventListener("click", async (e) => {
  const suggestion = e.target.closest(".suggestion");
  if (suggestion) return send(suggestion.dataset.q);

  const msgEl = e.target.closest(".msg");
  if (!msgEl) return;

  const cite = e.target.closest(".cite");
  if (cite) return showSource(msgEl, cite.dataset.cite);

  const action = e.target.closest("[data-action]");
  if (!action) return;

  if (action.dataset.action === "expand") {
    const card = action.closest(".source-card");
    expandCard(card, !card.classList.contains("expanded"));
  } else if (action.dataset.action === "copy") {
    const m = state.messages.find((x) => `msg-${x.id}` === msgEl.id);
    if (!m) return;
    await copyText(m.content);
    action.classList.add("done");
    action.innerHTML = `${icon("check")}<span>Copied</span>`;
    setTimeout(() => {
      action.classList.remove("done");
      action.innerHTML = `${icon("copy")}<span>Copy</span>`;
    }, 1500);
  }
});

document.querySelectorAll(".mode-switch button").forEach((b) => b.addEventListener("click", () => setMode(b.dataset.mode)));

$("#newChat").addEventListener("click", () => {
  state.controller?.abort();
  state.messages = [];
  persistMessages();
  render();
  closeSidebar();
  els.input.focus();
});

$("#openSidebar").addEventListener("click", openSidebar);
$("#closeSidebar").addEventListener("click", closeSidebar);
$("#scrim").addEventListener("click", closeSidebar);
document.addEventListener("keydown", (e) => e.key === "Escape" && closeSidebar());

els.themeToggle.addEventListener("click", () => {
  const next = currentTheme() === "dark" ? "light" : "dark";
  document.documentElement.dataset.theme = next;
  storage.set("rag.theme", next);
  updateThemeIcon();
});
matchMedia("(prefers-color-scheme: dark)").addEventListener("change", updateThemeIcon);

els.topk.addEventListener("input", () => {
  state.settings.k = Number(els.topk.value);
  els.topkValue.textContent = state.settings.k;
  storage.set("rag.settings", state.settings);
});

els.showPrompt.addEventListener("change", () => {
  state.settings.showPrompt = els.showPrompt.checked;
  storage.set("rag.settings", state.settings);
  render();
});

els.ingestBtn.addEventListener("click", ingest);
els.fileInput.addEventListener("change", () => {
  uploadFiles(els.fileInput.files);
  els.fileInput.value = "";
});

["dragenter", "dragover"].forEach((type) =>
  els.dropzone.addEventListener(type, (e) => {
    e.preventDefault();
    els.dropzone.classList.add("drag");
  })
);
["dragleave", "drop"].forEach((type) => els.dropzone.addEventListener(type, () => els.dropzone.classList.remove("drag")));
els.dropzone.addEventListener("drop", (e) => {
  e.preventDefault();
  uploadFiles(e.dataTransfer.files);
});
// ড্রপজোনের বাইরে ফাইল ছাড়লে ব্রাউজার যেন ফাইলটা খুলে না ফেলে
window.addEventListener("dragover", (e) => e.preventDefault());
window.addEventListener("drop", (e) => e.preventDefault());

// ======================================================================
// শুরু
// ======================================================================
els.topk.value = state.settings.k;
els.topkValue.textContent = state.settings.k;
els.showPrompt.checked = state.settings.showPrompt;
setMode(state.mode);
updateThemeIcon();
render();
checkHealth();
refreshStats();
setInterval(checkHealth, 15000);
els.input.focus();
