"""Tests for reporter instance registration."""

from rue.config import RueConfig
from rue.reports.base import Reporter


class DummyReporter(Reporter):
    """Minimal reporter for testing."""

    def __init__(self, verbosity: int = 0):
        self.verbosity = verbosity

    def configure(self, config: RueConfig) -> None:
        self.verbosity = config.verbosity

    async def on_no_tests_found(self) -> None:
        pass

    async def on_collection_complete(self, items, run) -> None:
        pass

    async def on_test_start(self, item) -> None:
        pass

    async def on_execution_complete(self, execution) -> None:
        pass

    async def on_run_complete(self, test_run) -> None:
        pass

    async def on_run_stopped_early(self, failure_count: int) -> None:
        pass


class TestReporterBase:
    """Tests for base Reporter behavior."""

    def test_instances_register_by_class_name(self):
        class OtherReporter(DummyReporter):
            pass

        first = DummyReporter()
        second = OtherReporter()

        assert Reporter.REGISTRY["DummyReporter"] is first
        assert Reporter.REGISTRY["OtherReporter"] is second

    def test_configure_adjusts_params_from_config(self):
        reporter = DummyReporter()
        config = RueConfig.model_construct(verbosity=3)

        reporter.configure(config)

        assert reporter.verbosity == 3


class TestReporterRegistry:
    """Tests for direct Reporter.REGISTRY access."""

    def test_registry_clear_removes_all_instances(self):
        Reporter.REGISTRY.clear()

        assert Reporter.REGISTRY == {}
