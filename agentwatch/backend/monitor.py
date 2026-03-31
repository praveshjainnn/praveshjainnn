"""
AgentWatch – core monitoring & alert logic.

Each AI agent posts events to the backend.  The monitor keeps a rolling
in-memory store of events and evaluates configurable alert rules in real time.
"""

import time
import uuid
from collections import deque, defaultdict
from dataclasses import dataclass, field, asdict
from typing import List, Dict, Optional

# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------

@dataclass
class AgentEvent:
    agent_id: str
    action: str          # e.g. "api_call", "delete", "email", "read", "write"
    details: str = ""
    severity: str = "info"   # info | warning | error | critical
    timestamp: float = field(default_factory=time.time)
    event_id: str = field(default_factory=lambda: str(uuid.uuid4()))

    def to_dict(self) -> dict:
        d = asdict(self)
        d["timestamp_iso"] = time.strftime(
            "%Y-%m-%dT%H:%M:%SZ", time.gmtime(self.timestamp)
        )
        return d


@dataclass
class Alert:
    alert_id: str
    agent_id: str
    rule: str
    message: str
    severity: str = "warning"
    timestamp: float = field(default_factory=time.time)
    resolved: bool = False

    def to_dict(self) -> dict:
        d = asdict(self)
        d["timestamp_iso"] = time.strftime(
            "%Y-%m-%dT%H:%M:%SZ", time.gmtime(self.timestamp)
        )
        return d


# ---------------------------------------------------------------------------
# Alert rules
# ---------------------------------------------------------------------------

class AlertRule:
    """Base class for alert rules."""

    name: str = "base_rule"
    severity: str = "warning"

    def evaluate(
        self,
        event: AgentEvent,
        history: deque,
        state: dict,
    ) -> Optional[Alert]:
        raise NotImplementedError


class HighFrequencyRule(AlertRule):
    """Fires when an agent makes more than `threshold` requests in `window` seconds."""

    name = "high_frequency_requests"
    severity = "warning"

    def __init__(self, threshold: int = 20, window: int = 60):
        self.threshold = threshold
        self.window = window

    def evaluate(self, event: AgentEvent, history: deque, state: dict) -> Optional[Alert]:
        cutoff = event.timestamp - self.window
        recent = [e for e in history if e.agent_id == event.agent_id and e.timestamp >= cutoff]
        if len(recent) >= self.threshold:
            key = f"hf:{event.agent_id}"
            last_fired = state.get(key, 0)
            if event.timestamp - last_fired > self.window:
                state[key] = event.timestamp
                return Alert(
                    alert_id=str(uuid.uuid4()),
                    agent_id=event.agent_id,
                    rule=self.name,
                    message=(
                        f"Agent '{event.agent_id}' made {len(recent)} requests "
                        f"in the last {self.window}s (threshold: {self.threshold})."
                    ),
                    severity=self.severity,
                )
        return None


class DataDeletionRule(AlertRule):
    """Fires when an agent performs a delete action."""

    name = "data_deletion_detected"
    severity = "critical"

    def evaluate(self, event: AgentEvent, history: deque, state: dict) -> Optional[Alert]:
        if event.action.lower() in ("delete", "drop", "truncate", "destroy"):
            return Alert(
                alert_id=str(uuid.uuid4()),
                agent_id=event.agent_id,
                rule=self.name,
                message=(
                    f"Agent '{event.agent_id}' performed a destructive action: "
                    f"'{event.action}'. Details: {event.details or 'N/A'}"
                ),
                severity=self.severity,
            )
        return None


class BulkEmailRule(AlertRule):
    """Fires when an agent sends more than `threshold` emails in `window` seconds."""

    name = "bulk_email_detected"
    severity = "critical"

    def __init__(self, threshold: int = 10, window: int = 60):
        self.threshold = threshold
        self.window = window

    def evaluate(self, event: AgentEvent, history: deque, state: dict) -> Optional[Alert]:
        if event.action.lower() not in ("email", "send_email", "notify"):
            return None
        cutoff = event.timestamp - self.window
        recent_emails = [
            e for e in history
            if e.agent_id == event.agent_id
            and e.action.lower() in ("email", "send_email", "notify")
            and e.timestamp >= cutoff
        ]
        if len(recent_emails) >= self.threshold:
            key = f"email:{event.agent_id}"
            last_fired = state.get(key, 0)
            if event.timestamp - last_fired > self.window:
                state[key] = event.timestamp
                return Alert(
                    alert_id=str(uuid.uuid4()),
                    agent_id=event.agent_id,
                    rule=self.name,
                    message=(
                        f"Agent '{event.agent_id}' sent {len(recent_emails)} emails "
                        f"in the last {self.window}s (threshold: {self.threshold})."
                    ),
                    severity=self.severity,
                )
        return None


