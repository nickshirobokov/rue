"""Subprocess-safe resource sync contract."""

from __future__ import annotations

from abc import ABC, abstractmethod


type SyncState = object


class SyncableResource[SyncStateT: SyncState](ABC):
    """Resource value that can move state across subprocess boundaries."""

    @abstractmethod
    def get_sync_state(self) -> SyncStateT:
        """Return subprocess-safe resource state."""

    @abstractmethod
    def from_sync_state(self, state: SyncStateT) -> None:
        """Hydrate this resource from subprocess-safe state."""

    @abstractmethod
    def merge_sync_states(
        self,
        baseline: SyncStateT,
        update: SyncStateT,
    ) -> None:
        """Merge a subprocess update into this resource."""
