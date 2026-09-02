import pytest

from app.core.agent_config import AgentConfigRegistry
from app.core.exceptions import AgentConfigError


def test_defaults_merge_into_agent_entries() -> None:
    registry = AgentConfigRegistry()
    intake = registry.get("intake_agent")
    assert intake.model == "gpt-4.1-mini"        # inherited from defaults
    assert intake.temperature == 0.0
    assert intake.max_tokens == 2000              # overridden by the agent entry
    assert intake.pricing["input_per_1m"] == 0.40  # nested default preserved


def test_adjudicator_agent_has_expected_temperature() -> None:
    registry = AgentConfigRegistry()
    adjudicator = registry.get("adjudicator_agent")
    assert adjudicator.temperature == 0.1
    assert adjudicator.model == "gpt-4.1-mini"


def test_unknown_agent_key_fails_fast() -> None:
    registry = AgentConfigRegistry()
    with pytest.raises(AgentConfigError):
        registry.get("not_a_real_agent")


def test_env_override_wins(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AGENT__ADJUDICATOR_AGENT__TEMPERATURE", "0.4")
    registry = AgentConfigRegistry()
    assert registry.get("adjudicator_agent").temperature == 0.4
