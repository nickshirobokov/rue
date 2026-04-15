"""Test definition model — process-bound pair of spec + live callable."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from uuid import UUID

from rue.testing.models.modifiers import Modifier
from rue.testing.models.spec import TestLocator, TestSpec


@dataclass
class TestDefinition:
    """A discovered test function ready for execution in the current process.

    Pairs a serializable :class:`TestSpec` with the live callable resolved
    by the loader.  The ``spec`` is the cross-process-safe record; ``fn`` is
    the process-local binding.

    ``fail_fast`` is the one runtime-mutable field: it is not part of the
    spec because it is set by the :class:`Runner` after collection, not by
    user decorators.
    """

    __test__ = False  # Prevent pytest from collecting this as a test class

    spec: TestSpec
    fn: Callable[..., Any]
    fail_fast: bool = field(default=False)

    # ------------------------------------------------------------------
    # Delegating properties — forward reads to spec so existing call
    # sites (runner, single, factory, reports …) work unchanged.
    # ------------------------------------------------------------------

    @property
    def name(self) -> str:
        return self.spec.name

    @property
    def module_path(self) -> Path:
        return self.spec.module_path

    @property
    def class_name(self) -> str | None:
        return self.spec.class_name

    @property
    def is_async(self) -> bool:
        return self.spec.is_async

    @property
    def params(self) -> tuple[str, ...]:
        return self.spec.params

    @property
    def modifiers(self) -> tuple[Modifier, ...]:
        return self.spec.modifiers

    @property
    def tags(self) -> frozenset[str]:
        return self.spec.tags

    @property
    def skip_reason(self) -> str | None:
        return self.spec.skip_reason

    @property
    def xfail_reason(self) -> str | None:
        return self.spec.xfail_reason

    @property
    def xfail_strict(self) -> bool:
        return self.spec.xfail_strict

    @property
    def definition_error(self) -> str | None:
        return self.spec.definition_error

    @property
    def inline(self) -> bool:
        return self.spec.inline

    @property
    def suffix(self) -> str | None:
        return self.spec.suffix

    @property
    def case_id(self) -> UUID | None:
        return self.spec.case_id

    @property
    def full_name(self) -> str:
        return self.spec.full_name

    @property
    def label(self) -> str | None:
        return self.spec.label

    @property
    def locator(self) -> TestLocator:
        return self.spec.locator

    def with_spec(self, **kwargs) -> TestDefinition:
        """Return a new TestDefinition with selected spec fields replaced."""
        return TestDefinition(
            spec=self.spec.with_changes(**kwargs),
            fn=self.fn,
            fail_fast=self.fail_fast,
        )
