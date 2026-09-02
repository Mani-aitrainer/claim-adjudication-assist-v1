"""Loads config/agents.yaml into per-agent configuration.

Loader contract:
- Deep-merges `defaults` into each agent entry.
- Env override wins: AGENT__ADJUDICATOR_AGENT__TEMPERATURE=0.3
- Validates on load; an unknown agent key fails fast with a clear message.
"""

import copy
import os
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict

from app.core.exceptions import AgentConfigError

DEFAULT_CONFIG_PATH = Path(__file__).resolve().parents[3] / "config" / "agents.yaml"

_ENV_PREFIX = "AGENT__"


class AgentConfig(BaseModel):
    """Resolved configuration for a single agent key. Extra keys (prompt, retry,
    retrieval, healing, dimensions, batch_size, ...) pass through untouched."""

    model_config = ConfigDict(extra="allow")

    provider: str = "openai"
    model: str
    temperature: float = 0.0
    max_tokens: int = 1500
    timeout_seconds: int = 60
    max_retries: int = 2
    pricing: dict[str, float] = {}


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    merged = copy.deepcopy(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def _coerce_scalar(raw: str) -> Any:
    loaded = yaml.safe_load(raw)
    return loaded


def _apply_env_overrides(agent_key: str, resolved: dict[str, Any]) -> dict[str, Any]:
    prefix = f"{_ENV_PREFIX}{agent_key.upper()}__"
    for env_key, env_value in os.environ.items():
        if not env_key.startswith(prefix):
            continue
        field_name = env_key[len(prefix) :].lower()
        resolved[field_name] = _coerce_scalar(env_value)
    return resolved


class AgentConfigRegistry:
    """Loads and validates config/agents.yaml, exposing resolved AgentConfig per key."""

    def __init__(self, config_path: Path = DEFAULT_CONFIG_PATH) -> None:
        self._config_path = config_path
        self._raw = self._load_yaml()
        self._defaults: dict[str, Any] = self._raw.get("defaults", {})
        self._agents_raw: dict[str, Any] = self._raw.get("agents", {})
        self._resolved: dict[str, AgentConfig] = {}
        self._resolve_all()

    def _load_yaml(self) -> dict[str, Any]:
        if not self._config_path.exists():
            raise AgentConfigError(f"agents.yaml not found at {self._config_path}")
        with self._config_path.open("r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        if "defaults" not in data or "agents" not in data:
            raise AgentConfigError(
                f"{self._config_path} must define top-level 'defaults' and 'agents' keys"
            )
        return data

    def _resolve_all(self) -> None:
        for agent_key, agent_overrides in self._agents_raw.items():
            merged = _deep_merge(self._defaults, agent_overrides or {})
            merged = _apply_env_overrides(agent_key, merged)
            try:
                self._resolved[agent_key] = AgentConfig(**merged)
            except Exception as exc:  # noqa: BLE001 - re-raised as AgentConfigError
                raise AgentConfigError(
                    f"invalid configuration for agent '{agent_key}': {exc}"
                ) from exc

    def get(self, agent_key: str) -> AgentConfig:
        if agent_key not in self._resolved:
            known = ", ".join(sorted(self._resolved))
            raise AgentConfigError(
                f"unknown agent key '{agent_key}'. Known agent keys: {known}"
            )
        return self._resolved[agent_key]

    def keys(self) -> list[str]:
        return sorted(self._resolved)


@lru_cache(maxsize=1)
def get_agent_config_registry() -> AgentConfigRegistry:
    return AgentConfigRegistry()


def get_agent_config(agent_key: str) -> AgentConfig:
    return get_agent_config_registry().get(agent_key)
