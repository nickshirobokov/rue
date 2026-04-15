"""Test plan selection and filtering."""

from __future__ import annotations

from collections.abc import Iterator, Mapping, Sequence
from dataclasses import replace
from typing import Protocol, TypeVar

from rue.testing.discovery.plan import CollectionPlan
from rue.testing.discovery.planner import plan_collection


class Filterable(Protocol):
    @property
    def tags(self) -> set[str] | frozenset[str]: ...

    @property
    def full_name(self) -> str: ...


FilterableT = TypeVar("FilterableT", bound=Filterable)


class _KeywordNames(Mapping[str, bool]):
    __slots__ = ("_text",)

    def __init__(self, text: str) -> None:
        self._text = text

    def __getitem__(self, key: str) -> bool:
        return key in self._text

    def __iter__(self) -> Iterator[str]:
        return iter(())

    def __len__(self) -> int:
        return 0


class KeywordMatcher:
    """Evaluate pytest-style -k expressions."""

    __slots__ = ("_code",)

    def __init__(self, expression: str) -> None:
        self._code = compile(expression, "<keyword>", "eval")

    def match(self, text: str) -> bool:
        return bool(
            eval(self._code, {"__builtins__": {}}, _KeywordNames(text))
        )


class TestSelector:
    """Builds filtered collection plans for a given set of selection criteria."""

    def __init__(
        self,
        include_tags: Sequence[str],
        exclude_tags: Sequence[str],
        keyword: str | None,
    ) -> None:
        self.include_tags = include_tags
        self.exclude_tags = exclude_tags
        self.keyword = keyword

    def plan(
        self,
        paths,
    ) -> CollectionPlan:
        plan = plan_collection(paths)
        selected_specs = tuple(self.filter(plan.specs))
        selected_paths = {spec.module_path for spec in selected_specs}
        setup_chains = {
            module_path: chain
            for module_path, chain in plan.setup_chains.items()
            if module_path in selected_paths
        }
        return replace(
            plan,
            setup_chains=setup_chains,
            specs=selected_specs,
        )

    def filter(self, items: Sequence[FilterableT]) -> list[FilterableT]:
        filtered = list(items)

        if self.include_tags:
            include = set(self.include_tags)
            filtered = [item for item in filtered if item.tags & include]

        if self.exclude_tags:
            exclude = set(self.exclude_tags)
            filtered = [item for item in filtered if not (item.tags & exclude)]

        if self.keyword:
            matcher = KeywordMatcher(self.keyword)
            filtered = [
                item for item in filtered if matcher.match(item.full_name)
            ]

        return filtered
