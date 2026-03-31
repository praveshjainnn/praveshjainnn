"""
AgentWatch – Flask REST API + Server-Sent Events stream.

Endpoints
---------
POST /api/events          – ingest an agent event
GET  /api/events          – list recent events  (?agent_id=&limit=)
GET  /api/agents          – list known agents
POST /api/agents          – register an agent with metadata
GET  /api/alerts          – list alerts         (?agent_id=&resolved=)
POST /api/alerts/<id>/resolve – mark an alert resolved
GET  /api/stats           – summary statistics
GET  /api/stream          – SSE stream of events and alerts (real-time)
GET  /                    – serve the dashboard UI
"""

import json
import queue
import time

from flask import Flask, Response, jsonify, request, send_from_directory
from flask_cors import CORS

from monitor import AgentEvent, AgentMonitor

# ---------------------------------------------------------------------------
# Application setup
# ---------------------------------------------------------------------------

app = Flask(__name__, static_folder="../frontend", static_url_path="")
CORS(app)

monitor = AgentMonitor()

# Seed a few demo agents so the UI has something to show on first load
_DEMO_AGENTS = [
    {"agent_id": "email-bot-1",   "allowed_actions": ["read", "email", "notify"]},
    {"agent_id": "data-cleaner",  "allowed_actions": ["read", "write", "delete"]},
    {"agent_id": "report-agent",  "allowed_actions": ["read", "api_call", "write"]},
]
for _a in _DEMO_AGENTS:
    monitor.register_agent(_a["agent_id"], _a)


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def _bad(msg: str, code: int = 400):
    return jsonify({"error": msg}), code


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.route("/")
def index():
    return send_from_directory("../frontend", "index.html")


@app.route("/api/events", methods=["POST"])
def ingest_event():
    data = request.get_json(silent=True) or {}
    agent_id = data.get("agent_id", "").strip()
    action = data.get("action", "").strip()
    if not agent_id:
        return _bad("agent_id is required")
    if not action:
        return _bad("action is required")

    event = AgentEvent(
        agent_id=agent_id,
        action=action,
        details=data.get("details", ""),
        severity=data.get("severity", "info"),
        timestamp=data.get("timestamp", time.time()),
    )
    fired_alerts = monitor.record_event(event)
    return jsonify({
        "event": event.to_dict(),
        "alerts_fired": [a.to_dict() for a in fired_alerts],
    }), 201


@app.route("/api/events", methods=["GET"])
def list_events():
    agent_id = request.args.get("agent_id")
    limit = min(int(request.args.get("limit", 100)), 500)
    return jsonify(monitor.get_events(agent_id=agent_id, limit=limit))


@app.route("/api/agents", methods=["GET"])
def list_agents():
    return jsonify(monitor.get_agents())


@app.route("/api/agents", methods=["POST"])
def register_agent():
    data = request.get_json(silent=True) or {}
    agent_id = data.get("agent_id", "").strip()
    if not agent_id:
        return _bad("agent_id is required")
    monitor.register_agent(agent_id, data)
    return jsonify({"registered": agent_id}), 201


@app.route("/api/alerts", methods=["GET"])
def list_alerts():
    agent_id = request.args.get("agent_id")
    resolved_param = request.args.get("resolved")
    resolved = None
    if resolved_param is not None:
        resolved = resolved_param.lower() in ("true", "1", "yes")
    return jsonify(monitor.get_alerts(agent_id=agent_id, resolved=resolved))


@app.route("/api/alerts/<alert_id>/resolve", methods=["POST"])
def resolve_alert(alert_id: str):
    ok = monitor.resolve_alert(alert_id)
    if ok:
        return jsonify({"resolved": alert_id})
    return _bad("alert not found", 404)


@app.route("/api/stats", methods=["GET"])
def stats():
    return jsonify(monitor.get_stats())


# ---------------------------------------------------------------------------
# SSE stream
# ---------------------------------------------------------------------------

def _sse_format(event_type: str, data: dict) -> str:
    return f"event: {event_type}\ndata: {json.dumps(data)}\n\n"


@app.route("/api/stream")
def sse_stream():
    """
    Server-Sent Events endpoint.  The client receives:
      - event: agent_event  (new event ingested)
      - event: alert        (new alert fired)
      - event: heartbeat    (every 15 s to keep the connection alive)
    """
    q: queue.Queue = queue.Queue(maxsize=200)
    monitor.subscribe(q)

    def generate():
        try:
            # Send current stats as the first message
            yield _sse_format("stats", monitor.get_stats())
            last_heartbeat = time.time()
            while True:
                now = time.time()
                if now - last_heartbeat >= 15:
                    yield _sse_format("heartbeat", {"ts": now})
                    last_heartbeat = now
                try:
                    msg = q.get(timeout=1)
                    yield _sse_format(msg["type"], msg["data"])
                except queue.Empty:
                    pass
        finally:
            monitor.unsubscribe(q)

    return Response(
        generate(),
        mimetype="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import os
    host = os.environ.get("AGENTWATCH_HOST", "127.0.0.1")
    port = int(os.environ.get("AGENTWATCH_PORT", "5000"))
    app.run(host=host, port=port, debug=False, threaded=True)
