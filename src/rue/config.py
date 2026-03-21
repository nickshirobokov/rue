"""Configuration loading for the Rue CLI."""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass
from functools import cached_property
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, computed_field
from pydantic_ai.models import KnownModelName
from pydantic_ai.settings import ModelSettings
from pydantic_settings import BaseSettings, SettingsConfigDict


class PredicateConfig(BaseModel):
    """Config for a single predicate — model name plus optional ModelSettings fields."""

    model_config = ConfigDict(protected_namespaces=(), arbitrary_types_allowed=True)

    model: KnownModelName
    temperature: float | None = None
    max_tokens: int | None = None
    top_p: float | None = None
    timeout: float | None = None
    seed: int | None = None
    presence_penalty: float | None = None
    frequency_penalty: float | None = None
    stop_sequences: list[str] | None = None
    parallel_tool_calls: bool | None = None

    @computed_field
    @cached_property
    def model_settings(self) -> ModelSettings:
        model_settings: ModelSettings = {}

        if self.temperature is not None:
            model_settings["temperature"] = self.temperature
        if self.max_tokens is not None:
            model_settings["max_tokens"] = self.max_tokens
        if self.top_p is not None:
            model_settings["top_p"] = self.top_p
        if self.timeout is not None:
            model_settings["timeout"] = self.timeout
        if self.seed is not None:
            model_settings["seed"] = self.seed
        if self.presence_penalty is not None:
            model_settings["presence_penalty"] = self.presence_penalty
        if self.frequency_penalty is not None:
            model_settings["frequency_penalty"] = self.frequency_penalty
        if self.stop_sequences is not None:
            model_settings["stop_sequences"] = self.stop_sequences
        if self.parallel_tool_calls is not None:
            model_settings["parallel_tool_calls"] = self.parallel_tool_calls

        return model_settings


class PredicateSettings(BaseSettings):
    """All built-in predicate config loaded from `[tool.rue.predicates]`."""

    model_config = SettingsConfigDict(
        extra="forbid",
        pyproject_toml_table_header=("tool", "rue", "predicates"),
    )

    all_predicates: PredicateConfig | None = None
    follows_policy: PredicateConfig | None = None
    has_conflicting_facts: PredicateConfig | None = None
    has_facts: PredicateConfig | None = None
    has_topics: PredicateConfig | None = None
    has_unsupported_facts: PredicateConfig | None = None
    matches_facts: PredicateConfig | None = None
    matches_writing_layout: PredicateConfig | None = None
    matches_writing_style: PredicateConfig | None = None


@dataclass
class Config:
    """Resolved configuration values for running tests."""

    test_paths: list[str]
    include_tags: list[str]
    exclude_tags: list[str]
    keyword: str | None
    maxfail: int | None
    verbosity: int
    addopts: list[str]
    concurrency: int  # 1=sequential, 0=unlimited, max default=10
    timeout: float | None
    db_path: str | None
    save_to_db: bool
    reporters: list[str]
    reporter_options: dict[str, dict[str, Any]]
    predicates: PredicateSettings


DEFAULT_CONFIG = Config(
    test_paths=["."],
    include_tags=[],
    exclude_tags=[],
    keyword=None,
    maxfail=None,
    verbosity=0,
    addopts=[],
    concurrency=1,
    timeout=None,
    db_path=None,
    save_to_db=True,
    reporters=[],
    reporter_options={},
    predicates=PredicateSettings(),
)


