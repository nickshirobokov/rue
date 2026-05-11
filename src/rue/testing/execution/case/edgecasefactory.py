"""AI-backed case factories for adversarial test attempts."""

from __future__ import annotations

import inspect
import json
from typing import Any

from pydantic import BaseModel, ConfigDict
from pydantic_ai import (
    Agent,
    DeferredToolRequests,
    DeferredToolResults,
    ExternalToolset,
    ModelRetry,
    ToolDefinition,
)
from pydantic_ai.messages import ModelMessage, ModelRequest, UserPromptPart
from pydantic_ai.models import KnownModelName
from pydantic_ai.settings import ModelSettings
from pydantic_ai_backends import (
    READONLY_RULESET,
    ConsoleCapability,
    LocalBackend,
)

from rue.testing.execution.case.basefactory import CaseFactory
from rue.testing.execution.case.models import Case
from rue.testing.execution.test.models import ExecutedTest, LoadedTestDef


class CaseReview(BaseModel):
    """Validation result for a proposed edge case."""

    valid: bool
    message: str


class EdgeCaseAgentDeps(BaseModel):
    """Dependencies for the edge-case generation agent."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    backend: LocalBackend


class EdgeCaseFactory[CaseT: Case[Any, Any]](CaseFactory):
    """Generate valid cases that try to break a test's assertions."""

    def __init__(
        self,
        *,
        case_model: type[CaseT],
        max_attempts: int = 3,
        display_name: str = "edge_cases",
        model: KnownModelName | str = "openai:gpt-5.4",
        model_settings: ModelSettings | None = None,
    ) -> None:
        super().__init__(
            max_attempts=max_attempts,
            display_name=display_name,
        )
        self.case_model = case_model

        self._model = model
        self._model_settings = model_settings
        self._main_agent: (
            Agent[EdgeCaseAgentDeps, DeferredToolRequests | str] | None
        ) = None
        self._review_agent: Agent[None, CaseReview] | None = None
        self._main_agent_backend: EdgeCaseAgentDeps | None = None

        self.main_agent_messages: list[ModelMessage] = []
        self.pending_tool_results: DeferredToolResults | None = None
        self.last_tool_call_id: str | None = None
        self.generated_cases_count = 0

    async def next_case(
        self,
        loaded_test: LoadedTestDef,
    ) -> CaseT | None:
        """Return the next edge case generated for ``loaded_test``."""
        if self.generated_cases_count >= self.max_attempts:
            return None

        main_agent = self._main_agent or self._build_main_agent(
            loaded_test
        )
        review_agent = self._review_agent or self._build_review_agent(
            loaded_test
        )
        main_agent_deps = self._main_agent_backend or self._build_backend(
            loaded_test
        )
        self.last_tool_call_id = None

        proposed_case = None
        while proposed_case is None:
            result = await main_agent.run(
                message_history=self.main_agent_messages,
                deferred_tool_results=self.pending_tool_results,
                deps=main_agent_deps,
            )
            self.pending_tool_results = None
            self.main_agent_messages = list(result.all_messages())

            assert isinstance(result.output, DeferredToolRequests)

            for tool_call in result.output.calls:
                if tool_call.tool_name != "provide_case":
                    continue

                review_result = await review_agent.run(
                    user_prompt=(
                        "Proposed Case:"
                        f"{json.dumps(tool_call.args, indent=2, default=str)}"
                    )
                )
                if review_result.output.valid:
                    proposed_case = self.case_model.model_validate(
                        tool_call.args
                    )
                    self.last_tool_call_id = tool_call.tool_call_id
                    self.generated_cases_count += 1
                    break

                self.pending_tool_results = DeferredToolResults()
                self.pending_tool_results.calls[tool_call.tool_call_id] = (
                    ModelRetry(review_result.output.message)
                )
                break

        return proposed_case

    async def observe(
        self,
        case: Case[Any, Any],
        execution: ExecutedTest,
    ) -> None:
        """Append the observed execution outcome to the agent history."""
        _ = case
        if self.last_tool_call_id is None:
            raise ValueError("No tool call ID found.")
        self.pending_tool_results = DeferredToolResults()
        self.pending_tool_results.calls[self.last_tool_call_id] = (
            execution.result
        )

    def _load_test_body(self, loaded_test: LoadedTestDef) -> str:
        try:
            return inspect.getsource(loaded_test.fn)
        except OSError:
            return loaded_test.spec.full_name

    def _build_main_agent(
        self,
        loaded_test: LoadedTestDef,
    ) -> Agent[EdgeCaseAgentDeps, DeferredToolRequests | str]:
        test_body = self._load_test_body(loaded_test)
        case_schema = self.case_model.model_json_schema()
        self.main_agent_messages = [
            ModelRequest(
                parts=[
                    UserPromptPart(
                        content=(
                            "You generate edge cases for Rue tests. Local "
                            "context is read-only. Use ls, read_file, "
                            "glob, and grep if you need local context; "
                            "do not write, edit, execute code, or request "
                            "a dependency graph. Call provide_case with a "
                            "complete Case object when ready.\n"
                            f"Test code body: {test_body}\n"
                            f"Case JSON schema: {case_schema}"
                        )
                    )
                ]
            )
        ]
        provide_case_tool = ToolDefinition(
            name="provide_case",
            description=(
                "Provide final Case values for the next adaptive attempt."
            ),
            parameters_json_schema=self.case_model.model_json_schema(),
        )
        external_toolset = ExternalToolset[EdgeCaseAgentDeps](
            [provide_case_tool]
        )
        main_agent = Agent(
            model=self._model,
            output_type=[DeferredToolRequests, str],
            deps_type=EdgeCaseAgentDeps,
            instructions=(
                "Analyze the test and provide Case values that have the "
                "highest chance of failing assertions in the test body while "
                "still being valid for the described inputs and references. "
                "Local context tools are read-only: use ls, read_file, glob, "
                "and grep when needed. Writing, editing, shell execution, "
                "and dependency graph tools are unavailable."
            ),
            model_settings=self._model_settings,
            toolsets=[external_toolset],
            capabilities=[
                ConsoleCapability(
                    include_execute=False,
                    permissions=READONLY_RULESET,
                )
            ],
            tool_retries=3,
            output_retries=3,
        )
        main_agent.output_validator(
            lambda output: output
            if isinstance(output, DeferredToolRequests)
            else (_ for _ in ()).throw(
                ModelRetry("Agent must use provide_case.")
            )
        )
        self._main_agent = main_agent
        return main_agent

    def _build_review_agent(
        self,
        loaded_test: LoadedTestDef,
    ) -> Agent[None, CaseReview]:
        review_agent = Agent(
            self._model,
            output_type=CaseReview,
            instructions=(
                "Check whether proposed Case values are valid for the test "
                "description and schema. Reject invalid, missing, or "
                "impossible values even if they might fail the test.\n"
                f"Test code body:{self._load_test_body(loaded_test)}\n"
                f"Case JSON schema:{self.case_model.model_json_schema()}"
            ),
            model_settings=self._model_settings,
        )
        self._review_agent = review_agent
        return review_agent

    def _build_backend(
        self,
        loaded_test: LoadedTestDef,
    ) -> EdgeCaseAgentDeps:
        self._main_agent_backend = EdgeCaseAgentDeps(
            backend=LocalBackend(
                root_dir=loaded_test.suite_root,
                enable_execute=False,
                permissions=READONLY_RULESET,
            )
        )
        return self._main_agent_backend
