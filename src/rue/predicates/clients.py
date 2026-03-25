"""LLM-backed predicate client."""

from dotenv import load_dotenv
from pydantic import BaseModel
from pydantic_ai import RunContext
from pydantic_ai._output import OutputSchema
from pydantic_ai.direct import model_request
from pydantic_ai.messages import ModelRequest, SystemPromptPart, UserPromptPart
from pydantic_ai.models import (
    KnownModelName,
    ModelRequestParameters,
    infer_model,
)
from pydantic_ai.settings import ModelSettings
from pydantic_ai.usage import RunUsage

from rue.config import PredicateConfig, load_config
from rue.predicates.models import PredicateResult
from rue.predicates.decorator import predicate


load_dotenv()


class WithExplanationOutput(BaseModel):
    """Structured output with a verdict and explanation."""

    explanation: str
    verdict: bool


class LLMPredicate:
    """An engine to call an LLM as a predicate."""

    bool_output_schema = OutputSchema[bool].build(output_spec=bool)
    bool_with_explanation_output_schema = OutputSchema[
        WithExplanationOutput
    ].build(output_spec=WithExplanationOutput)

    bool_request_parameters = ModelRequestParameters(
        allow_text_output=False,
        output_object=bool_output_schema.object_def,
        output_mode="native",
    )
    bool_with_explanation_request_parameters = ModelRequestParameters(
        allow_text_output=False,
        output_object=bool_with_explanation_output_schema.object_def,
        output_mode="native",
    )

    def __init__(
        self,
        predicate_name: str,
        normal_prompt: str,
        strict_prompt: str,
        task_template: str,
        predicate_config: PredicateConfig | None = None,
    ) -> None:
        self.predicate_name = predicate_name
        self.normal_prompt = normal_prompt
        self.strict_prompt = strict_prompt
        self.task_template = task_template
        self.predicate_config = predicate_config

    async def generate_predicate_result(
        self,
        actual: str,
        reference: str,
        strict: bool = False,  # noqa: FBT001, FBT002
        with_explanation: bool = False,  # noqa: FBT001, FBT002
    ) -> PredicateResult:
        """Get the bool value of the predicate from the LLM."""
        model, model_settings = self.get_model_config()

        if with_explanation:
            output_processor = (
                self.bool_with_explanation_output_schema.text_processor
            )
            request_parameters = self.bool_with_explanation_request_parameters
        else:
            output_processor = self.bool_output_schema.text_processor
            request_parameters = self.bool_request_parameters

        task_prompt = self.task_template.format(
            actual=actual, reference=reference
        )
        system_prompt = self.strict_prompt if strict else self.normal_prompt
        messages = ModelRequest(
            parts=[
                SystemPromptPart(content=system_prompt),
                UserPromptPart(content=task_prompt),
            ],
        )

        model_response = await model_request(
            model=model,
            messages=[messages],
            model_request_parameters=request_parameters,
            model_settings=model_settings,
        )
        assert output_processor is not None
        parsed_output = await output_processor.process(
            model_response.parts[-1].content,  # type: ignore[arg-type]
            run_context=RunContext(
                deps=None,
                model=infer_model(model),
                usage=RunUsage(),
            ),
        )
        result = PredicateResult(
            actual=actual,
            reference=reference,
            name=self.predicate_name,
            strict=strict,
            value=parsed_output
            if isinstance(parsed_output, bool)
            else parsed_output.verdict,
            confidence=1.0,
            message=None
            if isinstance(parsed_output, bool)
            else parsed_output.explanation,
        )
        return result

    def get_model_config(self) -> tuple[KnownModelName, ModelSettings]:
        """Resolve the configured model and settings for a built-in predicate."""
        if self.predicate_config:
            return (
                self.predicate_config.model,
                self.predicate_config.model_settings,
            )

        global_config = load_config()
        cfg = (
            getattr(global_config.predicates, self.predicate_name, None)
            or global_config.predicates.all_predicates
        )

        if not cfg:
            raise RuntimeError(
                f"Missing predicate config for '{self.predicate_name}'"
            )

        self.predicate_config = cfg
        return cfg.model, cfg.model_settings

    def build_predicate(self):
        return predicate(
            self.generate_predicate_result, name=self.predicate_name
        )
