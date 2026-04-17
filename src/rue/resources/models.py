"""Resource model types."""

from collections.abc import Callable
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any


class Scope(Enum):
    """Resource lifecycle scope."""

    TEST = "test"  # Fresh instance per test
    MODULE = "module"  # Shared across tests in same file
    PROCESS = "process"  # Shared across entire test run


@dataclass(frozen=True, slots=True)
class ResourceSpec:
    """Canonical spec for one resolved resource provider."""

    name: str
    scope: Scope
    provider_path: str | None = None
    provider_dir: str | None = None
    dependencies: tuple[str, ...] = field(default=(), compare=False)

    @property
    def origin_path(self) -> Path | None:
        if self.provider_path is None:
            return None
        return Path(self.provider_path)

    @property
    def origin_dir(self) -> Path | None:
        if self.provider_dir is None:
            return None
        return Path(self.provider_dir)

    @property
    def snapshot_key(self) -> str:
        return "|".join(
            (
                self.scope.value,
                self.name,
                self.provider_path or "",
                self.provider_dir or "",
            )
        )


@dataclass(slots=True, eq=False)
class LoadedResourceDef:
    """Definition of a registered resource."""

    spec: ResourceSpec
    fn: Callable[..., Any]
    is_async: bool
    is_generator: bool
    is_async_generator: bool
    on_resolve: Callable[[Any], Any] | None = None
    on_injection: Callable[[Any], Any] | None = None
    on_teardown: Callable[[Any], Any] | None = None


@dataclass(frozen=True, slots=True)
class SelectedResource:
    """Selected resource provider for one resolution request."""

    definition: LoadedResourceDef


@dataclass(frozen=True, slots=True)
class ResourceBlueprint:
    """Complete transfer payload for reconstructing resources in a worker."""

    res_specs: tuple[ResourceSpec, ...]
    request_path: str | None
    root_ids: dict[str, int] = field(default_factory=dict)
    nodes: dict[int, dict[str, Any]] = field(default_factory=dict)
    ignored_paths: dict[str, list[str]] = field(default_factory=dict)
    resolution_order: tuple[ResourceSpec, ...] = field(
        default_factory=tuple,
    )
