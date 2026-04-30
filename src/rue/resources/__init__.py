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
    ResourceTransferSnapshot,
)
from rue.resources.registry import ResourceRegistry, registry, resource
from rue.resources.resolver import ResourceResolver
from rue.resources.state import (
    ResourceStore,
    ResourceTeardownRecord,
)
from rue.resources.transfer import ResourceTransfer


_register_builtin_resources(registry)


__all__ = [
    "LoadedResourceDef",
    "MonkeyPatch",
    "ResourceFactoryKind",
    "ResourceGraph",
    "ResourceRegistry",
    "ResourceResolver",
    "ResourceSpec",
    "ResourceStore",
    "ResourceTeardownRecord",
    "ResourceTransfer",
    "ResourceTransferSnapshot",
    "Scope",
    "registry",
    "resource",
]
