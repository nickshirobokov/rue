"""Test discovery."""

from rue.testing.discovery.collector import StaticTestReference, collect, collect_static
from rue.testing.discovery.loader import RueModuleLoader
from rue.testing.models import TestDefinition, RueTestDefinition


# Backwards compatibility alias
TestItem = TestDefinition

__all__ = [
    "TestDefinition",
    "RueModuleLoader",
    "RueTestDefinition",
    "StaticTestReference",
    "TestItem",
    "collect",
    "collect_static",
]
