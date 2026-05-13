"""Configuration loading for the Rue CLI."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Annotated, Any, Self

from pydantic import (
    AliasGenerator,
    BaseModel,
    ConfigDict,
    Field,
    model_validator,
)
from pydantic_ai.models import KnownModelName
from pydantic_ai.settings import ModelSettings
from pydantic_settings import (
    BaseSettings,
    PydanticBaseSettingsSource,
    PyprojectTomlConfigSettingsSource,
    SettingsConfigDict,
    TomlConfigSettingsSource,
)


class AIModelConfig(BaseModel):
    """Model and request parameters for an AI-backed Rue component."""

    model_config = ConfigDict(
        protected_namespaces=(),
        populate_by_name=True,
        alias_generator=AliasGenerator(
            validation_alias=lambda name: name.replace("_", "-")
        ),
    )

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

    @property
    def model_settings(self) -> ModelSettings:
        """OpenAI-style model kwargs derived from optional config fields."""
        return self.model_dump(
            exclude={"model"},
            exclude_none=True,
        )  # type: ignore[return-value]


class PredicateSettings(BaseSettings):
    """Built-in predicate config from `[tool.rue.predicates]`."""

    model_config = SettingsConfigDict(
        extra="forbid",
        populate_by_name=True,
        alias_generator=AliasGenerator(
            validation_alias=lambda name: name.replace("_", "-")
        ),
        pyproject_toml_table_header=("tool", "rue", "predicates"),
    )

    all_predicates: AIModelConfig | None = None
    follows_policy: AIModelConfig | None = None
    has_conflicting_facts: AIModelConfig | None = None
    has_facts: AIModelConfig | None = None
    has_topic: AIModelConfig | None = None
    has_unsupported_facts: AIModelConfig | None = None
    matches_facts: AIModelConfig | None = None
    matches_writing_layout: AIModelConfig | None = None
    matches_writing_style: AIModelConfig | None = None

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        """Load predicate settings after standard settings sources."""
        return (
            init_settings,
            env_settings,
            dotenv_settings,
            file_secret_settings,
            PyprojectTomlConfigSettingsSource(settings_cls),
        )


class CaseFactorySettings(BaseSettings):
    """AI-backed case factory config from `[tool.rue.case-factories]`."""

    model_config = SettingsConfigDict(
        extra="forbid",
        populate_by_name=True,
        alias_generator=AliasGenerator(
            validation_alias=lambda name: name.replace("_", "-")
        ),
        pyproject_toml_table_header=("tool", "rue", "case-factories"),
    )

    edge_case_factory: AIModelConfig | None = None

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        """Load case factory settings after standard settings sources."""
        return (
            init_settings,
            env_settings,
            dotenv_settings,
            file_secret_settings,
            PyprojectTomlConfigSettingsSource(settings_cls),
        )


class Config(BaseSettings):
    """Resolved configuration values for running tests."""

    model_config = SettingsConfigDict(
        env_prefix="RUE_",
        populate_by_name=True,
        alias_generator=AliasGenerator(
            validation_alias=lambda name: name.replace("_", "-")
        ),
        pyproject_toml_table_header=("tool", "rue"),
        toml_file="rue.toml",
    )

    test_paths: list[str] = Field(default_factory=lambda: ["."])
    include_tags: list[str] = Field(default_factory=list)
    exclude_tags: list[str] = Field(default_factory=list)
    keyword: str | None = None
    maxfail: Annotated[int, Field(gt=0)] | None = None
    fail_fast: bool = False
    verbosity: int = 0
    addopts: list[str] = Field(default_factory=list)
    concurrency: Annotated[int, Field(ge=0)] = 1
    timeout: Annotated[float, Field(gt=0)] | None = None
    otel: bool = True
    database_path: Path = Path(".rue/rue.turso.db")
    processors: list[str] = Field(default_factory=list)
    predicates: PredicateSettings = Field(default_factory=PredicateSettings)
    case_factories: CaseFactorySettings = Field(
        default_factory=CaseFactorySettings
    )

    @model_validator(mode="after")
    def empty_test_paths_use_default(self) -> Self:
        r"""Match prior behavior: empty ``test-paths`` resets to ``["."]``."""
        if not self.test_paths:
            return self.model_copy(update={"test_paths": ["."]})
        return self

    def with_overrides(self, **kwargs: Any) -> Config:
        """Return a copy with non-None kwargs applied."""
        data = self.model_dump()
        data.update({k: v for k, v in kwargs.items() if v is not None})
        return type(self)(**data)

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        """Load config from init, env, ``rue.toml``, and ``[tool.rue]``."""
        return (
            init_settings,
            env_settings,
            TomlConfigSettingsSource(settings_cls),
            PyprojectTomlConfigSettingsSource(settings_cls),
        )


@lru_cache(maxsize=1)
def load_config() -> Config:
    """Load configuration from pyproject.toml, rue.toml, and environment."""
    return Config()


def reset_load_config_cache() -> None:
    """Drop the cached config so the next ``load_config()`` rebuilds."""
    load_config.cache_clear()


__all__ = [
    "AIModelConfig",
    "CaseFactorySettings",
    "Config",
    "load_config",
    "reset_load_config_cache",
]
