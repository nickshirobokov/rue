"""Test discovery."""

from rue.testing.discovery.collector import (
    Filterable,
    KeywordMatcher,
    StaticTestReference,
    TestCollector,
    collect,
    collect_paths,
    collect_static,
)
from rue.testing.discovery.loader import RueImportSession, RueModuleLoader
from rue.testing.models import TestDefinition


# Backwards compatibility alias
TestItem = TestDefinition

__all__ = [
    "Filterable",
    "KeywordMatcher",
    "RueImportSession",
    "RueModuleLoader",
    "StaticTestReference",
    "TestCollector",
    "TestDefinition",
    "TestItem",
    "collect",
    "collect_paths",
    "collect_static",
]
