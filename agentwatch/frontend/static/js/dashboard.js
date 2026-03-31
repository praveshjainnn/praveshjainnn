/* =========================================================
   AgentWatch – Dashboard JavaScript
   ========================================================= */

const API = "";           // same origin
const MAX_EVENTS = 60;    // rows to keep in the live feed
const MAX_ALERTS = 30;

let eventsBuffer  = [];
let alertsBuffer  = [];
let agentsMap     = {};   // agent_id -> metadata

// ── DOM refs ───────────────────────────────────────────────
const $ = id => document.getElementById(id);

const connStatus   = $("conn-status");
const statTotal    = $("stat-total");
const statAgents   = $("stat-agents");
const statAlerts   = $("stat-alerts");
const statOpen     = $("stat-open");
const statCrit     = $("stat-crit");
const agentsList   = $("agents-list");
const alertsList   = $("alerts-list");
const eventsList   = $("events-list");
const alertBadge   = $("alerts-badge");
const sendForm     = $("event-form");

// ── Utilities ──────────────────────────────────────────────
function fmtTime(ts) {
  const d = new Date(ts * 1000);
  return d.toLocaleTimeString([], { hour12: false, hour: "2-digit", minute: "2-digit", second: "2-digit" });
}

function escHtml(s) {
  return String(s)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;");
}

function actionBadge(action) {
  const cls = escHtml(action.toLowerCase());
  return `<span class="action-badge ${cls}">${escHtml(action)}</span>`;
}

function sevBadge(severity) {
  return `<span class="sev-badge ${escHtml(severity)}">${escHtml(severity)}</span>`;
}

// ── Stats ──────────────────────────────────────────────────
function updateStats(s) {
  statTotal.textContent  = s.total_events  ?? 0;
  statAgents.textContent = s.total_agents  ?? 0;
  statAlerts.textContent = s.total_alerts  ?? 0;
  statOpen.textContent   = s.open_alerts   ?? 0;
  statCrit.textContent   = s.critical_alerts ?? 0;

  $("card-open").className = "stat-card" + (s.open_alerts > 0 ? " warn" : " ok");
  $("card-crit").className = "stat-card" + (s.critical_alerts > 0 ? " danger" : " ok");
}

async function fetchStats() {
  try {
    const r = await fetch(`${API}/api/stats`);
    if (r.ok) updateStats(await r.json());
  } catch (_) {}
}

// ── Agents ────────────────────────────────────────────────
function renderAgents() {
  const ids = Object.keys(agentsMap);
  if (!ids.length) {
    agentsList.innerHTML = `<div class="empty">No agents registered yet.</div>`;
    return;
  }
  agentsList.innerHTML = ids.map(id => {
    const m = agentsMap[id];
    const now = Date.now() / 1000;
    const active = m.last_seen && (now - m.last_seen) < 120;
    const events = m.event_count ?? 0;
    return `
      <div class="agent-row">
        <div class="agent-dot ${active ? "active" : "idle"}"></div>
        <div class="agent-name">${escHtml(id)}</div>
        <div class="agent-meta">${events} event${events !== 1 ? "s" : ""}</div>
      </div>`;
  }).join("");
}

async function fetchAgents() {
  try {
    const r = await fetch(`${API}/api/agents`);
    if (!r.ok) return;
    const list = await r.json();
    list.forEach(a => { agentsMap[a.agent_id] = a; });
    renderAgents();
  } catch (_) {}
}

// ── Alerts ────────────────────────────────────────────────
function renderAlerts() {
  alertBadge.textContent = alertsBuffer.filter(a => !a.resolved).length;
  alertsList.innerHTML = "";
  if (!alertsBuffer.length) {
    alertsList.innerHTML = `<div class="empty">✅ No alerts — all clear.</div>`;
    return;
  }
  alertsBuffer.forEach(a => {
    const item = document.createElement("div");
    item.className = `alert-item ${escHtml(a.severity)}`;
    item.dataset.id = a.alert_id;

    const header = document.createElement("div");
    header.className = "alert-header";
    header.innerHTML = `
      ${sevBadge(a.severity)}
      <span class="alert-rule">${escHtml(a.rule)}</span>
      <span class="alert-time">${fmtTime(a.timestamp)}</span>`;

    if (!a.resolved) {
      const btn = document.createElement("button");
      btn.className = "resolve-btn";
      btn.textContent = "Resolve";
      btn.addEventListener("click", () => resolveAlert(a.alert_id));
      header.appendChild(btn);
    } else {
      const span = document.createElement("span");
      span.style.cssText = "color:var(--green);font-size:11px;";
      span.textContent = "✓ resolved";
      header.appendChild(span);
    }

    const msg = document.createElement("div");
    msg.className = "alert-msg";
    msg.textContent = a.message;

    item.appendChild(header);
    item.appendChild(msg);
    alertsList.appendChild(item);
  });
}

