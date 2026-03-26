"""Test discovery."""

from rue.testing.discovery.collector import (
    StaticTestReference,
    collect,
    collect_paths,
    collect_static,
)
from rue.testing.discovery.loader import RueImportSession, RueModuleLoader
from rue.testing.models import RueTestDefinition, TestDefinition


# Backwards compatibility alias
TestItem = TestDefinition

__all__ = [
    "RueImportSession",
    "RueModuleLoader",
    "RueTestDefinition",
    "StaticTestReference",
    "TestDefinition",
    "TestItem",
    "collect",
    "collect_paths",
    "collect_static",
]
