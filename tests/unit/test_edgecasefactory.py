"""Tests for AI-backed edge case factories."""

from pathlib import Path
from typing import Any

import pytest
from pydantic_ai.exceptions import UnexpectedModelBehavior
from pydantic_ai.models.test import TestModel

from rue.analysis import DependencyEntry
from rue.config import AIModelConfig, CaseFactorySettings, Config
from rue.testing.execution.case import Case, EdgeCaseFactory
from rue.testing.execution.case.edge_case_factory import (
    factory as factory_module,
)
from tests.helpers import make_definition


@pytest.fixture
def edge_case_config(monkeypatch: pytest.MonkeyPatch) -> None:
    original_agent = factory_module.Agent

    def agent(*args: Any, **kwargs: Any) -> Any:
        if args and args[0] == "test":
            args = (TestModel(call_tools=[]), *args[1:])
        if kwargs.get("model") == "test":
            kwargs["model"] = TestModel(call_tools=[])
        return original_agent(*args, **kwargs)

    monkeypatch.setattr(
        factory_module,
        "load_config",
        lambda: Config(
            case_factories=CaseFactorySettings(
                edge_case_factory=AIModelConfig(
                    model="test",
                    temperature=0.2,
                )
            )
        ),
    )
    monkeypatch.setattr(factory_module, "Agent", agent)


@pytest.mark.usefixtures("edge_case_config")
@pytest.mark.asyncio
async def test_edge_case_factory_exposes_read_only_backend_tools(
    tmp_path: Path,
) -> None:
    factory = EdgeCaseFactory(case_model=Case)
    loaded_test = make_definition(
        fn=lambda: None,
        module_path=tmp_path / "test_subject.py",
        suite_root=tmp_path,
    )

    with pytest.raises(UnexpectedModelBehavior):
        await factory.next_case(loaded_test)

    assert factory._main_agent is not None
    assert isinstance(factory._main_agent.model, TestModel)
    request_parameters = factory._main_agent.model.last_model_request_parameters
    assert request_parameters is not None
    tool_names = {tool.name for tool in request_parameters.function_tools}
    assert tool_names == {
        "compact_conversation",
        "glob",
        "grep",
        "ls",
        "provide_case",
        "read_file",
    }
    assert tool_names - {"provide_case"} == {
        "compact_conversation",
        "glob",
        "grep",
        "ls",
        "read_file",
    }


@pytest.mark.usefixtures("edge_case_config")
@pytest.mark.asyncio
async def test_edge_case_factory_backend_is_read_only_and_suite_scoped(
    tmp_path: Path,
) -> None:
    suite_file = tmp_path / "test_subject.py"
    suite_file.write_text("def test_subject():\n    marker = 'needle'\n")
    outside_file = tmp_path.parent / f"{tmp_path.name}_outside.py"
    outside_file.write_text("outside = 'needle'\n")

    factory = EdgeCaseFactory(case_model=Case)
    loaded_test = make_definition(
        fn=lambda: None,
        module_path=suite_file,
        suite_root=tmp_path,
    )

    with pytest.raises(UnexpectedModelBehavior):
        await factory.next_case(loaded_test)
    assert factory._main_agent_backend is not None
    backend = factory._main_agent_backend.backend

    assert backend.execute_enabled is False
    assert [entry["path"] for entry in backend.glob_info("*.py", ".")] == [
        str(suite_file)
    ]

    matches = backend.grep_raw("needle", "test_subject.py")
    assert isinstance(matches, list)
    assert matches[0]["path"] == str(suite_file)
    assert matches[0]["line_number"] == 2

    outside_result = backend.grep_raw("needle", str(outside_file))
    assert isinstance(outside_result, str)
    assert "outside allowed directories" in outside_result


@pytest.mark.usefixtures("edge_case_config")
def test_edge_case_factory_builds_main_agent_from_config_without_history(
    tmp_path: Path,
) -> None:
    factory = EdgeCaseFactory(case_model=Case)
    loaded_test = make_definition(
        fn=lambda: None,
        module_path=tmp_path / "test_subject.py",
        suite_root=tmp_path,
    )

    agent = factory._build_main_agent(loaded_test)

    assert agent.model_settings == {"temperature": 0.2}
    assert factory.main_agent_messages == []


@pytest.mark.usefixtures("edge_case_config")
def test_edge_case_factory_includes_dependency_paths_in_main_agent_prompt(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    suite_root = tmp_path / "suite"
    dependency_entries = [
        DependencyEntry("pkg", suite_root / "pkg" / "__init__.py"),
        DependencyEntry("pkg.subject", suite_root / "pkg" / "subject.py"),
        DependencyEntry(
            "tests.test_subject",
            suite_root / "tests" / "test_subject.py",
        ),
    ]
    monkeypatch.setattr(
        factory_module,
        "collect_dependencies",
        lambda fn: dependency_entries,
    )

    factory = EdgeCaseFactory(case_model=Case)
    loaded_test = make_definition(
        fn=lambda: None,
        module_path=suite_root / "tests" / "test_subject.py",
        suite_root=suite_root,
    )

    agent = factory._build_main_agent(loaded_test)

    assert len(agent._instructions) == 1
    assert (
        "Local dependency file tree:\n"
        "pkg/__init__.py\n"
        "pkg/subject.py\n"
        "tests/test_subject.py\n"
    ) in agent._instructions[0]
