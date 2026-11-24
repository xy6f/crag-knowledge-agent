/* Agentic RAG 前端：类 DeepSeek/ChatGLM 交互
 * - 答案逐 token 流式打字机输出
 * - 决策过程内嵌可折叠「正在思考 ›」条，默认收起，结束变「已思考 N 秒」
 * - 用户向上滚动看历史时不再被强制拽底（悬浮回底按钮）
 * - 自研轻量 Markdown 块渲染器（代码块带复制 / 表格 / 标题 / 列表 / 引用）
 */
"use strict";

const $ = (s) => document.querySelector(s);
const chatWindow = $("#chat-window");
const questionBox = $("#question");
const btnSend = $("#btn-send");
const btnBottom = $("#btn-bottom");

/* ================= 轻量 Markdown 渲染器 ================= */
function esc(s) {
  return s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
}

function inline(s) {
  s = esc(s);
  s = s.replace(/`([^`]+)`/g, (_, c) => `<code>${c}</code>`);
  s = s.replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>");
  s = s.replace(/(^|[^*\w])\*([^*\n]+)\*(?=[^*]|$)/g, "$1<em>$2</em>");
  s = s.replace(/\[([^\]]+)\]\((https?:[^)\s]+)\)/g, '<a href="$2" target="_blank" rel="noopener">$1</a>');
  return s;
}

function renderTable(rows) {
  const isSep = (r) => /^\s*\|?[\s:|-]+\|?\s*$/.test(r) && r.includes("-");
  const cells = (r) => r.trim().replace(/^\|/, "").replace(/\|$/, "").split("|").map((c) => c.trim());
  const hasHead = rows.length > 1 && isSep(rows[1]);
  const body = rows.filter((r) => !isSep(r));
  if (!body.length) return "";
  let html = "<table>";
  if (hasHead) {
    html += "<thead><tr>" + cells(body[0]).map((h) => `<th>${inline(h)}</th>`).join("") + "</tr></thead><tbody>";
  }
  const data = hasHead ? body.slice(1) : body;
  for (const r of data) html += "<tr>" + cells(r).map((c) => `<td>${inline(c)}</td>`).join("") + "</tr>";
  html += hasHead ? "</tbody></table>" : "</table>";
  return html;
}

function renderMD(src) {
  if (!src) return "";
  // 先摘出围栏代码块，避免块解析时被拆散
  const fences = [];
  src = src.replace(/```(\w*)\r?\n([\s\S]*?)```/g, (_, lang, code) => {
    fences.push({ lang, code: code.replace(/\n$/, "") });
    return `\u0000F${fences.length - 1}\u0000`;
  });
  const lines = src.split(/\r?\n/);
  const out = [];
  let i = 0;
  const listRe = /^\s*([-*•]|\d+[.、)])\s+/;
  const blockRe = /^\s*([-*•]|\d+[.、)]\s|#|>|\||\u0000F)/;
  while (i < lines.length) {
    const line = lines[i];
    const fM = line.trim().match(/^\u0000F(\d+)\u0000$/);
    if (fM) {
      const f = fences[+fM[1]];
      out.push(
        `<div class="codeblock"><button class="copy-btn" type="button">复制</button><pre><code>${esc(f.code)}</code></pre></div>`
      );
      i++; continue;
    }
    if (!line.trim()) { i++; continue; }
    if (/^\s*\|.*\|\s*$/.test(line)) {
      const rows = [];
      while (i < lines.length && /^\s*\|.*\|\s*$/.test(lines[i])) rows.push(lines[i++]);
      out.push(renderTable(rows)); continue;
    }
    let h = line.match(/^(#{1,4})\s+(.*)$/);
    if (h) {
      const lv = Math.min(Math.max(h[1].length, 3), 4);
      out.push(`<h${lv}>${inline(h[2])}</h${lv}>`); i++; continue;
    }
    if (/^\s*(-{3,}|\*{3,})\s*$/.test(line)) { out.push("<hr>"); i++; continue; }
    if (/^\s*>\s?/.test(line)) {
      const buf = [];
      while (i < lines.length && /^\s*>\s?/.test(lines[i])) buf.push(lines[i++].replace(/^\s*>\s?/, ""));
      out.push(`<blockquote>${inline(buf.join("<br>"))}</blockquote>`); continue;
    }
    if (listRe.test(line)) {
      const ordered = /^\s*\d+/.test(line);
      const items = [];
      while (i < lines.length && listRe.test(lines[i])) items.push(lines[i++].replace(listRe, ""));
      const tag = ordered ? "ol" : "ul";
      out.push(`<${tag}>${items.map((it) => `<li>${inline(it)}</li>`).join("")}</${tag}>`);
      continue;
    }
    const buf = [line]; i++;
    while (i < lines.length && lines[i].trim() && !blockRe.test(lines[i])) buf.push(lines[i++]);
    out.push(`<p>${inline(buf.join("\n")).replace(/\n/g, "<br>")}</p>`);
  }
  return out.join("\n");
}

/* 代码块复制 */
chatWindow.addEventListener("click", (e) => {
  const btn = e.target.closest(".copy-btn");
  if (!btn) return;
  const code = btn.parentElement.querySelector("code").textContent;
  (navigator.clipboard?.writeText(code) ?? Promise.reject())
    .then(() => { btn.textContent = "已复制 ✓"; setTimeout(() => (btn.textContent = "复制"), 1500); })
    .catch(() => { btn.textContent = "复制失败"; });
});

/* ================= 滚动粘性 ================= */
let stick = true;
chatWindow.addEventListener("scroll", () => {
  stick = chatWindow.scrollHeight - chatWindow.scrollTop - chatWindow.clientHeight < 90;
  btnBottom.hidden = stick;
});
btnBottom.addEventListener("click", () => {
  chatWindow.scrollTop = chatWindow.scrollHeight;
  stick = true;
  btnBottom.hidden = true;
});
function maybeScroll() { if (stick) chatWindow.scrollTop = chatWindow.scrollHeight; }

/* ================= 消息结构 ================= */
let cur = null; // 当前助手消息的渲染上下文

function addMessage(role, text) {
  const wrap = document.createElement("div");
  wrap.className = `msg ${role}`;
  if (role === "user") {
    wrap.innerHTML = `<div class="bubble"></div>`;
    wrap.querySelector(".bubble").textContent = text;
  } else {
    wrap.innerHTML = `
      <div class="think running" hidden>
        <div class="think-head">
          <span class="think-dot"></span>
          <span class="think-title">正在思考</span>
          <span class="think-sub"></span>
          <span class="think-chevron">›</span>
        </div>
        <ul class="think-steps"></ul>
      </div>
      <div class="answer streaming"></div>
      <div class="msg-foot"></div>`;
    chatWindow.appendChild(wrap);
    const think = wrap.querySelector(".think");
    think.querySelector(".think-head").addEventListener("click", () => think.classList.toggle("open"));
    cur = {
      root: wrap,
      think,
      thinkSub: think.querySelector(".think-sub"),
      thinkTitle: think.querySelector(".think-title"),
      steps: think.querySelector(".think-steps"),
      answer: wrap.querySelector(".answer"),
      foot: wrap.querySelector(".msg-foot"),
      deltas: "",
      renderTimer: null,
      startedAt: performance.now(),
    };
    maybeScroll();
    return null;
  }
  chatWindow.appendChild(wrap);
  maybeScroll();
}

/* ================= SSE 事件处理 ================= */
const STEP_ICON = {
  route: "🧭", retrieve: "🔎", grade: "⚖️", rewrite: "✍️",
  web_search: "🌐", generate: "💬", check: "🧪", direct_chat: "💬", answer: "✅",
};

function scheduleRender() {
  if (cur.renderTimer || !cur) return;
  cur.renderTimer = setTimeout(() => {
    cur.renderTimer = null;
    cur.answer.innerHTML = renderMD(cur.deltas);
    maybeScroll();
  }, 80);
}

function finishThink(label) {
  if (!cur || cur.think.hidden) { if (cur) cur.think.remove(); return; }
  cur.think.classList.remove("running");
  const secs = ((performance.now() - cur.startedAt) / 1000).toFixed(1);
  cur.thinkTitle.textContent = label || `已思考 ${secs} 秒`;
  cur.thinkSub.textContent = "";
}

function handleEvent(ev) {
  if (!cur) return;
  switch (ev.type) {
    case "step": {
      cur.think.hidden = false;
      cur.thinkSub.textContent = `· ${ev.label}`;
      const li = document.createElement("li");
      if (ev.status === "warning") li.className = "warn";
      li.innerHTML = `
        <div class="step-line"><span>${STEP_ICON[ev.step] || "•"} ${esc(ev.label)}</span><span class="ms">${ev.duration_ms ?? "-"} ms</span></div>
        <div class="step-detail">${esc(ev.detail || "")}</div>`;
      cur.steps.appendChild(li);
      break;
    }
    case "reset":
      cur.deltas = "";
      if (cur.renderTimer) { clearTimeout(cur.renderTimer); cur.renderTimer = null; }
      cur.answer.innerHTML = "";
      break;
    case "delta":
      cur.deltas += ev.text;
      scheduleRender();
      break;
    case "answer": {
      // 最终答案以服务端全文为准（补平可能丢失的增量）
      cur.deltas = ev.answer || cur.deltas;
      if (cur.renderTimer) { clearTimeout(cur.renderTimer); cur.renderTimer = null; }
      cur.answer.classList.remove("streaming");
      cur.answer.innerHTML = renderMD(cur.deltas);
      finishThink();
      renderFoot(ev.sources || [], ev.confidence || "medium");
      maybeScroll();
      break;
    }
    case "error": {
      cur.answer.classList.remove("streaming");
      if (!cur.deltas) cur.answer.innerHTML = `<div class="error-bubble">❌ ${esc(ev.message)}</div>`;
      finishThink("思考已中断");
      break;
    }
  }
}

const CONF_TEXT = { high: "✅ 高置信", medium: "⚠️ 中置信（含联网或未核验内容）", low: "⚠️ 低置信（请谨慎采信）" };
function renderFoot(sources, confidence) {
  let html = `<div class="sources"><div class="sources-title">引用来源</div>`;
  sources.forEach((s) => {
    html += `<div class="source-item">${esc(s.source)}${s.section ? ` / ${esc(String(s.section).slice(0, 60))}` : ""}</div>`;
  });
  html += `</div><span class="confidence ${confidence}">${CONF_TEXT[confidence] || ""}</span>`;
  cur.foot.innerHTML = html;
}

/* ================= 发送 ================= */
let busy = false;
const history = []; // 供 direct_chat 用的多轮上下文

async function ask(question) {
  if (busy || !question.trim()) return;
  busy = true;
  btnSend.disabled = true;
  questionBox.value = "";
  questionBox.style.height = "auto";
  stick = true;
  addMessage("user", question);
  addMessage("bot", "");

  try {
    const resp = await fetch("/api/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ question, history: history.slice(-6) }),
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
        if (chunk.startsWith("data: ")) {
          try { handleEvent(JSON.parse(chunk.slice(6))); } catch { /* 忽略半包 */ }
        }
      }
    }
    if (cur && cur.deltas) {
      history.push({ role: "user", content: question });
      history.push({ role: "assistant", content: cur.deltas });
    }
  } catch (err) {
    if (cur) {
      cur.answer.classList.remove("streaming");
      cur.answer.innerHTML = `<div class="error-bubble">请求失败：${esc(String(err))}</div>`;
    }
  } finally {
    if (cur) cur.answer.classList.remove("streaming");
    busy = false;
    btnSend.disabled = false;
    cur = null;
    btnBottom.hidden = stick;
    questionBox.focus();
  }
}

/* ================= 输入绑定 ================= */
btnSend.addEventListener("click", () => ask(questionBox.value));
questionBox.addEventListener("keydown", (e) => {
  if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); ask(questionBox.value); }
});
questionBox.addEventListener("input", () => {
  questionBox.style.height = "auto";
  questionBox.style.height = Math.min(questionBox.scrollHeight, 140) + "px";
});
document.querySelectorAll(".example").forEach((b) => b.addEventListener("click", () => ask(b.dataset.q)));

/* ================= 抽屉 ================= */
const drawer = $("#kb-drawer");
const backdrop = $("#drawer-backdrop");
function toggleDrawer(open) {
  drawer.classList.toggle("open", open);
  backdrop.hidden = !open;
}
$("#btn-kb").addEventListener("click", () => toggleDrawer(!drawer.classList.contains("open")));
$("#btn-drawer-close").addEventListener("click", () => toggleDrawer(false));
backdrop.addEventListener("click", () => toggleDrawer(false));

/* ================= 健康 / 知识库 ================= */
async function refreshHealth() {
  try {
    const h = await (await fetch("/api/health")).json();
    const chip = $("#chip-api");
    chip.textContent = h.api_key_configured ? "API Key ✓" : "API Key 未配置";
    chip.className = "chip " + (h.api_key_configured ? "ok" : "warn");
    const kb = $("#chip-kb");
    kb.textContent = `知识库 ${h.total_chunks} 条`;
    kb.className = "chip " + (h.total_chunks > 0 ? "ok" : "warn");
    $("#kb-total").textContent = h.total_chunks;
  } catch {
    $("#chip-api").textContent = "服务离线";
    $("#chip-api").className = "chip err";
  }
}

async function refreshDocs() {
  try {
    const d = await (await fetch("/api/documents")).json();
    const docList = $("#doc-list");
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

$("#file-input").addEventListener("change", async (e) => {
  const file = e.target.files[0];
  e.target.value = "";
  if (!file) return;
  const fd = new FormData();
  fd.append("file", file);
  const chip = $("#chip-kb");
  chip.textContent = `上传中…`;
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
  }
});

$("#btn-rebuild").addEventListener("click", async () => {
  if (!confirm("清空当前知识库并重新导入示例语料？")) return;
  try {
    const r = await fetch("/api/rebuild", { method: "POST" });
    const d = await r.json();
    if (!r.ok) throw new Error(d.detail || "重建失败");
    await refreshHealth();
    await refreshDocs();
  } catch { /* 忽略 */ }
});

refreshHealth();
refreshDocs();
