# Rue Agent Notes

## What Rue Is

Rue is a testing framework for AI software. It lets developers test AI behavior
with real engineering tools: `@rue.test`, resources, predicates, SUT tracing,
scoped monkeypatching, metrics, CLI runs, and persisted run records.

Rue is not evals. Do not drag this project toward benchmark theater, notebook
rituals, dashboard worship, dataset cargo cults, or anything that smells like
data-science cosplay pretending to be software engineering.

## Current State

Rue is alpha. There is no backward compatibility promise.

If an API is wrong, redesign it. If a model is wrong, change it. If a module is
wrong, move it. Do not preserve trash with compatibility shims, old aliases,
wrapper properties, or "just in case" public surfaces.

## Sources Of Truth

Specs beat docs. Code beats stale docs. Tests prove behavior only when the
behavior deserves to be treated as a contract.

Normative specs live here:

- `src/rue/cli/SPEC.md`
- `src/rue/context/SPEC.md`
- `src/rue/resources/SPEC.md`
- `src/rue/patching/SPEC.md`
- `src/rue/predicates/SPEC.md`

README and old docs may be stale. Treat them as rumors until specs and code
confirm them.

## Architecture Lanes

- Public API: `src/rue/__init__.py`
- CLI entry point: `rue.cli:main`
- CLI orchestration: `src/rue/cli/`
- Terminal UX and Rich view code: `src/rue/cli/rendering/`
- Static collection: `TestSpecCollector`
- Loading/import and AST rewrites: `TestLoader`
- Execution: `Runner`, `RunContext`, `TestContext`
- Resource DI: `ResourceRegistry`, `DependencyResolver`, `ResourceStore`
- Scoped patching: `src/rue/patching/`
- Event side effects: `RunEventsProcessor` implementations

Keep these lanes clean. If CLI code starts building terminal layouts, it is
wrong. If rendering code mutates runner/storage state, it is wrong. If runtime
context ownership leaks into unrelated modules, it is wrong.

Models are core data contracts. Views are optimized shapes for external
consumers like databases, reports, terminals, and other output surfaces. Do not
confuse them.

## Code Standards

Clean code is not optional. Less code is better than more code. Fewer models are
better than more models.

Helper spam is a red flag. Model spam is a red flag. They usually mean the
developer is hiding bad API design behind more names.

Do not add a helper when the inline code is one or two lines, even if it repeats
ten times. DRY is a tool, not a religion.

Do not add convenient wrapper properties. Consumers should request the real
thing directly. Convenience APIs rot into fake contracts.

Naming is architecture. Every module, class, function, field, and enum member
must say exactly what it owns. Vague names are not harmless; they are usually
garbage design trying to look abstract.

Layout is architecture too. Think hard before adding a file or moving code. A
good implementation in the wrong module is still bad work.

Use the codebase's existing domain objects before inventing a new abstraction.
If a nearby model needs one field or method, add it there instead of creating a
new pile of glue.

No defensive `try/except` without explicit approval. Cleanup `try/finally` is
fine when lifecycle ownership requires it.

Imports go at module top. No method-local imports, compatibility shims, ghost
modules, or stale re-exports.

Validated/serializable models use Pydantic. Local settings use
`pydantic_settings`. LLM abstractions should use Pydantic AI when it fits.

Ask before adding `cast` or `type: ignore`.

## Tests

Be careful with tests. Agents treat tests as truth. If you test a hack, future
agents will build a cathedral around that hack.

Do not test Python itself: default factories, constructor plumbing, dataclass or
Pydantic basics, enum access, import existence, or anything mypy/Ruff can catch.

Prefer one meaningful integration test over ten brittle unit tests. Test user
behavior, runtime contracts, and cross-module interactions. Do not test private
implementation trivia just because it was easy.

Test Rue with pytest, not `rue run`.

Useful commands:

- `uv run pytest tests/unit/test_config.py -q`
- `uv run pytest tests/unit/test_config.py::test_load_config_defaults_when_missing -q`
- `uv run --group lint ruff check .`
- `uv run --group lint ruff format .`
- `uv run --group lint mypy src/rue`

Predicate E2E tests need model credentials and are expensive. Do not run them
casually.

## Tooling

Python is `3.12`. Use `uv`, not `pip` and not bare `python`.

Run setup with:

- `uv sync --all-groups`

Ruff uses line length 80, Python 3.12, Google docstrings, and import sorting.
Mypy is strict with the Pydantic plugin.

`rue run` persists to `.rue/rue.turso.db` by default. Use `RUE_DATABASE_PATH`
for throwaway runs.
