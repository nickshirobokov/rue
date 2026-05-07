# Rue Agent Notes

## Sources Of Truth
- Treat `src/rue/**/SPEC.md` as the design contract. README, docs, and tests can lag; when they conflict with SPEC or executable code, trust SPEC/code.
- Update the nearest SPEC when changing runtime, CLI, resource, patching, or predicate contracts.
- Existing extra guidance lives in `.cursor/CLAUDE.md`; preserve only rules that still match code and SPEC.

## Tooling
- Python is `3.12` (`.python-version`). Use `uv`, not `pip` or direct `python`.
- Install/sync all local groups with `uv sync --all-groups`.
- Lint/format/typecheck commands: `uv run --group lint ruff check .`, `uv run --group lint ruff format .`, `uv run --group lint mypy src/rue`.
- Ruff is configured for line length 80, Python 3.12, Google docstrings, and import sorting; mypy is strict with the Pydantic plugin.

## Testing
- Test Rue itself with pytest, not `rue run`: `uv run pytest tests/unit/test_config.py -q`.
- Run one pytest test with node ids, e.g. `uv run pytest tests/unit/test_config.py::test_load_config_defaults_when_missing -q`.
- Pytest test files live under `tests/unit/`, `tests/integrations/`, and `tests/e2e/` using `test_*.py` names.
- Pytest config sets `asyncio_mode = "auto"`, `pythonpath = ["."]`, and ignores `pytest.PytestCollectionWarning`.
- Predicate E2E tests need configured model credentials and are expensive/flaky compared with unit tests.

## Architecture
- Public package code is under `src/rue`; `rue.cli:main` is the CLI entry point and `src/rue/__init__.py` is the public API surface.
- CLI commands are explicit: `rue run`, `rue status`, `rue db`, `rue init`. Do not add hidden aliases like old `tests` or `experiments` commands.
- `rue status` is preflight only: same selection path as `rue run`, resource graph checks, no test bodies.
- `rue run -exp` fans out experiment child runs; `--run-id` and `--maxfail` are intentionally rejected there.
- `rue run` persists to `.rue/rue.turso.db` by default; set `RUE_DATABASE_PATH` for throwaway runs.
- `src/rue/cli/run.py` orchestrates config, collection, contexts, processors, storage, and runner calls. Rich layouts and terminal UX belong in `src/rue/cli/rendering/`.
- Config loads from init args, `RUE_*`, `rue.toml`, then `[tool.rue]` in `pyproject.toml`; `rue.toml` overrides pyproject. Default DB is `.rue/rue.turso.db`.
- Collection is static AST discovery in `TestSpecCollector`; loading/import and AST rewrites happen in `TestLoader`; execution happens in `Runner` under `RunContext`/`TestContext`.
- Rue only collects top-level functions decorated with `@rue.test`, plus `test_` methods inside classes decorated with `@rue.test`. Setup imports are `conftest.py` first, then sorted `confrue_*.py` files.
- Resource DI is graph-compiled before execution. Provider selection is by requested name, allowed scope, and nearest provider directory to the consumer module.
- Run event processors own side effects such as terminal rendering, Turso persistence, and OTEL. Custom processors outside `rue.*` auto-register by class name and are selected with `--processor` or `config.processors`.

## SPEC Contracts
- `cli/SPEC.md`: command modules do orchestration only; rendering modules own Rich view models/live state; prefer boring, stable terminal output.
- `context/SPEC.md`: `RunContext` must exist before runner APIs; `TestContext` must exist before test bodies and test/module resource ownership; missing required contexts should fail.
- `resources/SPEC.md`: resources are named providers cached by `ScopeOwner`; wider scopes cannot depend on narrower scopes; `PatchStore` is bound during resolve/teardown.
- `patching/SPEC.md`: monkeypatch visibility is context-routed through dispatchers, not globally replaced per test; Rue teardown undoes patches by scope; built-in `monkeypatch` is `sync=False`.
- `predicates/SPEC.md`: keep facts, style, layout, topic, and policy as separate dimensions. Factual `strict=True` is closed-world, `strict=False` is open-world. Predicate inputs are arbitrary documents, not clean fact lists.

## Project Style
- Keep code short. Prefer OOP and existing domain classes; avoid one-use helpers and helpers under two lines unless they clarify real complexity.
- Do not add defensive `try/except` without user approval. Cleanup `try/finally` is fine when lifecycle ownership requires it.
- Put imports at module top; no method-level imports. Avoid compatibility shims, old aliases, and "just in case" re-exports.
- Serializable/validated models should use `pydantic.BaseModel`; local config models should use `pydantic_settings.BaseSettings`; LLM abstractions should use Pydantic AI when practical.
- Ask before adding new `cast` or `type: ignore`. Tests, evals, and QA can be less DRY than production code.