def load_config(start_path: str | Path | None = None) -> Config:
    """Load configuration from pyproject.toml or rue.toml."""
    base = Path(start_path or Path.cwd()).resolve()
    config = Config(
        test_paths=list(DEFAULT_CONFIG.test_paths),
        include_tags=list(DEFAULT_CONFIG.include_tags),
        exclude_tags=list(DEFAULT_CONFIG.exclude_tags),
        keyword=DEFAULT_CONFIG.keyword,
        maxfail=DEFAULT_CONFIG.maxfail,
        verbosity=DEFAULT_CONFIG.verbosity,
        addopts=list(DEFAULT_CONFIG.addopts),
        concurrency=DEFAULT_CONFIG.concurrency,
        timeout=DEFAULT_CONFIG.timeout,
        db_path=DEFAULT_CONFIG.db_path,
        save_to_db=DEFAULT_CONFIG.save_to_db,
        reporters=list(DEFAULT_CONFIG.reporters),
        reporter_options=dict(DEFAULT_CONFIG.reporter_options),
        predicates=DEFAULT_CONFIG.predicates,
    )

    pyproject = _find_file(base, "pyproject.toml")
    if pyproject:
        data = _load_toml(pyproject)
        section = data.get("tool", {}).get("rue")
        if isinstance(section, dict):
            _apply_section(config, section)

    rue_toml = _find_file(base, "rue.toml")
    if rue_toml:
        data = _load_toml(rue_toml)
        _apply_section(config, data)

    env_db_path = os.getenv("RUE_DB_PATH")
    if env_db_path:
        config.db_path = env_db_path

    env_db_enabled = os.getenv("RUE_DB_ENABLED")
    if env_db_enabled is not None:
        config.save_to_db = env_db_enabled.strip().lower() not in {"0", "false", "no", "off"}

    if not config.test_paths:
        config.test_paths = list(DEFAULT_CONFIG.test_paths)

    return config


def _find_file(start: Path, filename: str) -> Path | None:
    """Search upwards from start for filename."""
    current = start
    while True:
        candidate = current / filename
        if candidate.exists():
            return candidate
        if current.parent == current:
            return None
        current = current.parent


def _load_toml(path: Path) -> dict[str, Any]:
    with path.open("rb") as fp:
        return tomllib.load(fp)


def _apply_section(config: Config, section: dict[str, Any]) -> None:
    """Apply a single config section to the resolved config."""
    mapping = {
        "test-paths": "test_paths",
        "test_paths": "test_paths",
        "include-tags": "include_tags",
        "include_tags": "include_tags",
        "exclude-tags": "exclude_tags",
        "exclude_tags": "exclude_tags",
        "keyword": "keyword",
        "maxfail": "maxfail",
        "verbosity": "verbosity",
        "addopts": "addopts",
        "concurrency": "concurrency",
        "timeout": "timeout",
        "db-path": "db_path",
        "db_path": "db_path",
        "save-to-db": "save_to_db",
        "save_to_db": "save_to_db",
        "reporters": "reporters",
    }

    for key, value in section.items():
        attr = mapping.get(key)
        if attr is None:
            # Handle reporter_options as a nested dict
            if key in {"reporter-options", "reporter_options"}:
                if isinstance(value, dict):
                    config.reporter_options = {
                        k: dict(v) for k, v in value.items() if isinstance(v, dict)
                    }
            continue
        if attr in {"test_paths", "include_tags", "exclude_tags", "addopts", "reporters"}:
            if isinstance(value, list):
                setattr(config, attr, [str(v) for v in value])
        elif attr == "verbosity":
            if isinstance(value, int):
                config.verbosity = value
        elif attr == "maxfail":
            if isinstance(value, int) and value > 0:
                config.maxfail = value
        elif attr == "keyword":
            if isinstance(value, str):
                config.keyword = value
        elif attr == "concurrency":
            if isinstance(value, int) and value >= 0:
                config.concurrency = value
        elif attr == "timeout":
            if isinstance(value, (int, float)) and value > 0:
                config.timeout = float(value)
        elif attr == "db_path":
            if isinstance(value, str):
                config.db_path = value
        elif attr == "save_to_db":
            if isinstance(value, bool):
                config.save_to_db = value

    predicates_raw = section.get("predicates")
    if isinstance(predicates_raw, dict):
        normalized = {k.replace("-", "_"): v for k, v in predicates_raw.items()}
        config.predicates = PredicateSettings.model_validate(normalized)


RueConfig = Config


__all__ = ["Config", "DEFAULT_CONFIG", "PredicateConfig", "RueConfig", "load_config"]
