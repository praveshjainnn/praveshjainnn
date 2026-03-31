# AgentWatch 🛡️

> **Real-time monitoring & alerting for AI agents** — "Your AI agent went rogue, and you had no idea."

Every company deploying AI agents will face the same nightmare: an agent starts making
unexpected requests, deletes data, sends thousands of emails — and you find out *after*
the damage is done. AgentWatch is **Datadog for AI agents**: a lightweight, self-hostable
monitoring dashboard that gives you full visibility into what your agents are doing and
alerts you the moment behaviour deviates from expectations.

---

## Features

| Feature | Description |
|---|---|
| 📥 **Event ingestion** | POST any agent action (read, write, delete, email, api_call, …) via a simple REST API |
| 🤖 **Agent registry** | Register agents with optional *allowed-action* lists |
| 🚨 **Real-time alerts** | Rule-based anomaly detection fires instantly |
| ⚡ **Live dashboard** | Server-Sent Events push every event & alert to the browser without polling |
| ✅ **Alert resolution** | One-click resolve from the UI; re-open via API |
| 📊 **Stats overview** | Total events, agent count, open/critical alerts at a glance |
| 🧪 **Simulate panel** | Send test events from the UI to exercise your alert rules |

### Built-in alert rules

| Rule | Trigger |
|---|---|
| `high_frequency_requests` | Agent exceeds N requests in a rolling time window |
| `data_deletion_detected` | Agent performs `delete`, `drop`, `truncate`, or `destroy` |
| `bulk_email_detected` | Agent sends more than N emails in a rolling time window |
| `unexpected_action` | Agent takes an action outside its declared `allowed_actions` list |

---

## Quick start

```bash
# 1. Install dependencies
cd agentwatch
pip install -r requirements.txt

# 2. Start the server
cd backend
python app.py
# → listening on http://localhost:5000

# 3. Open the dashboard
open http://localhost:5000
```

---

## REST API reference

### Ingest an event
```http
POST /api/events
Content-Type: application/json

{
  "agent_id": "my-agent",
  "action":   "delete",
  "details":  "Dropped table users",
  "severity": "critical"
}
```

### List events
```http
GET /api/events?agent_id=my-agent&limit=50
```

### Register an agent (with allowed actions)
```http
POST /api/agents
Content-Type: application/json

{
  "agent_id": "strict-agent",
  "allowed_actions": ["read", "write"]
}
```

### List agents / alerts / stats
```http
GET /api/agents
GET /api/alerts?agent_id=my-agent&resolved=false
GET /api/stats
```

### Resolve an alert
```http
POST /api/alerts/<alert_id>/resolve
```

### Real-time SSE stream
```http
GET /api/stream
```
Events emitted: `agent_event`, `alert`, `heartbeat`, `stats`.

---

## Running tests

```bash
cd agentwatch/backend
python -m pytest tests.py -v
```

All 25 tests cover:
- Event recording & agent auto-registration
- All four alert rules (including edge cases)
- Alert management (resolve, filter by agent)
- Stats accuracy

---

## Project structure

```
agentwatch/
├── backend/
│   ├── app.py       – Flask REST API + SSE stream
│   ├── monitor.py   – Core monitoring engine & alert rules
│   └── tests.py     – Pytest test suite (25 tests)
├── frontend/
│   ├── index.html   – Dashboard UI
│   └── static/
│       ├── css/dashboard.css
│       └── js/dashboard.js
└── requirements.txt
```

---

## How it works

```
AI Agent  →  POST /api/events  →  AgentMonitor.record_event()
                                       │
                              ┌────────┴────────┐
                              │  Evaluate rules  │
                              └────────┬────────┘
                                       │ Alert?
                          ┌────────────┴───────────────┐
                          │  Append to alerts list      │
                          │  Push to SSE subscribers    │
                          └────────────────────────────-┘
                                       │
                              Browser (SSE stream)
                              ├── Live event feed
                              ├── Alert panel
                              └── Stats cards
```
