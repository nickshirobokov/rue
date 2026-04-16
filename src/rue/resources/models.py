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


class TransferStrategy(Enum):
    """How a resolved resource should be transferred to a worker process."""

    SERIALIZE = "serialize"
    RE_RESOLVE = "re_resolve"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class ResourceIdentity:
    """Canonical identity for one resolved resource provider."""

    name: str
    scope: Scope
    provider_path: str | None = None
    provider_dir: str | None = None

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


@dataclass(slots=True, eq=False)
class ResourceDef:
    """Definition of a registered resource."""

    identity: ResourceIdentity
    fn: Callable[..., Any]
    is_async: bool
    is_generator: bool
    is_async_generator: bool
    dependencies: list[str] = field(default_factory=list)
    on_resolve: Callable[[Any], Any] | None = None
    on_injection: Callable[[Any], Any] | None = None
    on_teardown: Callable[[Any], Any] | None = None


@dataclass(frozen=True, slots=True)
class SelectedResource:
    """Selected resource provider for one resolution request."""

    definition: ResourceDef


@dataclass(frozen=True, slots=True)
class ResourceTransferEntry:
    """One resource's transfer plan within a blueprint."""

    identity: ResourceIdentity
    strategy: TransferStrategy
    serialized_value: bytes | None
    dependencies: tuple[ResourceIdentity, ...]


@dataclass(frozen=True, slots=True)
class ResourceBlueprint:
    """Complete transfer payload for reconstructing resources in a worker."""

    entries: tuple[ResourceTransferEntry, ...]
    resolution_order: tuple[ResourceIdentity, ...]
    request_path: str | None
