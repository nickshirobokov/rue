"""Resource injection system."""

from rue.context.scopes import Scope
from rue.patching import MonkeyPatch
from rue.resources.builtins import register_builtin_resources
from rue.resources.models import (
    LoadedResourceDef,
    ResourceSpec,
    ResourceTransferSnapshot,
)
from rue.resources.registry import ResourceRegistry, registry, resource
from rue.resources.resolver import ResourceResolver
from rue.resources.state import (
    ResolverLifecycleMode,
    ResourceCacheKey,
    ResourceStore,
    ResourceTeardownRecord,
    ResourceTransferState,
)
from rue.resources.transfer import ResourceTransfer


register_builtin_resources(registry)


__all__ = [
    "LoadedResourceDef",
    "MonkeyPatch",
    "ResolverLifecycleMode",
    "ResourceCacheKey",
    "ResourceRegistry",
    "ResourceResolver",
    "ResourceSpec",
    "ResourceStore",
    "ResourceTeardownRecord",
    "ResourceTransfer",
    "ResourceTransferSnapshot",
    "ResourceTransferState",
    "Scope",
    "register_builtin_resources",
    "registry",
    "resource",
]
