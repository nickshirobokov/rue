"""Iteration decorators for Rue tests."""

from __future__ import annotations

from collections.abc import Callable, Iterable, Sequence
from typing import Any

from rue.testing.models import (
    Case,
    CaseGroup,
    CasesIterateModifier,
    GroupsIterateModifier,
    IterateModifier,
    ParameterSet,
    ParamsIterateModifier,
)


class IterateDecorator:
    """Primary entry-point for iterating Rue tests."""

    def _attach_modifier(
        self,
        target: Callable[..., Any],
        modifier: object,
    ) -> Callable[..., Any]:
        modifiers: list[Any] = getattr(target, "__rue_modifiers__", [])
        modifiers.append(modifier)
        target.__rue_modifiers__ = modifiers  # type: ignore[attr-defined]
        target.__rue_test__ = True  # type: ignore[attr-defined]
        return target

    def _resolve_min_passes(
        self,
        name: str,
        count: int,
        min_passes: int | None,
    ) -> int:
        actual_min_passes = min_passes if min_passes is not None else count
        if actual_min_passes < 1:
            raise ValueError(
                f"{name} min_passes must be >= 1, got {actual_min_passes}"
            )
        if actual_min_passes > count:
            raise ValueError(
                f"{name} min_passes ({actual_min_passes}) cannot exceed count ({count})"
            )
        return actual_min_passes

    def __call__(
        self,
        count: int,
        *,
        min_passes: int | None = None,
    ) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
        if count < 1:
            raise ValueError(f"iterate() count must be >= 1, got {count}")

        actual_min_passes = self._resolve_min_passes(
            "iterate()",
            count,
            min_passes,
        )
        modifier = IterateModifier(
            count=count,
            min_passes=actual_min_passes,
        )

        def decorator(target: Callable[..., Any]) -> Callable[..., Any]:
            return self._attach_modifier(target, modifier)

        return decorator

    def params(
        self,
        argnames: str | Sequence[str],
        argvalues: Iterable[Any],
        *,
        ids: Sequence[str] | None = None,
        min_passes: int | None = None,
    ) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
        match argnames:
            case str():
                names = tuple(n.strip() for n in argnames.split(",") if n.strip())
            case _:
                names = tuple(str(n) for n in argnames)

        values_list: list[tuple[Any, ...]] = []
        parse_error: str | None = None
        for raw in (argvalues if names else ()):
            match raw:
                case tuple() | list() if len(raw) == len(names):
                    values_list.append(tuple(raw))
                case tuple() | list():
                    parse_error = f"iterate.params() expected {len(names)} values, got {len(raw)}"
                    break
                case _ if len(names) == 1:
                    values_list.append((raw,))
                case _:
                    parse_error = "iterate.params() values must be tuples or lists"
                    break

        ids_tuple = tuple(str(i) for i in ids) if ids is not None else None

        definition_error: str | None = None
        modifier: ParamsIterateModifier | None = None
        match (names, values_list, parse_error, ids_tuple):
            case ((), _, _, _):
                definition_error = "iterate.params() requires at least one argument name"
            case (_, _, str() as err, _):
                definition_error = err
            case (_, [], _, _):
                definition_error = "iterate.params() requires at least one value set"
            case (_, _, _, tuple() as it) if len(it) != len(values_list):
                definition_error = "iterate.params() ids must match number of value sets"
            case _:
                parameter_sets: list[ParameterSet] = []
                for i, vals in enumerate(values_list):
                    match ids_tuple:
                        case tuple():
                            suffix = ids_tuple[i]
                        case _:
                            suffix = "{" + ", ".join(f"{n}={repr(v)[:30]}" for n, v in zip(names, vals)) + "}"
                    parameter_sets.append(ParameterSet(values=dict(zip(names, vals)), suffix=suffix))
                modifier = ParamsIterateModifier(
                    parameter_sets=tuple(parameter_sets),
                    min_passes=self._resolve_min_passes("iterate.params()", len(values_list), min_passes),
                )

        def decorator(target: Callable[..., Any]) -> Callable[..., Any]:
            match definition_error:
                case str() as err:
                    target.__rue_definition_error__ = err  # type: ignore[attr-defined]
                    target.__rue_test__ = True  # type: ignore[attr-defined]
                    return target
                case _:
                    return self._attach_modifier(target, modifier)

        return decorator

    def cases(
        self,
        *cases: Case[Any, Any],
        min_passes: int | None = None,
    ) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
        cases_list = list(cases)
        if len(cases_list) == 1 and isinstance(cases_list[0], (list, tuple)):
            cases_list = list(cases_list[0])

        definition_error = (
            None if cases_list else "iterate.cases() requires at least one case"
        )
        modifier = None
        if cases_list:
            actual_min_passes = self._resolve_min_passes(
                "iterate.cases()",
                len(cases_list),
                min_passes,
            )
            modifier = CasesIterateModifier(
                cases=tuple(cases_list),
                min_passes=actual_min_passes,
            )

        def decorator(target: Callable[..., Any]) -> Callable[..., Any]:
            if definition_error:
                target.__rue_definition_error__ = definition_error  # type: ignore[attr-defined]
                target.__rue_test__ = True  # type: ignore[attr-defined]
                return target
            if modifier is None:
                return target
            return self._attach_modifier(target, modifier)

        return decorator

    def groups(
        self,
        *groups: CaseGroup[Any, Any, Any],
        min_passes: int | None = None,
    ) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
        groups_list = list(groups)
        definition_error = (
            None
            if groups_list
            else "iterate.groups() requires at least one case group"
        )
        modifier = None
        if groups_list:
            actual_min_passes = self._resolve_min_passes(
                "iterate.groups()",
                len(groups_list),
                min_passes,
            )
            modifier = GroupsIterateModifier(
                groups=tuple(groups_list),
                min_passes=actual_min_passes,
            )

        def decorator(target: Callable[..., Any]) -> Callable[..., Any]:
            if definition_error:
                target.__rue_definition_error__ = definition_error  # type: ignore[attr-defined]
                target.__rue_test__ = True  # type: ignore[attr-defined]
                return target
            if modifier is None:
                return target
            return self._attach_modifier(target, modifier)

        return decorator


iterate = IterateDecorator()

__all__ = ["IterateDecorator", "iterate"]
