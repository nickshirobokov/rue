"""Resource injection system."""

from rue.context.scopes import Scope
from rue.patching import MonkeyPatch
from rue.resources.builtins import (
    register_builtin_resources as _register_builtin_resources,
)
from rue.resources.models import (
    LoadedResourceDef,
    ResourceFactoryKind,
    ResourceGraph,
    ResourceSpec,
    ScheduledTeardown,
    StateSnapshot,
)
from rue.resources.registry import ResourceRegistry, registry, resource
from rue.resources.resolver import DependencyResolver
from rue.resources.state import ResourceStore
from rue.resources.transfer import StateTransfer


_register_builtin_resources(registry)


__all__ = [
    "LoadedResourceDef",
    "MonkeyPatch",
    "ResourceFactoryKind",
    "ResourceGraph",
    "ResourceRegistry",
    "DependencyResolver",
    "ResourceSpec",
    "ResourceStore",
    "ScheduledTeardown",
    "StateTransfer",
    "StateSnapshot",
    "Scope",
    "registry",
    "resource",
]
