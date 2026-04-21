"""AST and runtime hooks that map pytest fixtures to Rue resources."""

import ast
from collections.abc import Callable
from typing import cast

from rue.resources.models import Scope
from rue.resources.registry import registry as default_registry, resource


type ResourceFactory = Callable[..., object]
type ResourceDecorator = Callable[[ResourceFactory], ResourceFactory]


def decorate_pytest_fixture_as_resource(
    fn: ResourceFactory | None = None,
    *,
    scope: Scope | str = "function",
    params: object | None = None,
    **kwargs: object,
) -> ResourceFactory | ResourceDecorator:
    _ = kwargs

    def decorator(fn: ResourceFactory) -> ResourceFactory:
        if params is not None or default_registry.get(fn.__name__) is not None:
            return fn
        match scope:
            case Scope():
                mapped_scope = scope
            case "function":
                mapped_scope = Scope.TEST
            case "class" | "module":
                mapped_scope = Scope.MODULE
            case "package" | "session":
                mapped_scope = Scope.PROCESS
            case _:
                mapped_scope = Scope.TEST
        return cast("ResourceFactory", resource(fn, scope=mapped_scope))

    if fn is not None:
        return decorator(fn)
    return decorator


class RewritePytestFixtureDecoratorsTransformer(ast.NodeTransformer):
    """Rewrite supported ``pytest.fixture`` forms to ``__rue_fixture_resource__``."""

    def __init__(self) -> None:
        self._pytest_aliases: set[str] = set()
        self._fixture_aliases: set[str] = set()
        self._class_depth = 0
        self._function_depth = 0

    def visit_Module(self, node: ast.Module) -> ast.Module:
        self._collect_aliases(node)
        return cast("ast.Module", self.generic_visit(node))

    def visit_ClassDef(self, node: ast.ClassDef) -> ast.ClassDef:
        self._class_depth += 1
        try:
            return cast("ast.ClassDef", self.generic_visit(node))
        finally:
            self._class_depth -= 1

    def visit_FunctionDef(self, node: ast.FunctionDef) -> ast.FunctionDef:
        return cast("ast.FunctionDef", self._visit_function(node))

    def visit_AsyncFunctionDef(
        self, node: ast.AsyncFunctionDef
    ) -> ast.AsyncFunctionDef:
        return cast("ast.AsyncFunctionDef", self._visit_function(node))

    def _visit_function(
        self, node: ast.FunctionDef | ast.AsyncFunctionDef
    ) -> ast.FunctionDef | ast.AsyncFunctionDef:
        if self._class_depth == 0 and self._function_depth == 0:
            node.decorator_list = [
                self._rewrite_fixture_decorator(decorator)
                for decorator in node.decorator_list
            ]

        self._function_depth += 1
        try:
            return cast(
                "ast.FunctionDef | ast.AsyncFunctionDef",
                self.generic_visit(node),
            )
        finally:
            self._function_depth -= 1

    def _collect_aliases(self, node: ast.Module) -> None:
        for statement in node.body:
            match statement:
                case ast.Import(names=names):
                    for alias in names:
                        if alias.name == "pytest":
                            self._pytest_aliases.add(alias.asname or alias.name)
                case ast.ImportFrom(module="pytest", names=names):
                    for alias in names:
                        if alias.name == "fixture":
                            self._fixture_aliases.add(
                                alias.asname or alias.name
                            )

    def _rewrite_fixture_decorator(self, decorator: ast.expr) -> ast.expr:
        match decorator:
            case ast.Name() if self._is_fixture_reference(decorator):
                return ast.copy_location(
                    ast.Name(id="__rue_fixture_resource__", ctx=ast.Load()),
                    decorator,
                )
            case ast.Attribute() if self._is_fixture_reference(decorator):
                return ast.copy_location(
                    ast.Name(id="__rue_fixture_resource__", ctx=ast.Load()),
                    decorator,
                )
            case ast.Call(func=func, args=args, keywords=keywords) if (
                self._is_fixture_reference(func) and not args
            ):
                return ast.copy_location(
                    ast.Call(
                        func=ast.Name(
                            id="__rue_fixture_resource__", ctx=ast.Load()
                        ),
                        args=[],
                        keywords=keywords,
                    ),
                    decorator,
                )
            case _:
                return decorator

    def _is_fixture_reference(self, decorator: ast.expr) -> bool:
        match decorator:
            case ast.Name(id=name):
                return name in self._fixture_aliases
            case ast.Attribute(
                value=ast.Name(id=module_name),
                attr="fixture",
            ):
                return module_name in self._pytest_aliases
            case _:
                return False


class InjectFixtureResourceDependenciesTransformer(ast.NodeTransformer):
    """Inject fixture resource rewrite dependencies into a module body.

    We inject imports at the top of each transformed module when decorators
    reference `__rue_fixture_resource__`, so rewritten `pytest.fixture` forms
    can resolve without relying on the module loader to bind the name.
    """

    def visit_Module(self, node: ast.Module) -> ast.Module:
        uses = False
        for n in ast.walk(node):
            if not isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            for d in n.decorator_list:
                match d:
                    case ast.Name(id="__rue_fixture_resource__"):
                        uses = True
                    case ast.Call(func=ast.Name(id="__rue_fixture_resource__")):
                        uses = True
                    case _:
                        continue
                if uses:
                    break
            if uses:
                break
        if not uses:
            return node

        inject_stmts: list[ast.stmt] = [
            ast.ImportFrom(
                module="rue.resources.fixtures_collector",
                names=[
                    ast.alias(
                        name="decorate_pytest_fixture_as_resource",
                        asname="__rue_fixture_resource__",
                    )
                ],
                level=0,
            ),
        ]

        body = list(node.body)
        insert_at = 1 if ast.get_docstring(node, clean=False) is not None else 0
        node.body = [*body[:insert_at], *inject_stmts, *body[insert_at:]]

        for stmt in inject_stmts:
            ast.copy_location(stmt, node)
        return node
