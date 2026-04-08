"""Configuration loading for the Rue CLI."""

from __future__ import annotations

from functools import lru_cache
from typing import Annotated, Self

from pydantic import (
    AliasChoices,
    AliasGenerator,
    BaseModel,
    ConfigDict,
    Field,
    computed_field,
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


class PredicateConfig(BaseModel):
    """Config for a single predicate — model name plus optional ModelSettings fields."""

    model_config = ConfigDict(
        protected_namespaces=(), arbitrary_types_allowed=True
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

    @computed_field
    @property
    def model_settings(self) -> ModelSettings:
        """OpenAI-style model kwargs derived from optional predicate fields."""
        return self.model_dump(
            exclude={"model"},
            exclude_none=True,
            exclude_computed_fields=True,
        )  # type: ignore[return-value]


class PredicateSettings(BaseSettings):
    """Built-in predicate config from `[tool.rue.predicates]` (also merged under `[tool.rue]`)."""

    model_config = SettingsConfigDict(
        extra="forbid",
        populate_by_name=True,
        alias_generator=AliasGenerator(
            validation_alias=lambda name: name.replace("_", "-")
        ),
        pyproject_toml_table_header=("tool", "rue", "predicates"),
    )

    all_predicates: PredicateConfig | None = None
    follows_policy: PredicateConfig | None = None
    has_conflicting_facts: PredicateConfig | None = None
    has_facts: PredicateConfig | None = None
    has_topic: PredicateConfig | None = Field(
        default=None,
        validation_alias=AliasChoices(
            "has_topic", "has-topic", "has_topics", "has-topics"
        ),
    )
    has_unsupported_facts: PredicateConfig | None = None
    matches_facts: PredicateConfig | None = None
    matches_writing_layout: PredicateConfig | None = None
    matches_writing_style: PredicateConfig | None = None

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        """Load order: init, env, dotenv, secrets, then ``[tool.rue.predicates]``."""
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
    verbosity: int = 0
    addopts: list[str] = Field(default_factory=list)
    concurrency: Annotated[int, Field(ge=0)] = 1
    timeout: Annotated[float, Field(gt=0)] | None = None
    otel: bool = True
    db_path: str | None = None
    db_enabled: bool = True
    reporters: list[str] = Field(default_factory=list)
    predicates: PredicateSettings = Field(default_factory=PredicateSettings)

    @model_validator(mode="after")
    def empty_test_paths_use_default(self) -> Self:
        r"""Match prior behavior: empty ``test-paths`` resets to ``["."]``."""
        if not self.test_paths:
            return self.model_copy(update={"test_paths": ["."]})
        return self

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,  # noqa: ARG003
        file_secret_settings: PydanticBaseSettingsSource,  # noqa: ARG003
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        """Load order: init, env, ``rue.toml``, ``[tool.rue]``, then field defaults."""
        return (
            init_settings,
            env_settings,
            TomlConfigSettingsSource(settings_cls),
            PyprojectTomlConfigSettingsSource(settings_cls),
        )


@lru_cache(maxsize=1)
def load_config() -> Config:
    """Load configuration from pyproject.toml, rue.toml, and environment.

    Cached for the process. Call ``reset_load_config_cache()`` after cwd/env changes.
    """
    return Config()


def reset_load_config_cache() -> None:
    """Drop the cached config so the next ``load_config()`` rebuilds."""
    load_config.cache_clear()


RueConfig = Config

__all__ = [
    "Config",
    "PredicateConfig",
    "RueConfig",
    "load_config",
    "reset_load_config_cache",
]