class UnexpectedActionRule(AlertRule):
    """Fires when an agent performs an action outside its declared allowed set."""

    name = "unexpected_action"
    severity = "warning"

    def evaluate(self, event: AgentEvent, history: deque, state: dict) -> Optional[Alert]:
        allowed = state.get(f"allowed:{event.agent_id}")
        if allowed and event.action.lower() not in allowed:
            return Alert(
                alert_id=str(uuid.uuid4()),
                agent_id=event.agent_id,
                rule=self.name,
                message=(
                    f"Agent '{event.agent_id}' performed unexpected action "
                    f"'{event.action}' (allowed: {', '.join(sorted(allowed))})."
                ),
                severity=self.severity,
            )
        return None


# ---------------------------------------------------------------------------
# Monitor
# ---------------------------------------------------------------------------

DEFAULT_RULES = [
    HighFrequencyRule(threshold=20, window=60),
    DataDeletionRule(),
    BulkEmailRule(threshold=10, window=60),
    UnexpectedActionRule(),
]


class AgentMonitor:
    """
    Central monitor that stores events, tracks agents, and evaluates alert rules.
    """

    def __init__(self, rules=None, max_events: int = 1000):
        self.rules: List[AlertRule] = rules if rules is not None else DEFAULT_RULES
        self.events: deque = deque(maxlen=max_events)
        self.alerts: List[Alert] = []
        self.agents: Dict[str, dict] = {}   # agent_id -> metadata
        self._rule_state: dict = {}          # mutable state shared across rule evaluations
        self._subscribers: List = []         # SSE subscriber queues

    # ------------------------------------------------------------------
    # Agent registration
    # ------------------------------------------------------------------

    def register_agent(self, agent_id: str, metadata: dict = None):
        """Register an agent and optionally specify its allowed actions."""
        self.agents[agent_id] = metadata or {}
        allowed = (metadata or {}).get("allowed_actions")
        if allowed:
            self._rule_state[f"allowed:{agent_id}"] = {a.lower() for a in allowed}

    # ------------------------------------------------------------------
    # Event ingestion
    # ------------------------------------------------------------------

    def record_event(self, event: AgentEvent) -> List[Alert]:
        """Store the event, auto-register agent if needed, and evaluate rules."""
        if event.agent_id not in self.agents:
            self.agents[event.agent_id] = {"auto_registered": True}

        self.events.append(event)

        # Update last-seen timestamp for the agent
        self.agents[event.agent_id]["last_seen"] = event.timestamp
        self.agents[event.agent_id].setdefault("event_count", 0)
        self.agents[event.agent_id]["event_count"] += 1

        fired: List[Alert] = []
        for rule in self.rules:
            try:
                alert = rule.evaluate(event, self.events, self._rule_state)
                if alert:
                    self.alerts.append(alert)
                    fired.append(alert)
                    self._notify_subscribers({"type": "alert", "data": alert.to_dict()})
            except Exception as exc:
                # Rules must never crash the ingestion path; log for debugging.
                import logging
                logging.getLogger(__name__).warning(
                    "Rule %s raised an exception for event %s: %s",
                    getattr(rule, "name", type(rule).__name__),
                    event.event_id,
                    exc,
                    exc_info=True,
                )

        self._notify_subscribers({"type": "event", "data": event.to_dict()})
        return fired

    # ------------------------------------------------------------------
    # Queries
    # ------------------------------------------------------------------

    def get_events(self, agent_id: str = None, limit: int = 100) -> List[dict]:
        events = list(self.events)
        if agent_id:
            events = [e for e in events if e.agent_id == agent_id]
        return [e.to_dict() for e in events[-limit:]]

    def get_alerts(self, agent_id: str = None, resolved: bool = None) -> List[dict]:
        alerts = self.alerts
        if agent_id:
            alerts = [a for a in alerts if a.agent_id == agent_id]
        if resolved is not None:
            alerts = [a for a in alerts if a.resolved == resolved]
        return [a.to_dict() for a in alerts]

    def get_agents(self) -> List[dict]:
        result = []
        for agent_id, meta in self.agents.items():
            entry = {"agent_id": agent_id, **meta}
            if "last_seen" in meta:
                entry["last_seen_iso"] = time.strftime(
                    "%Y-%m-%dT%H:%M:%SZ", time.gmtime(meta["last_seen"])
                )
            result.append(entry)
        return result

    def resolve_alert(self, alert_id: str) -> bool:
        for alert in self.alerts:
            if alert.alert_id == alert_id:
                alert.resolved = True
                return True
        return False

    def get_stats(self) -> dict:
        open_alerts = sum(1 for a in self.alerts if not a.resolved)
        critical_alerts = sum(1 for a in self.alerts if not a.resolved and a.severity == "critical")
        return {
            "total_events": len(self.events),
            "total_agents": len(self.agents),
            "total_alerts": len(self.alerts),
            "open_alerts": open_alerts,
            "critical_alerts": critical_alerts,
        }

    # ------------------------------------------------------------------
    # SSE helpers
    # ------------------------------------------------------------------

    def subscribe(self, queue):
        self._subscribers.append(queue)

    def unsubscribe(self, queue):
        try:
            self._subscribers.remove(queue)
        except ValueError:
            pass

    def _notify_subscribers(self, message: dict):
        dead = []
        for q in self._subscribers:
            try:
                q.put_nowait(message)
            except Exception:
                dead.append(q)
        for q in dead:
            self.unsubscribe(q)
