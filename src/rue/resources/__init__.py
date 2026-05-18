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
    SubprocessResourceSnapshot,
)
from rue.resources.registry import ResourceRegistry, registry, resource
from rue.resources.resolver import DependencyResolver
from rue.resources.store import ResourceStore


_register_builtin_resources(registry)


__all__ = [
    "DependencyResolver",
    "LoadedResourceDef",
    "MonkeyPatch",
    "ResourceFactoryKind",
    "ResourceGraph",
    "ResourceRegistry",
    "ResourceSpec",
    "ResourceStore",
    "ScheduledTeardown",
    "Scope",
    "SubprocessResourceSnapshot",
    "registry",
    "resource",
]
