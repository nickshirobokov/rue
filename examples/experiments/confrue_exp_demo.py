"""Experiment dimensions for the chatbot example."""

import rue
from rue import MonkeyPatch

from . import conftest


@rue.experiment(
    [conftest.AnswerProfile.fast(), conftest.AnswerProfile.grounded()],
    ids=["fast", "grounded"],
)
def answer_profile(
    value: conftest.AnswerProfile,
    monkeypatch: MonkeyPatch,
) -> None:
    """Patch the module-level answer profile for one experiment run."""
    monkeypatch.setattr(conftest, "ANSWER_PROFILE", value)


@rue.experiment(
    [conftest.SafetyPolicy.standard(), conftest.SafetyPolicy.locked_down()],
    ids=["standard", "locked-down"],
)
def safety_policy(
    value: conftest.SafetyPolicy,
    monkeypatch: MonkeyPatch,
) -> None:
    """Patch the chatbot class safety policy for one experiment run."""
    monkeypatch.setattr(conftest.Chatbot, "safety_policy", value)
