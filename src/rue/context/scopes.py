"""Runtime scope ownership models."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum, auto
from pathlib import Path
from uuid import UUID


class Scope(StrEnum):
    """Resource lifecycle scope."""

    TEST = auto()  # Fresh instance per test
    MODULE = auto()  # Shared across tests in same file
    RUN = auto()  # Shared across entire test run


@dataclass(frozen=True, slots=True)
class ScopeOwner:
    """Runtime owner for resource and patch lifecycles."""

    scope: Scope
    execution_id: UUID | None = None
    run_id: UUID | None = None
    module_path: Path | None = None

    @classmethod
    def for_resource_scope(
        cls,
        scope: Scope,
        *,
        execution_id: UUID,
        run_id: UUID,
        module_path: Path,
    ) -> ScopeOwner:
        """Build the owner key for a resource scope in this context."""
        match scope:
            case Scope.TEST:
                return cls(
                    scope=scope,
                    execution_id=execution_id,
                    run_id=run_id,
                )
            case Scope.MODULE:
                return cls(
                    scope=scope,
                    run_id=run_id,
                    module_path=module_path,
                )
            case Scope.RUN:
                return cls(scope=scope, run_id=run_id)

    def is_active(
        self,
        *,
        execution_id: UUID | None,
        run_id: UUID | None,
        module_path: Path | None,
    ) -> bool:
        """Return whether this owner applies in the current runtime context."""
        match self.scope:
            case Scope.TEST:
                return (
                    self.execution_id is not None
                    and self.run_id is not None
                    and execution_id == self.execution_id
                    and run_id == self.run_id
                )
            case Scope.MODULE:
                return (
                    self.module_path is not None
                    and self.run_id is not None
                    and module_path == self.module_path
                    and run_id == self.run_id
                )
            case Scope.RUN:
                return self.run_id is not None and run_id == self.run_id
