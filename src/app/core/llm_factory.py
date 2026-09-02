"""Builds cached, metrics-instrumented ChatOpenAI clients from config/agents.yaml.

No node ever constructs an LLM itself. Every call through the returned wrapper records
agent_tokens_total, agent_cost_usd_total and llm_calls_total — this is the one place LLM
call metrics are recorded, so no agent needs its own metrics code for that.
"""

from functools import cache
from typing import Any

from langchain_openai import ChatOpenAI
from pydantic import SecretStr

from app.core.agent_config import get_agent_config
from app.core.exceptions import LLMFactoryError
from app.core.settings import get_settings
from app.observability.cost import compute_cost_usd
from app.observability.metrics import agent_cost_usd_total, agent_tokens_total, llm_calls_total


class InstrumentedChatModel:
    """Wraps a ChatOpenAI instance. Delegates attribute access (temperature, model_name,
    ...) to the wrapped model — only `invoke` is intercepted, to record metrics."""

    def __init__(self, chat_model: ChatOpenAI, agent_key: str, pricing: dict[str, float]) -> None:
        self._chat_model = chat_model
        self._agent_key = agent_key
        self._pricing = pricing

    def __getattr__(self, item: str) -> Any:
        return getattr(self._chat_model, item)

    def invoke(self, messages: Any) -> Any:
        model = self._chat_model.model_name
        try:
            response = self._chat_model.invoke(messages)
        except Exception:
            llm_calls_total.labels(agent=self._agent_key, model=model, outcome="error").inc()
            raise

        usage = getattr(response, "usage_metadata", None) or {}
        input_tokens = usage.get("input_tokens", 0)
        output_tokens = usage.get("output_tokens", 0)
        if input_tokens or output_tokens:
            agent_tokens_total.labels(agent=self._agent_key, model=model, token_type="input").inc(
                input_tokens
            )
            agent_tokens_total.labels(
                agent=self._agent_key, model=model, token_type="output"
            ).inc(output_tokens)
            cost = compute_cost_usd(input_tokens, output_tokens, self._pricing)
            agent_cost_usd_total.labels(agent=self._agent_key, model=model).inc(cost)

        llm_calls_total.labels(agent=self._agent_key, model=model, outcome="success").inc()
        return response


@cache
def get_llm(agent_key: str) -> Any:
    """Returns a cached, instrumented ChatOpenAI configured per config/agents.yaml
    agents.<agent_key>."""
    config = get_agent_config(agent_key)
    settings = get_settings()

    if config.provider != "openai":
        raise LLMFactoryError(
            f"agent '{agent_key}' requests provider '{config.provider}', "
            "but only 'openai' is currently supported"
        )

    chat_model = ChatOpenAI(
        model=config.model,
        temperature=config.temperature,
        max_tokens=config.max_tokens,
        timeout=config.timeout_seconds,
        max_retries=config.max_retries,
        api_key=SecretStr(settings.openai_api_key) if settings.openai_api_key else None,
    )
    return InstrumentedChatModel(chat_model, agent_key, config.pricing)
