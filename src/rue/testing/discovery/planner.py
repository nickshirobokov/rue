"""Static discovery phase — produces a serializable CollectionPlan.

``plan_collection()`` scans the filesystem using AST only (no imports, no
registry side-effects) and returns a :class:`CollectionPlan` that fully
describes the test suite.  The plan can be pickled and sent to worker
processes, or passed directly to a :class:`~rue.testing.discovery.loader.TestLoader`
in the same process.
"""

from __future__ import annotations

import ast
import os
from collections.abc import Sequence
from pathlib import Path

from rue.testing.discovery.plan import CollectionPlan, SetupFileRef
from rue.testing.models.spec import TestLocator, TestSpec


# ---------------------------------------------------------------------------
# Path helpers
# ---------------------------------------------------------------------------


def _resolve_path(path: Path | str | None) -> Path:
    if path is None:
        return Path.cwd().resolve()
    if isinstance(path, str):
        return Path(path).resolve()
    return path.resolve()


def _iter_test_files(path: Path) -> list[Path]:
    if path.is_file():
        if path.name.startswith("test_") and path.suffix == ".py":
            return [path]
        return []
    if path.is_dir():
        return sorted(path.rglob("test_*.py"))
    return []


def _iter_setup_files(path: Path) -> list[SetupFileRef]:
    if not path.is_dir():
        return []
    refs: list[SetupFileRef] = []
    conftest = path / "conftest.py"
    if conftest.is_file():
        refs.append(SetupFileRef(path=conftest, kind="conftest"))
    for p in sorted(path.glob("confrue_*.py")):
        refs.append(SetupFileRef(path=p, kind="confrue"))
    return refs


def _resolve_suite_root(explicit_root: Path) -> Path:
    for candidate in [explicit_root, *explicit_root.parents]:
        if (candidate / "pyproject.toml").exists():
            return candidate
    return explicit_root


def _resolve_collect_root(paths: list[Path]) -> Path:
    bases = [path.parent for path in paths]
    if len(bases) == 1:
        return bases[0]
    return Path(os.path.commonpath([str(b) for b in bases]))


def _iter_ancestor_dirs(root: Path, directory: Path) -> list[Path]:
    relative = directory.relative_to(root)
    current = root
    directories = [root]
    for part in relative.parts:
        current /= part
        directories.append(current)
    return directories


def _config_chain_for(path: Path, suite_root: Path) -> tuple[SetupFileRef, ...]:
    refs: list[SetupFileRef] = []
    for directory in _iter_ancestor_dirs(suite_root, path.parent):
        refs.extend(_iter_setup_files(directory))
    return tuple(refs)


# ---------------------------------------------------------------------------
# AST-only test detection (mirrors collector.py, no imports)
# ---------------------------------------------------------------------------


def _is_test_root(expr: ast.expr) -> bool:
    if isinstance(expr, ast.Name):
        return expr.id == "test"
    if isinstance(expr, ast.Attribute):
        return (
            isinstance(expr.value, ast.Name)
            and expr.value.id == "rue"
            and expr.attr == "test"
        )
    return False


def _is_rue_test_decorator(expr: ast.expr) -> bool:
    if isinstance(expr, ast.Call):
        return _is_rue_test_decorator(expr.func)
    if _is_test_root(expr):
        return True
    if isinstance(expr, ast.Attribute):
        return _is_rue_test_decorator(expr.value)
    return False


def _is_tag_root(expr: ast.expr) -> bool:
    return (
        isinstance(expr, ast.Attribute)
        and expr.attr == "tag"
        and _is_test_root(expr.value)
    )


def _is_tag_method(expr: ast.expr, method_name: str) -> bool:
    return (
        isinstance(expr, ast.Attribute)
        and expr.attr == method_name
        and _is_tag_root(expr.value)
    )


def _extract_static_tags(decorators: list[ast.expr]) -> set[str]:
    tags: set[str] = set()
    for decorator in decorators:
        if isinstance(decorator, ast.Call):
            if _is_tag_root(decorator.func):
                for arg in decorator.args:
                    if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                        tags.add(arg.value)
                continue
            if _is_tag_method(decorator.func, "skip"):
                tags.add("skip")
                continue
            if _is_tag_method(decorator.func, "xfail"):
                tags.add("xfail")
            continue
        if _is_tag_method(decorator, "inline"):
            tags.add("inline")
    return tags


