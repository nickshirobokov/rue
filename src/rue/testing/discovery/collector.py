"""Static test spec collection and filtering."""

from __future__ import annotations

import ast
import os
from collections.abc import Iterator, Mapping, Sequence
from pathlib import Path

from rue.testing.models.spec import (
    SetupFileRef,
    TestLocator,
    TestSpec,
    TestSpecCollection,
)


class _StaticSpecVisitor(ast.NodeVisitor):
    def __init__(self, path: Path) -> None:
        self._path = path
        self._class_name: str | None = None
        self._class_tags: frozenset[str] = frozenset()
        self._class_is_rue = False
        self.specs: list[TestSpec] = []

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._visit_test_function(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self._visit_test_function(node)

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        if self._class_name is not None:
            return

        self._class_name = node.name
        self._class_tags = frozenset(
            self._extract_static_tags(node.decorator_list)
        )
        self._class_is_rue = any(
            self._is_rue_test_decorator(decorator)
            for decorator in node.decorator_list
        )
        for child in node.body:
            self.visit(child)
        self._class_name = None
        self._class_tags = frozenset()
        self._class_is_rue = False

    def _visit_test_function(
        self, node: ast.FunctionDef | ast.AsyncFunctionDef
    ) -> None:
        has_rue_test = any(
            self._is_rue_test_decorator(decorator)
            for decorator in node.decorator_list
        )
        if self._class_name is None and not has_rue_test:
            return
        if self._class_name is not None and not (
            (self._class_is_rue and node.name.startswith("test_"))
            or has_rue_test
        ):
            return

        tags = self._extract_static_tags(node.decorator_list)
        if self._class_name is not None:
            tags = set(self._class_tags | tags)

        self.specs.append(
            TestSpec(
                locator=TestLocator(
                    module_path=self._path,
                    function_name=node.name,
                    class_name=self._class_name,
                ),
                is_async=isinstance(node, ast.AsyncFunctionDef),
                params=(),
                modifiers=(),
                tags=frozenset(tags),
            )
        )

    def _is_test_root(self, expr: ast.expr) -> bool:
        match expr:
            case ast.Name(id="test"):
                return True
            case ast.Attribute(value=ast.Name(id="rue"), attr="test"):
                return True
            case _:
                return False

    def _is_rue_test_decorator(self, expr: ast.expr) -> bool:
        match expr:
            case ast.Call(func=func):
                return self._is_rue_test_decorator(func)
            case ast.Name() | ast.Attribute():
                if self._is_test_root(expr):
                    return True
                if isinstance(expr, ast.Attribute):
                    return self._is_rue_test_decorator(expr.value)
            case _:
                return False
        return False

    def _is_tag_root(self, expr: ast.expr) -> bool:
        match expr:
            case ast.Attribute(value=value, attr="tag"):
                return self._is_test_root(value)
            case _:
                return False

    def _is_tag_method(self, expr: ast.expr, method_name: str) -> bool:
        match expr:
            case ast.Attribute(value=value, attr=attr):
                return attr == method_name and self._is_tag_root(value)
            case _:
                return False

    def _extract_static_tags(self, decorators: list[ast.expr]) -> set[str]:
        tags: set[str] = set()
        for decorator in decorators:
            match decorator:
                case ast.Call(func=func, args=args) if self._is_tag_root(func):
                    tags.update(
                        arg.value
                        for arg in args
                        if isinstance(arg, ast.Constant)
                        and isinstance(arg.value, str)
                    )
                case ast.Call(func=func) if self._is_tag_method(func, "skip"):
                    tags.add("skip")
                case ast.Call(func=func) if self._is_tag_method(func, "xfail"):
                    tags.add("xfail")
                case ast.Attribute() if self._is_tag_method(
                    decorator, "inline"
                ):
                    tags.add("inline")
        return tags


class _KeywordNames(Mapping[str, bool]):
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
    """Evaluate pytest-style -k expressions."""

    __slots__ = ("_code",)

    def __init__(self, expression: str) -> None:
        self._code = compile(expression, "<keyword>", "eval")

    def match(self, text: str) -> bool:
        return bool(
            eval(self._code, {"__builtins__": {}}, _KeywordNames(text))
        )


class TestSpecCollector:
    """Build filtered spec collections using static AST discovery only."""

    def __init__(
        self,
        include_tags: Sequence[str],
        exclude_tags: Sequence[str],
        keyword: str | None,
    ) -> None:
        self.include_tags = frozenset(include_tags)
        self.exclude_tags = frozenset(exclude_tags)
        self.keyword = keyword
        self._keyword_matcher = KeywordMatcher(keyword) if keyword else None

    def build_spec_collection(
        self,
        paths: Sequence[Path | str],
        *,
        explicit_root: Path | None = None,
    ) -> TestSpecCollection:
        explicit_root = explicit_root.resolve() if explicit_root else None
        inputs = tuple(Path(path).resolve() for path in paths)
        module_paths = sorted(
            {
                module_path
                for path in inputs
                for module_path in (
                    [path]
                    if path.is_file()
                    and path.suffix == ".py"
                    and path.name.startswith("test_")
                    else path.rglob("test_*.py")
                    if path.is_dir()
                    else ()
                )
            }
        )

        if not module_paths:
            if explicit_root is not None:
                return TestSpecCollection(suite_root=explicit_root)
            if len(inputs) == 1:
                [root] = inputs
                return TestSpecCollection(
                    suite_root=root if root.is_dir() else root.parent
                )
            return TestSpecCollection(suite_root=Path.cwd().resolve())

        collect_root = explicit_root or Path(
            os.path.commonpath(
                [module_path.parent for module_path in module_paths]
            )
        )
        suite_root = next(
            (
                candidate
                for candidate in (collect_root, *collect_root.parents)
                if (candidate / "pyproject.toml").exists()
            ),
            collect_root,
        )

        setup_chains: dict[Path, tuple[SetupFileRef, ...]] = {}
        specs: list[TestSpec] = []
        for module_path in module_paths:
            visitor = _StaticSpecVisitor(module_path)
            visitor.visit(
                ast.parse(
                    module_path.read_text(),
                    filename=str(module_path),
                )
            )
            if not (module_specs := self.filter_specs(visitor.specs)):
                continue

            parts = module_path.parent.relative_to(suite_root).parts
            directories = [
                suite_root,
                *(
                    suite_root.joinpath(*parts[:depth])
                    for depth in range(1, len(parts) + 1)
                ),
            ]

            chain: list[SetupFileRef] = []
            for directory in directories:
                if (conftest := directory / "conftest.py").is_file():
                    chain.append(
                        SetupFileRef(path=conftest, kind="conftest")
                    )
                chain.extend(
                    SetupFileRef(path=setup_path, kind="confrue")
                    for setup_path in sorted(directory.glob("confrue_*.py"))
                )

            setup_chains[module_path] = tuple(chain)
            specs.extend(module_specs)

        return TestSpecCollection(
            suite_root=suite_root,
            setup_chains=setup_chains,
            specs=tuple(specs),
        )

    def filter_specs(self, items: Sequence[TestSpec]) -> list[TestSpec]:
        filtered = list(items)

        if self.include_tags:
            filtered = [
                item
                for item in filtered
                if item.tags & self.include_tags
            ]

        if self.exclude_tags:
            filtered = [
                item
                for item in filtered
                if not (item.tags & self.exclude_tags)
            ]

        if self._keyword_matcher is not None:
            filtered = [
                item
                for item in filtered
                if self._keyword_matcher.match(item.full_name)
            ]

        return filtered
