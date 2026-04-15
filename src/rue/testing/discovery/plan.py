"""Serializable collection plan — the handoff artifact between discovery and execution.

A :class:`CollectionPlan` is produced by :func:`plan_collection` in the
parent process and can be pickled / sent to a worker process.  The worker
passes it to :class:`~rue.testing.discovery.loader.TestLoader` to reconstruct
live :class:`~rue.testing.models.definition.TestDefinition` objects locally.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from rue.testing.models.spec import TestSpec


@dataclass(frozen=True)
class SetupFileRef:
    """Reference to one conftest or confrue setup file.

    Fully serializable.  Workers use these paths to import setup files in the
    correct order so their local registries mirror the parent's state.
    """

    path: Path
    kind: Literal["conftest", "confrue"]


@dataclass(frozen=True)
class CollectionPlan:
    """Serializable description of a planned test run.

    Contains everything a worker needs to reconstruct the test environment
    from scratch:

    * ``suite_root`` — used to create a :class:`RueImportSession` with the
      same deterministic synthetic package names as the parent.
    * ``setup_chains`` — maps each test file's absolute path to the ordered
      list of setup files that must be imported before that test's module
      (conftest / confrue chain from suite root down to the file's directory).
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
