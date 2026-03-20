from pydantic_ai.messages import ModelRequest, SystemPromptPart, UserPromptPart
from pydantic_ai.models import (
    KnownModelName,
    ModelRequestParameters,
    infer_model,
)
from pydantic_ai.direct import model_request
from pydantic_ai import RunContext
from pydantic_ai.usage import RunUsage
from pydantic_ai._output import OutputSchema, OutputSchemaWithoutMode
from dotenv import load_dotenv
from typing import cast

load_dotenv()


class LLMPredicate:
    _MODELS: dict[str, KnownModelName] = {}

    def __init__(
        self,
        predicate_name: str,
        model: KnownModelName,
        system_prompt: str,
        execution_prompt_template: str,
    ):
        self.predicate_name = predicate_name
        self.system_prompt = system_prompt
        self.task_template = execution_prompt_template
        self.model = model

        # Pydantic output processor
        self._output_schema = cast(
            OutputSchemaWithoutMode[bool], OutputSchema[bool].build(output_spec=bool)
        )

        # Pydantic AI run context
        self._ctx = RunContext(
            deps=None,
            model=infer_model(self.model),
            usage=RunUsage(),
        )

        # Pydantic AI model request parameters
        self._request_parameters = ModelRequestParameters(
            allow_text_output=False,
            output_object=self._output_schema.processor.object_def,
            output_mode="native",
        )

    async def __call__(self, actual: str, reference: str) -> bool:
        """Get the bool value of the predicate from the LLM."""

        task_prompt = self.task_template.format(
            actual=actual, 
            reference=reference
        )
        messages = ModelRequest(
            parts=[
                SystemPromptPart(content=self.system_prompt),
                UserPromptPart(content=task_prompt),
            ],
        )
        model_response = await model_request(
            model=self.model,
            messages=[messages],
            model_request_parameters=self._request_parameters,
        )
        unparsed_output = model_response.parts[-1].content  # type: ignore
        parsed = await self._output_schema.processor.process(
            unparsed_output, 
            run_context=self._ctx
        )
        return parsed