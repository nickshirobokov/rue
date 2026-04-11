"""Test discovery for rue_* files and pytest-style test names."""

import ast
import inspect
import os
from collections.abc import Callable, Iterator, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType
from typing import Any, Protocol, TypeVar

from rue.testing.decorators.tag import TagData, get_tag_data, merge_tag_data
from rue.testing.discovery.loader import RueImportSession
from rue.testing.models import Modifier, TestDefinition


@dataclass(frozen=True)
class StaticTestReference:
    """A test reference discovered from source without importing the module."""

    name: str
    module_path: Path
    class_name: str | None = None
    tags: frozenset[str] = frozenset()

    @property
    def full_name(self) -> str:
        """Full qualified name for matching and filtering."""
        if self.class_name:
            return f"{self.module_path.stem}::{self.class_name}::{self.name}"
        return f"{self.module_path.stem}::{self.name}"


def _resolve_path(path: Path | str | None) -> Path:
    if path is None:
        return Path.cwd().resolve()
    if isinstance(path, str):
        return Path(path).resolve()
    return path.resolve()


def _iter_rue_files(path: Path) -> list[Path]:
    if path.is_file():
        if path.name.startswith("rue_") and path.suffix == ".py":
            return [path]
        return []
    if path.is_dir():
        return sorted(path.rglob("rue_*.py"))
    return []


def _iter_confrue_files(path: Path) -> list[Path]:
    if not path.is_dir():
        return []
    return sorted(path.glob("confrue_*.py"))


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
    """Return True if the decorator AST node roots at `test` or `rue.test`."""
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
                    if (
                        isinstance(arg, ast.Constant)
                        and isinstance(arg.value, str)
                    ):
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


def _collect_static_from_module(path: Path) -> list[StaticTestReference]:
    module = ast.parse(path.read_text(), filename=str(path))
    refs: list[StaticTestReference] = []

    for node in module.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if node.name.startswith("test_") or any(
                _is_rue_test_decorator(d) for d in node.decorator_list
            ):
                refs.append(
                    StaticTestReference(
                        name=node.name,
                        module_path=path,
                        tags=frozenset(
                            _extract_static_tags(node.decorator_list)
                        ),
                    )
                )
            continue

        if isinstance(node, ast.ClassDef) and node.name.startswith("Test"):
            class_tags = _extract_static_tags(node.decorator_list)
            for class_node in node.body:
                if isinstance(
                    class_node, (ast.FunctionDef, ast.AsyncFunctionDef)
                ):
                    if class_node.name.startswith("test_") or any(
                        _is_rue_test_decorator(d)
                        for d in class_node.decorator_list
                    ):
                        tags = class_tags | _extract_static_tags(
                            class_node.decorator_list
                        )
                        refs.append(
                            StaticTestReference(
                                name=class_node.name,
                                module_path=path,
                                class_name=node.name,
                                tags=frozenset(tags),
                            )
                        )

    return refs


def collect_static(path: Path | str | None = None) -> list[StaticTestReference]:
    """Discover test names and tags without importing modules."""
    resolved_path = _resolve_path(path)
    refs: list[StaticTestReference] = []

    for file_path in _iter_rue_files(resolved_path):
        refs.extend(_collect_static_from_module(file_path))

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
    return Path(os.path.commonpath([str(base) for base in bases]))


def _iter_ancestor_dirs(root: Path, directory: Path) -> list[Path]:
    relative = directory.relative_to(root)
    current = root
    directories = [root]
    for part in relative.parts:
        current /= part
        directories.append(current)
    return directories


def _config_chain_for(path: Path, suite_root: Path) -> list[Path]:
    configs: list[Path] = []
    for directory in _iter_ancestor_dirs(suite_root, path.parent):
        configs.extend(_iter_confrue_files(directory))
    return configs


def _collect_paths(
    paths: list[Path], *, explicit_root: Path | None
) -> list[TestDefinition]:
    if not paths:
        return []

    resolved_paths = sorted({path.resolve() for path in paths})
    collect_root = (
        explicit_root.resolve()
        if explicit_root is not None
        else _resolve_collect_root(resolved_paths)
    )
    suite_root = _resolve_suite_root(collect_root)
    session = RueImportSession(suite_root)

    config_chains: dict[Path, list[Path]] = {}
    for file_path in resolved_paths:
        session.register_path(file_path)
        config_paths = _config_chain_for(file_path, suite_root)
        config_chains[file_path] = config_paths
        for config_path in config_paths:
            session.register_path(config_path)

    items: list[TestDefinition] = []
    for file_path in resolved_paths:
        for config_path in config_chains[file_path]:
            session.load_module(config_path)
        module = session.load_module(file_path)
        items.extend(_collect_from_module(module, file_path))

    return items


def _extract_test_params(fn: Callable[..., Any]) -> list[str]:
    """Extract parameter names from function signature (excluding 'self')."""
    sig = inspect.signature(fn)
    return [p for p in sig.parameters if p != "self"]


def _get_modifiers(fn: Callable[..., Any]) -> list[Modifier]:
    """Extract modifiers from function's __rue_modifiers__ attribute."""
    return getattr(fn, "__rue_modifiers__", [])


