"""Rue monkeypatch resource API."""

from __future__ import annotations

from pkgutil import resolve_name
from typing import Any

from rue.context.runtime import (
    CURRENT_RESOURCE_PROVIDER,
    CURRENT_RESOURCE_RESOLVER,
)
from rue.patching.runtime import PatchOwner, PatchScope, patch_manager


class MonkeyPatch:
    """Context-aware patch API injected as Rue's built-in resource."""

    def setattr(
        self,
        target: Any,
        name: str,
        value: Any,
        *,
        raising: bool = True,
        scope: PatchScope | None = None,
    ) -> None:
        """Replace an attribute while the selected Rue scope is active."""
        owner = PatchOwner.build(scope or self._default_scope())
        handle = patch_manager.setattr(
            target,
            name,
            value,
            owner=owner,
            raising=raising,
        )
        resolver = CURRENT_RESOURCE_RESOLVER.get()
        if resolver is None:
            handle.undo()
            raise RuntimeError(
                "MonkeyPatch can only be used inside Rue execution."
            )
        resolver.register_patch(handle)

    def setattr_path(
        self,
        import_path: str,
        value: Any,
        *,
        raising: bool = True,
        scope: PatchScope | None = None,
    ) -> None:
        """Replace an attribute addressed by a pkgutil-style import path."""
        target, name = self._resolve_attr_path(import_path)
        self.setattr(target, name, value, raising=raising, scope=scope)

    @staticmethod
    def _default_scope() -> PatchScope:
        if CURRENT_RESOURCE_PROVIDER.get() is not None:
            return "resource"
        return "test"

    @staticmethod
    def _resolve_attr_path(import_path: str) -> tuple[Any, str]:
        module_path, sep, attr_path = import_path.partition(":")
        if sep:
            parent_path, _, name = attr_path.rpartition(".")
            if not name:
                raise ValueError(
                    f"Patch path must name an attribute: {import_path}"
                )
            target_path = (
                module_path
                if not parent_path
                else f"{module_path}:{parent_path}"
            )
            return resolve_name(target_path), name

        target_path, _, name = import_path.rpartition(".")
        if not target_path or not name:
            raise ValueError(
                f"Patch path must name an attribute: {import_path}"
            )
        return resolve_name(target_path), name
