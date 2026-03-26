"""Resource injection system."""

from rue.resources.resolver import (
    ResourceDef,
    ResourceResolver,
    Scope,
    clear_registry,
    get_registry,
    resource,
    register_builtin,
)


__all__ = [
    "ResourceDef",
    "ResourceResolver",
    "Scope",
    "clear_registry",
    "get_registry",
    "register_builtin",
    "resource",
]

from rue.resources import builtins