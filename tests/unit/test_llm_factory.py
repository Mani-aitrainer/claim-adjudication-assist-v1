import pytest

from app.core.llm_factory import get_llm


@pytest.fixture(autouse=True)
def _fake_openai_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-not-real")
    get_llm.cache_clear()


def test_get_llm_reads_temperature_from_yaml() -> None:
    llm = get_llm("adjudicator_agent")
    assert llm.temperature == 0.1
    assert llm.model_name == "gpt-4.1-mini"


def test_get_llm_is_cached() -> None:
    first = get_llm("intake_agent")
    second = get_llm("intake_agent")
    assert first is second