def _collect_from_module(
    module: ModuleType, module_path: Path
) -> list[TestDefinition]:
    """Collect all matching tests from a module."""
    items: list[TestDefinition] = []

    for name, obj in inspect.getmembers(module):
        if inspect.isfunction(obj) and (
            name.startswith("test_") or getattr(obj, "__rue_test__", False)
        ):
            items.append(_build_item_for_callable(obj, name, module_path))

        elif name.startswith("Test") and inspect.isclass(obj):
            class_tags = get_tag_data(obj)
            for method_name, method in inspect.getmembers(
                obj, predicate=inspect.isfunction
            ):
                if method_name.startswith("test_") or getattr(
                    method, "__rue_test__", False
                ):
                    items.append(
                        _build_item_for_callable(
                            method,
                            method_name,
                            module_path,
                            class_name=name,
                            parent_tags=class_tags,
                        )
                    )

    return items


def _build_item_for_callable(
    fn: Callable[..., Any],
    name: str,
    module_path: Path,
    class_name: str | None = None,
    parent_tags: TagData | None = None,
) -> TestDefinition:
    """Create a single TestDefinition for a callable with modifiers attached."""
    combined_tags = merge_tag_data(parent_tags, get_tag_data(fn))
    modifiers = reversed(_get_modifiers(fn))
    definition_error: str | None = getattr(fn, "__rue_definition_error__", None)

    return TestDefinition(
        name=name,
        fn=fn,
        module_path=module_path,
        is_async=inspect.iscoroutinefunction(fn),
        params=_extract_test_params(fn),
        class_name=class_name,
        modifiers=list(modifiers),
        tags=set(combined_tags.tags),
        skip_reason=combined_tags.skip_reason,
        xfail_reason=combined_tags.xfail_reason,
        xfail_strict=combined_tags.xfail_strict,
        definition_error=definition_error,
        inline=combined_tags.inline,
    )


def collect(path: Path | str | None = None) -> list[TestDefinition]:
    """Discover all matching tests from path.

    Args:
        path: File or directory to search. Defaults to current directory.

    Returns:
        List of discovered TestDefinition objects.

    Example:
        items = collect()  # Current directory
        items = collect("rue_agents.py")  # Specific file
        items = collect("./tests/")  # Directory
    """
    path = _resolve_path(path)
    file_paths = _iter_rue_files(path)
    explicit_root = path if path.is_dir() else path.parent
    return _collect_paths(file_paths, explicit_root=explicit_root)


def collect_paths(paths: Sequence[Path | str]) -> list[TestDefinition]:
    """Collect tests from multiple explicit module paths in one session."""
    resolved = [
        Path(path).resolve() if isinstance(path, str) else path.resolve()
        for path in paths
    ]
    return _collect_paths(resolved, explicit_root=None)


class Filterable(Protocol):
    """Minimal interface needed by filtering logic."""

    @property
    def tags(self) -> set[str] | frozenset[str]: ...

    @property
    def full_name(self) -> str: ...


FilterableT = TypeVar("FilterableT", bound=Filterable)


class _KeywordNames(Mapping[str, bool]):
    """Namespace for eval: each identifier is true iff it appears as a substring."""

    __slots__ = ("_text",)

    def __init__(self, text: str) -> None:
        self._text = text

    def __getitem__(self, key: str) -> bool:
        return key in self._text

    def __iter__(self) -> Iterator[str]:
        return iter(())

    def __len__(self) -> int:
        return 0


class KeywordMatcher:
    """Evaluate pytest-style -k expressions (Python ``and`` / ``or`` / ``not``)."""

    __slots__ = ("_code",)

    def __init__(self, expression: str) -> None:
        self._code = compile(expression, "<keyword>", "eval")

    def match(self, text: str) -> bool:
        return bool(
            eval(self._code, {"__builtins__": {}}, _KeywordNames(text))
        )


class TestCollector:
    """Discovers and filters test items for a given set of paths and criteria."""

    def __init__(
        self,
        include_tags: Sequence[str],
        exclude_tags: Sequence[str],
        keyword: str | None,
    ) -> None:
        self.include_tags = include_tags
        self.exclude_tags = exclude_tags
        self.keyword = keyword

    def collect(self, paths: Sequence[str]) -> list[TestDefinition]:
        static_refs: list[StaticTestReference] = []
        for path in paths:
            static_refs.extend(collect_static(path))

        selected_refs = self.filter(static_refs)
        if not selected_refs:
            return []

        selected_paths = sorted({ref.module_path for ref in selected_refs})
        items = collect_paths(selected_paths)
        return self.filter(items)

    def filter(self, items: Sequence[FilterableT]) -> list[FilterableT]:
        filtered = list(items)

        if self.include_tags:
            include = set(self.include_tags)
            filtered = [item for item in filtered if item.tags & include]

        if self.exclude_tags:
            exclude = set(self.exclude_tags)
            filtered = [item for item in filtered if not (item.tags & exclude)]

        if self.keyword:
            matcher = KeywordMatcher(self.keyword)
            filtered = [
                item for item in filtered if matcher.match(item.full_name)
            ]

        return filtered