async function fetchAlerts() {
  try {
    const r = await fetch(`${API}/api/alerts`);
    if (!r.ok) return;
    alertsBuffer = await r.json();
    renderAlerts();
  } catch (_) {}
}

async function resolveAlert(alertId) {
  try {
    const r = await fetch(`${API}/api/alerts/${encodeURIComponent(alertId)}/resolve`, { method: "POST" });
    if (r.ok) {
      const a = alertsBuffer.find(x => x.alert_id === alertId);
      if (a) a.resolved = true;
      renderAlerts();
      fetchStats();
    }
  } catch (_) {}
}

// ── Events feed ───────────────────────────────────────────
function renderEvents() {
  if (!eventsBuffer.length) {
    eventsList.innerHTML = `<div class="empty">Waiting for agent events…</div>`;
    return;
  }
  eventsList.innerHTML = [...eventsBuffer].reverse().map(e => `
    <div class="event-row">
      <span class="agent">${escHtml(e.agent_id)}</span>
      ${actionBadge(e.action)}
      <span class="sev-badge ${escHtml(e.severity)}" style="font-size:10px">${escHtml(e.severity)}</span>
      <span class="details">${escHtml(e.details || "—")}</span>
      <span class="etime">${fmtTime(e.timestamp)}</span>
    </div>`).join("");
}

function addEvent(e) {
  eventsBuffer.push(e);
  if (eventsBuffer.length > MAX_EVENTS) eventsBuffer.shift();
  // Update agent map
  if (!agentsMap[e.agent_id]) agentsMap[e.agent_id] = { event_count: 0 };
  agentsMap[e.agent_id].last_seen = e.timestamp;
  agentsMap[e.agent_id].event_count = (agentsMap[e.agent_id].event_count ?? 0) + 1;
  renderAgents();
  renderEvents();
}

function addAlert(a) {
  alertsBuffer.unshift(a);
  if (alertsBuffer.length > MAX_ALERTS) alertsBuffer.pop();
  renderAlerts();
}

async function fetchEvents() {
  try {
    const r = await fetch(`${API}/api/events?limit=50`);
    if (!r.ok) return;
    eventsBuffer = await r.json();
    renderEvents();
  } catch (_) {}
}

// ── SSE connection ────────────────────────────────────────
const SSE_MAX_RETRIES = 10;
const SSE_BASE_DELAY_MS = 1000;

function connectSSE(attempt = 0) {
  const es = new EventSource(`${API}/api/stream`);

  es.addEventListener("stats", e => {
    updateStats(JSON.parse(e.data));
  });

  es.addEventListener("event", e => {
    addEvent(JSON.parse(e.data));
    fetchStats();
  });

  es.addEventListener("alert", e => {
    addAlert(JSON.parse(e.data));
    fetchStats();
  });

  es.addEventListener("heartbeat", () => {
    renderAgents();  // refresh active/idle dots
  });

  es.onopen = () => {
    attempt = 0;  // reset backoff on successful connection
    connStatus.className = "connected";
    connStatus.querySelector(".label").textContent = "Live";
  };

  es.onerror = () => {
    es.close();
    if (attempt >= SSE_MAX_RETRIES) {
      connStatus.className = "error";
      connStatus.querySelector(".label").textContent = "Disconnected";
      return;
    }
    const delay = Math.min(SSE_BASE_DELAY_MS * 2 ** attempt, 30000);
    connStatus.className = "error";
    connStatus.querySelector(".label").textContent = "Reconnecting…";
    setTimeout(() => connectSSE(attempt + 1), delay);
  };
}

// ── Send-event form ───────────────────────────────────────
sendForm.addEventListener("submit", async e => {
  e.preventDefault();
  const fd = new FormData(sendForm);
  const payload = {
    agent_id: fd.get("agent_id").trim(),
    action:   fd.get("action").trim(),
    details:  fd.get("details").trim(),
    severity: fd.get("severity"),
  };
  if (!payload.agent_id || !payload.action) return;

  try {
    await fetch(`${API}/api/events`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    sendForm.querySelector("[name=details]").value = "";
  } catch (_) {}
});

// ── Init ──────────────────────────────────────────────────
(async function init() {
  await Promise.all([fetchStats(), fetchAgents(), fetchAlerts(), fetchEvents()]);
  connectSSE();
})();
