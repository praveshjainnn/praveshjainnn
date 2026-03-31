"""
AgentWatch – unit tests for the monitoring engine.
Run with: python -m pytest tests/ -v
"""

import time
import pytest

from monitor import (
    AgentEvent,
    AgentMonitor,
    Alert,
    BulkEmailRule,
    DataDeletionRule,
    HighFrequencyRule,
    UnexpectedActionRule,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def monitor():
    return AgentMonitor()


def make_event(agent_id="agent-1", action="api_call", details="", ts=None):
    return AgentEvent(
        agent_id=agent_id,
        action=action,
        details=details,
        timestamp=ts or time.time(),
    )


# ---------------------------------------------------------------------------
# AgentMonitor – basic event recording
# ---------------------------------------------------------------------------

class TestEventRecording:
    def test_record_event_stores_event(self, monitor):
        evt = make_event()
        monitor.record_event(evt)
        events = monitor.get_events()
        assert len(events) == 1
        assert events[0]["agent_id"] == "agent-1"

    def test_auto_registers_unknown_agent(self, monitor):
        monitor.record_event(make_event(agent_id="new-bot"))
        agents = {a["agent_id"] for a in monitor.get_agents()}
        assert "new-bot" in agents

    def test_event_count_increments(self, monitor):
        monitor.record_event(make_event())
        monitor.record_event(make_event())
        agents = monitor.get_agents()
        assert agents[0]["event_count"] == 2

    def test_get_events_limit(self, monitor):
        for _ in range(10):
            monitor.record_event(make_event())
        assert len(monitor.get_events(limit=5)) == 5

    def test_get_events_filter_by_agent(self, monitor):
        monitor.record_event(make_event(agent_id="a1"))
        monitor.record_event(make_event(agent_id="a2"))
        assert len(monitor.get_events(agent_id="a1")) == 1


# ---------------------------------------------------------------------------
# AgentMonitor – agent registration
# ---------------------------------------------------------------------------

class TestAgentRegistration:
    def test_register_agent(self, monitor):
        monitor.register_agent("my-agent", {"version": "1.0"})
        agents = {a["agent_id"]: a for a in monitor.get_agents()}
        assert "my-agent" in agents
        assert agents["my-agent"]["version"] == "1.0"

    def test_register_with_allowed_actions_sets_rule_state(self, monitor):
        monitor.register_agent("strict-agent", {"allowed_actions": ["read", "write"]})
        key = "allowed:strict-agent"
        assert monitor._rule_state[key] == {"read", "write"}


# ---------------------------------------------------------------------------
# HighFrequencyRule
# ---------------------------------------------------------------------------

class TestHighFrequencyRule:
    def test_no_alert_below_threshold(self, monitor):
        rule = HighFrequencyRule(threshold=5, window=60)
        monitor.rules = [rule]
        for _ in range(4):
            alerts = monitor.record_event(make_event(agent_id="bot"))
            assert alerts == []

    def test_alert_at_threshold(self, monitor):
        rule = HighFrequencyRule(threshold=5, window=60)
        monitor.rules = [rule]
        fired = []
        for _ in range(5):
            fired.extend(monitor.record_event(make_event(agent_id="bot")))
        assert any(a.rule == "high_frequency_requests" for a in fired)

    def test_deduplication_within_window(self, monitor):
        rule = HighFrequencyRule(threshold=5, window=60)
        monitor.rules = [rule]
        for _ in range(10):
            monitor.record_event(make_event(agent_id="bot"))
        alerts = [a for a in monitor.alerts if a.rule == "high_frequency_requests"]
        assert len(alerts) == 1


# ---------------------------------------------------------------------------
# DataDeletionRule
# ---------------------------------------------------------------------------

class TestDataDeletionRule:
    def test_delete_action_fires_alert(self, monitor):
        monitor.rules = [DataDeletionRule()]
        alerts = monitor.record_event(make_event(action="delete"))
        assert any(a.rule == "data_deletion_detected" for a in alerts)

    def test_drop_action_fires_alert(self, monitor):
        monitor.rules = [DataDeletionRule()]
        alerts = monitor.record_event(make_event(action="drop"))
        assert any(a.rule == "data_deletion_detected" for a in alerts)

    def test_read_action_does_not_fire(self, monitor):
        monitor.rules = [DataDeletionRule()]
        alerts = monitor.record_event(make_event(action="read"))
        assert alerts == []

    def test_deletion_alert_severity_is_critical(self, monitor):
        monitor.rules = [DataDeletionRule()]
        alerts = monitor.record_event(make_event(action="delete"))
        assert alerts[0].severity == "critical"


# ---------------------------------------------------------------------------
# BulkEmailRule
# ---------------------------------------------------------------------------

class TestBulkEmailRule:
    def test_no_alert_below_threshold(self, monitor):
        rule = BulkEmailRule(threshold=5, window=60)
        monitor.rules = [rule]
        for _ in range(4):
            alerts = monitor.record_event(make_event(action="email"))
        assert not any(a.rule == "bulk_email_detected" for a in monitor.alerts)

    def test_alert_at_threshold(self, monitor):
        rule = BulkEmailRule(threshold=5, window=60)
        monitor.rules = [rule]
        fired = []
        for _ in range(5):
            fired.extend(monitor.record_event(make_event(action="email")))
        assert any(a.rule == "bulk_email_detected" for a in fired)

    def test_non_email_action_does_not_trigger(self, monitor):
        rule = BulkEmailRule(threshold=2, window=60)
        monitor.rules = [rule]
        for _ in range(5):
            monitor.record_event(make_event(action="api_call"))
        assert monitor.alerts == []


# ---------------------------------------------------------------------------
# UnexpectedActionRule
# ---------------------------------------------------------------------------

class TestUnexpectedActionRule:
    def test_fires_for_disallowed_action(self, monitor):
        monitor.rules = [UnexpectedActionRule()]
        monitor.register_agent("strict", {"allowed_actions": ["read"]})
        alerts = monitor.record_event(make_event(agent_id="strict", action="delete"))
        assert any(a.rule == "unexpected_action" for a in alerts)

    def test_no_alert_for_allowed_action(self, monitor):
        monitor.rules = [UnexpectedActionRule()]
        monitor.register_agent("strict", {"allowed_actions": ["read"]})
        alerts = monitor.record_event(make_event(agent_id="strict", action="read"))
        assert alerts == []

    def test_no_alert_when_no_allowed_list(self, monitor):
        monitor.rules = [UnexpectedActionRule()]
        monitor.register_agent("open-agent", {})
        alerts = monitor.record_event(make_event(agent_id="open-agent", action="anything"))
        assert alerts == []


# ---------------------------------------------------------------------------
# Alert management
# ---------------------------------------------------------------------------

class TestAlertManagement:
    def test_resolve_alert(self, monitor):
        monitor.rules = [DataDeletionRule()]
        fired = monitor.record_event(make_event(action="delete"))
        alert_id = fired[0].alert_id
        assert monitor.resolve_alert(alert_id) is True
        open_alerts = monitor.get_alerts(resolved=False)
        assert not any(a["alert_id"] == alert_id for a in open_alerts)

    def test_resolve_nonexistent_alert_returns_false(self, monitor):
        assert monitor.resolve_alert("nonexistent-id") is False

    def test_get_alerts_filter_by_agent(self, monitor):
        monitor.rules = [DataDeletionRule()]
        monitor.record_event(make_event(agent_id="a1", action="delete"))
        monitor.record_event(make_event(agent_id="a2", action="delete"))
        alerts_a1 = monitor.get_alerts(agent_id="a1")
        assert all(a["agent_id"] == "a1" for a in alerts_a1)


# ---------------------------------------------------------------------------
# Stats
# ---------------------------------------------------------------------------

class TestStats:
    def test_stats_reflect_recorded_events(self, monitor):
        monitor.rules = [DataDeletionRule()]
        monitor.record_event(make_event(action="read"))
        monitor.record_event(make_event(action="delete"))
        stats = monitor.get_stats()
        assert stats["total_events"] == 2
        assert stats["open_alerts"] == 1
        assert stats["critical_alerts"] == 1

    def test_stats_after_resolve(self, monitor):
        monitor.rules = [DataDeletionRule()]
        fired = monitor.record_event(make_event(action="delete"))
        monitor.resolve_alert(fired[0].alert_id)
        stats = monitor.get_stats()
        assert stats["open_alerts"] == 0
        assert stats["critical_alerts"] == 0
