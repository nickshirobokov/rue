from pathlib import Path

import pytest

from rue.config import load_config, reset_load_config_cache


@pytest.fixture(autouse=True)
def _reset_load_config_cache() -> None:
    reset_load_config_cache()
    yield
    reset_load_config_cache()


def test_load_config_prefers_rue_toml(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.chdir(tmp_path)
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text(
        """
[tool.rue]
test-paths = ["tests"]
include-tags = ["slow"]
maxfail = 1
verbosity = 1
addopts = ["-q"]
""".strip()
    )
    test_file = tmp_path / "rue.toml"
    test_file.write_text(
        """
test-paths = ["examples"]
include-tags = ["smoke"]
exclude-tags = ["slow"]
keyword = "chatbot"
fail-fast = true
otel = false
processors = ["ConsoleReporter", "OtelReporter"]
db-path = ".rue/custom.db"
""".strip()
    )

    config = load_config()

    assert config.test_paths == ["examples"]
    assert config.include_tags == ["smoke"]
    assert config.exclude_tags == ["slow"]
    assert config.keyword == "chatbot"
    assert config.maxfail == 1
    assert config.fail_fast is True
    assert config.verbosity == 1
    assert config.addopts == ["-q"]
    assert config.otel is False
    assert not hasattr(config, "otel_content")
    assert config.processors == ["ConsoleReporter", "OtelReporter"]
    assert config.db_path == Path(".rue/custom.db")


def test_load_config_defaults_when_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.chdir(tmp_path)
    config = load_config()
    assert config.test_paths == ["."]
    assert config.include_tags == []
    assert config.exclude_tags == []
    assert config.keyword is None
    assert config.maxfail is None
    assert config.fail_fast is False
    assert config.verbosity == 0
    assert config.addopts == []
    assert config.otel is True
    assert not hasattr(config, "otel_content")
    assert config.db_path == Path(".rue/rue.db")


def test_config_db_path_override_is_parsed_to_path() -> None:
    config = load_config().with_overrides(db_path=".rue/override.db")

    assert config.db_path == Path(".rue/override.db")


def test_config_db_path_env_override_is_parsed_to_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("RUE_DB_PATH", ".rue/env.db")

    config = load_config()

    assert config.db_path == Path(".rue/env.db")
