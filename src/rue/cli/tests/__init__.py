"""Test CLI package."""

from importlib import import_module

from rue.testing.discovery import TestSpecCollector


status = import_module("rue.cli.tests.status")

__all__ = ["TestSpecCollector", "status"]
