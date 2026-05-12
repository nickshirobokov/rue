"""AI-backed case factories for adversarial test attempts."""

from __future__ import annotations

import json
from typing import Any

from genai_prices import Usage, calc_price
from pydantic import BaseModel, ConfigDict
from pydantic_ai import (
    Agent,
    DeferredToolRequests,
    DeferredToolResults,
    ExternalToolset,
    ModelRetry,
    ToolDefinition,
)
from pydantic_ai.exceptions import UnexpectedModelBehavior
from pydantic_ai.messages import ModelMessage, ModelRequest
from pydantic_ai.models import KnownModelName, Model, infer_model
from pydantic_ai.settings import ModelSettings, merge_model_settings
from pydantic_ai_backends import (
    READONLY_RULESET,
    ConsoleCapability,
    LocalBackend,
)
from pydantic_ai_summarization import (
    ContextManagerCapability,
    LimitWarnerCapability,
)

from rue.testing.execution.case.basefactory import CaseFactory
from rue.testing.execution.case.edge_case_factory.prompts import (
    EDGE_CASE_AGENT_INSTRUCTIONS,
    EDGE_CASE_REVIEW_INSTRUCTIONS,
    EDGE_CASE_SUMMARY_PROMPT,
    FIRST_EDGE_CASE_PROMPT,
)
from rue.testing.execution.case.models import Case
from rue.testing.execution.test.models import ExecutedTest, LoadedTestDef


class _InstructionPreservingLimitWarnerCapability(LimitWarnerCapability):
    """Limit warning that preserves output validator retry instructions.

    Pydantic AI represents output validator retries as an empty ModelRequest
    with instructions. LimitWarnerCapability can drop that request because it
    has no parts, which loses the validator's "Agent must use provide_case."
    retry instruction and lets the next model request drift away from the
    required tool call.
    """

    async def before_model_request(
        self,
        ctx: Any,
        request_context: Any,
    ) -> Any:
        current_request = (
            request_context.messages[-1] if request_context.messages else None
        )
        request_context = await super().before_model_request(
            ctx,
            request_context,
        )

        if (
            isinstance(current_request, ModelRequest)
            and current_request.instructions is not None
            and not current_request.parts
            and not any(
                message is current_request
                for message in request_context.messages
            )
        ):
            request_context.messages.append(current_request)

        return request_context


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
        model: Model | KnownModelName,
        max_attempts: int = 3,
        display_name: str = "edge_cases",
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

        main_agent = self._main_agent or self._build_main_agent(loaded_test)
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
                user_prompt=(
                    FIRST_EDGE_CASE_PROMPT
                    if not self.main_agent_messages
                    else None
                ),
                message_history=self.main_agent_messages,
                deferred_tool_results=self.pending_tool_results,
                deps=main_agent_deps,
            )
            self.pending_tool_results = None
            self.main_agent_messages = list(result.all_messages())

            if isinstance(result.output, str):
                raise UnexpectedModelBehavior(
                    "Edge case agent returned text instead of a tool call."
                )

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

    def _build_main_agent(
        self,
        loaded_test: LoadedTestDef,
    ) -> Agent[EdgeCaseAgentDeps, DeferredToolRequests | str]:
        case_schema = self.case_model.model_json_schema()
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
        self._main_agent = Agent(
            model=self._model,
            output_type=[DeferredToolRequests, str],
            deps_type=EdgeCaseAgentDeps,
            instructions=EDGE_CASE_AGENT_INSTRUCTIONS.format(
                test_code_body=loaded_test.test_code_body,
                case_schema=case_schema,
            ),
            model_settings=self._model_settings,
            toolsets=[external_toolset],
            capabilities=[
                ConsoleCapability(
                    include_execute=False,
                    permissions=READONLY_RULESET,
                ),
                ContextManagerCapability(
                    max_tokens=100_000,
                    keep=("messages", 20),
                    summarization_model=self._model,
                    summary_prompt=EDGE_CASE_SUMMARY_PROMPT,
                    include_compact_tool=True,
                ),
                _InstructionPreservingLimitWarnerCapability(
                    max_context_tokens=100_000,
                    warn_on=["context_window"],
                ),
            ],
            tool_retries=3,
            output_retries=3,
        )
        self._main_agent.output_validator(
            lambda output: output
            if isinstance(output, DeferredToolRequests)
            else (_ for _ in ()).throw(
                ModelRetry("Agent must use provide_case.")
            )
        )
        return self._main_agent

    def _build_review_agent(
        self,
        loaded_test: LoadedTestDef,
    ) -> Agent[None, CaseReview]:
        self._review_agent = Agent(
            self._model,
            output_type=CaseReview,
            instructions=EDGE_CASE_REVIEW_INSTRUCTIONS.format(
                test_code_body=loaded_test.test_code_body,
                case_schema=self.case_model.model_json_schema(),
            ),
            model_settings=self._model_settings,
        )

        return self._review_agent

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
