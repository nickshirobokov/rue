"""Rue monkeypatch resource API."""

from __future__ import annotations

from collections.abc import MutableMapping, MutableSequence
from pkgutil import resolve_name
from typing import Any, overload

from rue.context.runtime import (
    CURRENT_RESOURCE_PROVIDER,
    CURRENT_RESOURCE_RESOLVER,
)
from rue.patching.runtime import (
    PatchHandle,
    PatchOwner,
    PatchScope,
    patch_manager,
)


_UNSET = object()


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
        self._register(handle)

    def delattr(
        self,
        target: Any,
        name: str,
        *,
        raising: bool = True,
        scope: PatchScope | None = None,
    ) -> None:
        """Delete an attribute while the selected Rue scope is active."""
        owner = PatchOwner.build(scope or self._default_scope())
        handle = patch_manager.delattr(
            target,
            name,
            owner=owner,
            raising=raising,
        )
        if handle is not None:
            self._register(handle)

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

    @overload
    def setitem(
        self,
        target: MutableMapping[Any, Any],
        key: Any,
        value: Any,
        *,
        idx: None = None,
        replace: None = None,
        scope: PatchScope | None = None,
    ) -> None: ...

    @overload
    def setitem(
        self,
        target: MutableSequence[Any],
        value: Any,
        /,
        *,
        idx: int,
        replace: bool,
        scope: PatchScope | None = None,
    ) -> None: ...

    def setitem(
        self,
        target: MutableMapping[Any, Any] | MutableSequence[Any],
        key: Any = _UNSET,
        value: Any = _UNSET,
        *,
        idx: int | None = None,
        replace: bool | None = None,
        scope: PatchScope | None = None,
    ) -> None:
        """Replace an item while the selected Rue scope is active."""
        if isinstance(target, MutableSequence):
            if value is not _UNSET:
                raise TypeError("List item patches use idx, not key.")
            if key is _UNSET:
                raise TypeError("List item patches require a value.")
            if idx is None or replace is None:
                raise TypeError(
                    "List item patches require idx and replace."
                )
            name = idx
            patch_value = key
        else:
            if key is _UNSET or value is _UNSET:
                raise TypeError(
                    "Mapping item patches require key and value."
                )
            if idx is not None or replace is not None:
                raise TypeError(
                    "Mapping item patches use key, not idx/replace."
                )
            name = key
            patch_value = value

        owner = PatchOwner.build(scope or self._default_scope())
        handle = patch_manager.setitem(
            target,
            name,
            patch_value,
            owner=owner,
            replace=replace,
        )
        self._register(handle)

    @overload
    def delitem(
        self,
        target: MutableMapping[Any, Any],
        key: Any,
        *,
        idx: None = None,
        replace: None = None,
        raising: bool = True,
        scope: PatchScope | None = None,
    ) -> None: ...

    @overload
    def delitem(
        self,
        target: MutableSequence[Any],
        *,
        idx: int,
        replace: bool,
        raising: bool = True,
        scope: PatchScope | None = None,
    ) -> None: ...

    def delitem(
        self,
        target: MutableMapping[Any, Any] | MutableSequence[Any],
        key: Any = _UNSET,
        *,
        idx: int | None = None,
        replace: bool | None = None,
        raising: bool = True,
        scope: PatchScope | None = None,
    ) -> None:
        """Delete an item while the selected Rue scope is active."""
        if isinstance(target, MutableSequence):
            if key is not _UNSET:
                raise TypeError("List item patches use idx, not key.")
            if idx is None or replace is None:
                raise TypeError(
                    "List item patches require idx and replace."
                )
            name = idx
        else:
            if key is _UNSET:
                raise TypeError("Mapping item patches require key.")
            if idx is not None or replace is not None:
                raise TypeError(
                    "Mapping item patches use key, not idx/replace."
                )
            name = key

        owner = PatchOwner.build(scope or self._default_scope())
        handle = patch_manager.delitem(
            target,
            name,
            owner=owner,
            raising=raising,
        )
        if handle is not None:
            self._register(handle)

    @staticmethod
    def _register(handle: PatchHandle) -> None:
        resolver = CURRENT_RESOURCE_RESOLVER.get()
        if resolver is None:
            handle.undo()
            raise RuntimeError(
                "MonkeyPatch can only be used inside Rue execution."
            )
        resolver.register_patch(handle)

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
