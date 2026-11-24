/* Agentic RAG 前端逻辑：SSE 消费 + 决策时间线渲染 + 知识库管理 */
"use strict";

const $ = (sel) => document.querySelector(sel);
const chatWindow = $("#chat-window");
const questionBox = $("#question");
const btnSend = $("#btn-send");
const traceList = $("#trace-list");
const traceEmpty = $("#trace-empty");
const docList = $("#doc-list");

/* ---------------- 轻量 Markdown 渲染 ---------------- */
function esc(s) {
  return s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
}
function renderMD(text) {
  const lines = esc(text).split("\n");
  const out = [];
  let inList = false;
  for (const line of lines) {
    let li = line;
    // 列表项
    const isLi = /^\s*([-*•]|\d+[.、])\s+/.test(li);
    if (isLi && !inList) { out.push("<ul>"); inList = true; }
    if (!isLi && inList) { out.push("</ul>"); inList = false; }
    li = li
      .replace(/^\s*([-*•]|\d+[.、])\s+/, "<li>")
      .replace(/^(#{1,4})\s+(.*)$/, (_, h, t) => `<strong>${t}</strong>`)
      .replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>")
      .replace(/`([^`]+)`/g, "<code>$1</code>");
    if (inList && isLi) {
      out.push(li.endsWith("<li>") ? li : li + "</li>");
    } else if (li.trim() === "") {
      if (!inList) out.push("");
    } else {
      out.push(`<p>${li}</p>`);
    }
  }
  if (inList) out.push("</ul>");
  return out.join("\n");
}

/* ---------------- 消息渲染 ---------------- */
function addMessage(role, html, extraClass = "") {
  const wrap = document.createElement("div");
  wrap.className = `msg ${role} ${extraClass}`;
  const avatar = role === "user" ? "🧑‍💼" : "🤖";
  wrap.innerHTML = `<div class="avatar">${avatar}</div><div class="bubble">${html}</div>`;
  chatWindow.appendChild(wrap);
  chatWindow.scrollTop = chatWindow.scrollHeight;
  return wrap.querySelector(".bubble");
}

function renderSources(bubble, sources, confidence) {
  const confText = { high: "✅ 高置信", medium: "⚠️ 中置信（含联网或未核验内容）", low: "⚠️ 低置信（请谨慎采信）" };
  let html = `<div class="sources"><div class="sources-title">引用来源</div>`;
  sources.forEach((s) => {
    html += `<div class="source-item">${esc(s.source)}${s.section ? ` / ${esc(s.section)}` : ""}</div>`;
  });
  html += `</div><span class="confidence ${confidence}">${confText[confidence] || ""}</span>`;
  bubble.insertAdjacentHTML("beforeend", html);
}

/* ---------------- 决策时间线 ---------------- */
const STEP_ICONS = {
  route: "🧭", retrieve: "🔎", grade: "⚖️", rewrite: "✍️",
  web_search: "🌐", generate: "💬", check: "🧪", direct_chat: "💬", answer: "✅",
};
let traceStepCount = 0;

function addTraceItem(ev) {
  traceEmpty.style.display = "none";
  const li = document.createElement("li");
  li.className = "trace-item" + (ev.status === "warning" ? " warn" : "");
  li.innerHTML = `
    <span class="dot">${traceStepCount + 1}</span>
    <div class="t-label">
      <span>${STEP_ICONS[ev.step] || "•"} ${esc(ev.label)}</span>
      <span class="ms">${ev.duration_ms ?? "-"} ms</span>
    </div>
    <div class="t-detail">${esc(ev.detail || "")}</div>`;
  traceList.appendChild(li);
  li.scrollIntoView({ block: "nearest" });
  traceStepCount += 1;
}
function resetTrace() {
  traceList.innerHTML = "";
  traceEmpty.style.display = "";
  traceStepCount = 0;
}

/* ---------------- SSE 聊天 ---------------- */
let busy = false;

async function ask(question) {
  if (busy || !question.trim()) return;
  busy = true;
  btnSend.disabled = true;
  questionBox.value = "";
  addMessage("user", esc(question));
  const thinking = addMessage("assistant", `<span class="typing"><span></span><span></span><span></span></span>`);
  resetTrace();

  try {
    const resp = await fetch("/api/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ question }),
    });
    if (!resp.ok || !resp.body) throw new Error(`HTTP ${resp.status}`);

    const reader = resp.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      let idx;
      while ((idx = buffer.indexOf("\n\n")) !== -1) {
        const chunk = buffer.slice(0, idx);
        buffer = buffer.slice(idx + 2);
        if (!chunk.startsWith("data: ")) continue;
        handleEvent(JSON.parse(chunk.slice(6)), thinking);
      }
    }
  } catch (err) {
    thinking.innerHTML = `<div class="error-bubble">请求失败：${esc(String(err))}</div>`;
  } finally {
    busy = false;
    btnSend.disabled = false;
    questionBox.focus();
  }
}

function handleEvent(ev, thinking) {
  if (ev.type === "step") {
    addTraceItem(ev);
  } else if (ev.type === "answer") {
    thinking.innerHTML = renderMD(ev.answer);
    renderSources(thinking, ev.sources || [], ev.confidence);
    chatWindow.scrollTop = chatWindow.scrollHeight;
    (ev.trace || []).forEach((t, i) => { if (i >= traceStepCount) addTraceItem(t); });
  } else if (ev.type === "error") {
    thinking.innerHTML = `<div class="error-bubble">❌ ${esc(ev.message)}</div>`;
  }
}

/* ---------------- 健康检查 / 知识库 ---------------- */
async function refreshHealth() {
  try {
    const r = await fetch("/api/health");
    const h = await r.json();
    const chip = $("#chip-api");
    chip.textContent = h.api_key_configured ? "API Key ✓" : "API Key 未配置";
    chip.className = "chip " + (h.api_key_configured ? "ok" : "warn");
    const kb = $("#chip-kb");
    kb.textContent = `知识库 ${h.total_chunks} 条`;
    kb.className = "chip " + (h.total_chunks > 0 ? "ok" : "warn");
  } catch {
    $("#chip-api").textContent = "服务离线";
    $("#chip-api").className = "chip err";
  }
}

async function refreshDocs() {
  try {
    const r = await fetch("/api/documents");
    const d = await r.json();
    docList.innerHTML = "";
    (d.sources || []).forEach((s) => {
      const deprecated = /废止|停止执行/.test(s.status || "");
      const li = document.createElement("li");
      li.innerHTML = `
        <span class="name">
          <span class="status-tag ${deprecated ? "deprecated" : "current"}">${deprecated ? "废止" : "现行"}</span>
          ${esc(s.source)}
        </span>
        <span class="meta">${s.chunks} 块</span>`;
      docList.appendChild(li);
    });
    if (!d.sources?.length) docList.innerHTML = `<li><span class="meta">知识库为空</span></li>`;
  } catch { /* 忽略 */ }
}

async function uploadFile(file) {
  const fd = new FormData();
  fd.append("file", file);
  const chip = $("#chip-kb");
  chip.textContent = `上传中: ${file.name}`;
  try {
    const r = await fetch("/api/ingest", { method: "POST", body: fd });
    const d = await r.json();
    if (!r.ok) throw new Error(d.detail || "上传失败");
    chip.textContent = `知识库 ${d.total_chunks} 条`;
    chip.className = "chip ok";
    await refreshDocs();
  } catch (err) {
    chip.textContent = "上传失败";
    chip.className = "chip err";
    alert(String(err));
  }
}

async function rebuild() {
  if (!confirm("清空当前知识库并重新导入示例语料？")) return;
  const chip = $("#chip-kb");
  chip.textContent = "重建中…";
  try {
    const r = await fetch("/api/rebuild", { method: "POST" });
    const d = await r.json();
    if (!r.ok) throw new Error(d.detail || "重建失败");
    chip.textContent = `知识库 ${d.total_chunks} 条`;
    chip.className = "chip ok";
    await refreshDocs();
  } catch (err) {
    chip.textContent = "重建失败";
    chip.className = "chip err";
    alert(String(err));
  }
}

/* ---------------- 事件绑定 ---------------- */
btnSend.addEventListener("click", () => ask(questionBox.value));
questionBox.addEventListener("keydown", (e) => {
  if (e.key === "Enter" && !e.shiftKey) {
    e.preventDefault();
    ask(questionBox.value);
  }
});
document.querySelectorAll(".example").forEach((b) =>
  b.addEventListener("click", () => ask(b.dataset.q))
);
$("#file-input").addEventListener("change", (e) => {
  if (e.target.files[0]) uploadFile(e.target.files[0]);
  e.target.value = "";
});
$("#btn-rebuild").addEventListener("click", rebuild);

refreshHealth();
refreshDocs();
