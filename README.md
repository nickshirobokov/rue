# Rue

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](https://opensource.org/licenses/MIT)
[![Python 3.12+](https://img.shields.io/badge/python-3.12+-blue.svg)](https://www.python.org/downloads/)

Rue is a Python testing framework for AI projects. It follows pytest syntax and culture while introducing components essential for testing AI software: metrics, typed datasets, semantic predicates (LLM-as-a-Judge), and OTEL traces.

---

## Installation

```bash
uv add rue
```

---

# Rue 101

Follow pytest habits...

- Create `test_*.py` files
- Mark plain Rue tests with `@rue.test`
- Use 'rue.resource' instead of 'pytest.fixture'
- Put shared suite setup, shared resources, and directory-specific overrides in `conftest.py` or `confrue_*.py` files. Rue loads `conftest.py` first in each directory. See [confrue files](docs/concepts/confrue-files.mdx)
- Add 'assert' expressions within the functions
- Run 'uv run rue tests run'

Rue only collects tests marked through Rue decorators, so pytest and Rue tests can live side by side in the same `test_*.py` module.

...while leveraging Rue APIs.
- Use 'with metrics()' context to turn failed assertions into quality metrics
- Use 'has_facts()' and other semantic predicates for asserting natural language
- Access OTEL span data and assert it with 'follows_policy()' predicate
- Parse datasets into clearly typed and validated data objects

---


## Example

```python
import rue
from rue import Case, Metric, metrics
from rue.predicates import has_unsupported_facts, follows_policy

from pydantic import BaseModel

@rue.resource.sut
def store_chatbot():
    return rue.SUT(call_llm)

@rue.resource.metric
def accuracy():
    metric = Metric()
    yield metric

    assert metric.mean > 0.8
    yield metric.mean

class Refs(BaseModel):
    kb: str
    expected_tool: str | None = None

cases = [
    Case(inputs={"prompt": "When are you open?"}, references=Refs(kb="Store hours: 9 AM - 6 PM, Monday-Saturday. Closed Sundays.")),
    Case(inputs={"prompt": "Return policy?"}, references=Refs(kb="30-day returns with receipt.")),
    Case(inputs={"prompt": "How much for the Nike Air Max?"}, references=Refs(kb="Nike Air Max: $129.99", expected_tool="offer_product")),
]

@rue.test.iterate.cases(*cases)
@rue.test.iterate(3)
async def test_chatbot_no_hallucinations(
    case: Case[dict[str, str], Refs],
    store_chatbot,
    accuracy: Metric,
):
    """AI agent relies on knowledge base and tool calls for transactional questions"""
    response = store_chatbot.instance(**case.inputs)

    # Verify the answer don't have any unsupported facts
    with metrics(accuracy):
        assert not await has_unsupported_facts(response, case.references.kb)

    # Verify tool was called when expected
    if expected_tool := case.references.expected_tool:
        root_spans = store_chatbot.root_spans
        tool_names = [
            s.attributes.get("llm.request.functions.0.name")
            for s in store_chatbot.llm_spans
            if s.attributes
        ]
        assert root_spans
        assert expected_tool in tool_names
```

Run it:

```bash
uv run rue tests run
```

Use a custom run UUID when you need stable correlation IDs:

```bash
uv run rue tests run --run-id 3f5f5e9a-1c2d-4b5f-9c2b-7f6d8a9b0c1d
```

Output:

```
Rue Test Runner
=================

Collected 1 test

test_example.py::test_chatbot_responds ✓

==================== 1 passed in 0.08s ====================
```

---

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

---
