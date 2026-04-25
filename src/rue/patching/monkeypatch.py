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

    def __init__(
        self,
        *,
        default_scope: PatchScope | None = None,
        allowed_scopes: tuple[PatchScope, ...] | None = None,
    ) -> None:
        self._scope = default_scope
        self._allowed_scopes = allowed_scopes

    @overload
    def setattr(
        self,
        import_path: str,
        value: Any,
        /,
        *,
        raising: bool = True,
        scope: PatchScope | None = None,
    ) -> None: ...

    @overload
    def setattr(
        self,
        target: Any,
        name: str,
        value: Any,
        *,
        raising: bool = True,
        scope: PatchScope | None = None,
    ) -> None: ...

    def setattr(
        self,
        target: Any,
        name: Any = _UNSET,
        value: Any = _UNSET,
        *,
        raising: bool = True,
        scope: PatchScope | None = None,
    ) -> None:
        """Replace an attribute while the selected Rue scope is active."""
        if isinstance(target, str) and value is _UNSET:
            if name is _UNSET:
                raise TypeError(
                    "Import-path attribute patches require a value."
                )
            module_path, sep, attr_path = target.partition(":")
            if sep:
                parent_path, _, attr_name = attr_path.rpartition(".")
                if not attr_name:
                    raise ValueError(
                        f"Patch path must name an attribute: {target}"
                    )
                patch_target = resolve_name(
                    module_path
                    if not parent_path
                    else f"{module_path}:{parent_path}"
                )
            else:
                target_path, _, attr_name = target.rpartition(".")
                if not target_path or not attr_name:
                    raise ValueError(
                        f"Patch path must name an attribute: {target}"
                    )
                patch_target = resolve_name(target_path)
            patch_value = name
        else:
            if name is _UNSET or value is _UNSET:
                raise TypeError(
                    "Object attribute patches require target, name, and "
                    "value."
                )
            patch_target = target
            attr_name = name
            patch_value = value

        owner = self._owner(scope)
        handle = patch_manager.setattr(
            patch_target,
            attr_name,
            patch_value,
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
        owner = self._owner(scope)
        handle = patch_manager.delattr(
            target,
            name,
            owner=owner,
            raising=raising,
        )
        if handle is not None:
            self._register(handle)

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

        owner = self._owner(scope)
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

        owner = self._owner(scope)
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

    def _owner(self, scope: PatchScope | None) -> PatchOwner:
        actual_scope = scope or self._default_scope()
        if (
            self._allowed_scopes is not None
            and actual_scope not in self._allowed_scopes
        ):
            allowed = ", ".join(self._allowed_scopes)
            raise ValueError(
                f"This monkeypatch only supports these scopes: {allowed}."
            )
        return PatchOwner.build(actual_scope)

    def _default_scope(self) -> PatchScope:
        if self._scope is not None:
            return self._scope
        if CURRENT_RESOURCE_PROVIDER.get() is not None:
            return "resource"
        return "test"
