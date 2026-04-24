"""Serializable test specification — process-boundary-safe models.

These models carry all test metadata that can cross a process boundary
(no live callables). They are the wire format between the parent discovery
process and any worker that materializes and executes tests.

:class:`TestSpecCollection` bundles suite layout, setup file chains, and the
ordered list of :class:`TestSpec` objects produced during discovery.
"""

from __future__ import annotations

import inspect
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal
from uuid import UUID


if TYPE_CHECKING:
    from rue.testing.decorators.tag import TagData
    from rue.testing.models.modifiers import Modifier


@dataclass(frozen=True)
class TestLocator:
    """Uniquely identifies a test function. Fully serializable.

    Sufficient to find the function in any process that has access to the
    filesystem and can import the module via a TestLoader.
    """

    module_path: Path
    function_name: str
    class_name: str | None = None

    def __str__(self) -> str:
        if self.class_name:
            return (
                f"{self.module_path.stem}::"
                f"{self.class_name}::{self.function_name}"
            )
        return f"{self.module_path.stem}::{self.function_name}"


@dataclass
class TestSpec:
    """Fully serializable test specification produced during discovery.

    Contains every piece of metadata needed to understand and schedule a
    test, but holds no live Python objects (no callables, no module
    references). A worker process deserializes this and passes it to
    ``TestLoader.load_definition()`` to obtain a runnable ``LoadedTestDef``.
    """

    locator: TestLocator
    is_async: bool
    params: tuple[str, ...]
    modifiers: tuple[Modifier, ...]
    tags: frozenset[str]
    skip_reason: str | None = None
    xfail_reason: str | None = None
    xfail_strict: bool = False
    definition_error: str | None = None
    suffix: str | None = None
    case_id: UUID | None = None
    collection_index: int = -1

    # --- Convenience accessors derived from locator / case fields ---

    @property
    def name(self) -> str:
        return self.locator.function_name

    @property
    def module_path(self) -> Path:
        return self.locator.module_path

    @property
    def class_name(self) -> str | None:
        return self.locator.class_name

    @property
    def full_name(self) -> str:
        return str(self.locator)

    @property
    def local_name(self) -> str:
        if self.class_name:
            return f"{self.class_name}::{self.name}"
        return self.name

    def get_label(
        self,
        *,
        full: bool = False,
        length: int = 50,
        separator: str = " | ",
    ) -> str | None:
        if self.suffix and self.case_id and full:
            case_id = str(self.case_id)
            suffix_length = length - len(case_id) - len(separator)
            if suffix_length <= 0:
                return case_id
            suffix = self.suffix
            if len(suffix) > suffix_length:
                suffix = f"{suffix[: suffix_length - 1]}…"
            return f"{suffix}{separator}{case_id}"
        if self.suffix:
            if len(self.suffix) <= length:
                return self.suffix
            return f"{self.suffix[: length - 1]}…"
        if self.case_id:
            return str(self.case_id)
        return None

    def update_tags(self, data: TagData) -> None:
        self.tags = frozenset(data.tags)
        self.skip_reason = data.skip_reason
        self.xfail_reason = data.xfail_reason
        self.xfail_strict = data.xfail_strict

    def get_execution_from_fn(self, fn: Callable[..., Any]) -> None:
        self.is_async = inspect.iscoroutinefunction(fn)
        self.params = tuple(
            name for name in inspect.signature(fn).parameters if name != "self"
        )
        self.modifiers = tuple(reversed(getattr(fn, "__rue_modifiers__", ())))
        self.definition_error = getattr(fn, "__rue_definition_error__", None)


@dataclass(frozen=True)
class SetupFileRef:
    """Reference to one conftest or confrue setup file.

    Fully serializable.  Workers use these paths to import setup files in the
    correct order so their local registries mirror the parent's state.
    """

    path: Path
    kind: Literal["conftest", "confrue"]


@dataclass(frozen=True)
class TestSpecCollection:
    """Serializable description of collected test specs for a run.

    Handoff artifact between discovery and execution: produced by
    :meth:`~rue.testing.discovery.collector.TestSpecCollector.build_spec_collection`
    in the parent process and passed to
    :class:`~rue.testing.discovery.loader.TestLoader` to reconstruct live
    :class:`~rue.testing.models.loaded.LoadedTestDef` objects locally.

    * ``suite_root`` — used to create a :class:`RueImportSession` with the
      same deterministic synthetic package names as the parent.
    * ``setup_chains`` — maps each test file's absolute path to the ordered
      list of setup files that must be imported before that test's module.
    * ``specs`` — the ordered list of serializable test specifications.
    """

    suite_root: Path
    setup_chains: dict[Path, tuple[SetupFileRef, ...]] = field(
        default_factory=dict
    )
    specs: tuple[TestSpec, ...] = field(default_factory=tuple)

    @property
    def all_setup_files(self) -> tuple[SetupFileRef, ...]:
        """Deduplicated, ordered set of all setup files across all chains."""
        seen: set[Path] = set()
        result: list[SetupFileRef] = []
        for chain in self.setup_chains.values():
            for ref in chain:
                if ref.path not in seen:
                    seen.add(ref.path)
                    result.append(ref)
        return tuple(result)

    def setup_chain_for(self, module_path: Path) -> tuple[SetupFileRef, ...]:
        """Return the setup chain for a specific test module path."""
        return self.setup_chains.get(module_path, ())
