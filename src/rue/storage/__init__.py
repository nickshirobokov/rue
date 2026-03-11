"""Storage module for persisting Rue test runs."""

from rue.storage.base import Store
from rue.storage.sqlite import SQLiteStore


__all__ = ["SQLiteStore", "Store"]