def _collect_static_specs_from_file(path: Path) -> list[TestSpec]:
    """Parse one test file with AST and return TestSpec stubs.

    The specs produced here carry static tag/name information only.
    Fields that require importing the module (is_async, params, modifiers,
    skip_reason, …) are filled in during the materialization phase inside
    TestLoader.  They are set to safe empty defaults here so that static
    filtering (tags, keyword) works without an import.
    """
    tree = ast.parse(path.read_text(), filename=str(path))
    specs: list[TestSpec] = []

    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if any(_is_rue_test_decorator(d) for d in node.decorator_list):
                specs.append(
                    TestSpec(
                        locator=TestLocator(
                            module_path=path,
                            function_name=node.name,
                        ),
                        is_async=isinstance(node, ast.AsyncFunctionDef),
                        params=(),
                        modifiers=(),
                        tags=frozenset(_extract_static_tags(node.decorator_list)),
                    )
                )
            continue

        if isinstance(node, ast.ClassDef):
            class_tags = _extract_static_tags(node.decorator_list)
            class_is_rue = any(
                _is_rue_test_decorator(d) for d in node.decorator_list
            )
            for class_node in node.body:
                if isinstance(class_node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    if (class_is_rue and class_node.name.startswith("test_")) or any(
                        _is_rue_test_decorator(d)
                        for d in class_node.decorator_list
                    ):
                        tags = class_tags | _extract_static_tags(
                            class_node.decorator_list
                        )
                        specs.append(
                            TestSpec(
                                locator=TestLocator(
                                    module_path=path,
                                    function_name=class_node.name,
                                    class_name=node.name,
                                ),
                                is_async=isinstance(
                                    class_node, ast.AsyncFunctionDef
                                ),
                                params=(),
                                modifiers=(),
                                tags=frozenset(tags),
                            )
                        )

    return specs


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def _coerce_paths(
    paths: Path | str | Sequence[Path | str] | None,
) -> tuple[Path | str | None, ...]:
    if paths is None:
        return (None,)
    if isinstance(paths, (Path, str)):
        return (paths,)
    return tuple(paths)


def plan_collection(
    paths: Path | str | Sequence[Path | str] | None = None,
    *,
    explicit_root: Path | None = None,
) -> CollectionPlan:
    """Produce a serializable CollectionPlan by scanning the filesystem.

    This function performs **static analysis only** — no modules are imported,
    no registry is mutated.  The returned plan contains:

    * The suite root (used to build deterministic synthetic module names).
    * The setup-file chain for every test file (conftest + confrue paths in
      ancestor order).
    * A :class:`TestSpec` for every discovered test function / method.

    The specs produced here carry the information that can be extracted from
    AST alone (name, class, static tags, async-ness).  Fields that require
    importing the module (full params list, modifiers, skip/xfail reasons,
    definition errors, …) are filled in during the subsequent
    :meth:`~rue.testing.discovery.loader.TestLoader.materialize` call.  For
    static-only use-cases (tag filtering, dry runs) the AST-level information
    is sufficient.

    Args:
        paths: Files or directories to scan.  Directories are scanned
            recursively for ``test_*.py`` files.
        explicit_root: Override the automatically derived collection root.

    Returns:
        A fully serializable :class:`CollectionPlan`.
    """
    inputs = _coerce_paths(paths)
    resolved_paths: list[Path] = []
    for p in inputs:
        resolved_paths.extend(_iter_test_files(_resolve_path(p)))

    if not resolved_paths:
        if explicit_root is not None:
            suite_root = _resolve_path(explicit_root)
        elif len(inputs) == 1:
            root = _resolve_path(inputs[0])
            suite_root = root if root.is_dir() else root.parent
        else:
            suite_root = Path.cwd().resolve()
        return CollectionPlan(suite_root=suite_root)

    deduped = sorted({p.resolve() for p in resolved_paths})
    collect_root = (
        explicit_root.resolve()
        if explicit_root is not None
        else _resolve_collect_root(deduped)
    )
    suite_root = _resolve_suite_root(collect_root)

    setup_chains: dict[Path, tuple[SetupFileRef, ...]] = {}
    all_specs: list[TestSpec] = []

    for file_path in deduped:
        chain = _config_chain_for(file_path, suite_root)
        setup_chains[file_path] = chain
        all_specs.extend(_collect_static_specs_from_file(file_path))

    return CollectionPlan(
        suite_root=suite_root,
        setup_chains=setup_chains,
        specs=tuple(all_specs),
    )
