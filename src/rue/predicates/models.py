"""Base predicate classes and result types."""

from typing import ParamSpec

from pydantic import BaseModel, Field

P = ParamSpec("P")


# Data model for predicate results


class PredicateResult(BaseModel):
    """Result of a single predicate evaluation.

    The result carries a boolean outcome (`value`), optional human-readable
    details (`message`), and structured metadata about the predicate execution.

    Attributes:
    ----------
    actual
        Observed value produced by the system under test.
    reference
        Predefined value to compare against.
    name
        Name of the predicate function.
    strict
        Whether to enforce strict comparison semantics (predicate-specific).
    confidence
        Confidence score in ``[0, 1]`` (predicate-specific semantics).
    value
        Boolean outcome of the check.
    message
        Optional details about the outcome (e.g. mismatch explanation).

    Notes:
    -----
    - ``bool(result)`` is equivalent to ``result.value``.
    - ``repr(result)`` returns JSON.
    """

    # Metadata
    actual: str
    reference: str
    name: str
    strict: bool = True
    confidence: float = Field(ge=0.0, le=1.0, default=1.0)

    # Result
    value: bool
    message: str | None = None

    def __repr__(self) -> str:
        return self.model_dump_json(indent=2)
