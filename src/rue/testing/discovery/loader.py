"""Import/session machinery for discovered Rue test modules."""

from __future__ import annotations

import ast
import hashlib
import importlib
import importlib.abc
import importlib.machinery
import importlib.util
import pkgutil
import sys
from dataclasses import dataclass, field
from pathlib import Path
from types import FunctionType, MethodType, ModuleType
from typing import TypeVar

from rue.assertions.transformers import (
    AssertTransformer,
    InjectAssertionDependenciesTransformer,
)
from rue.resources.fixtures_collector import (
    InjectFixtureResourceDependenciesTransformer,
    RewritePytestFixtureDecoratorsTransformer,
)
from rue.testing.decorators.tag import get_tag_data, merge_tag_data
from rue.testing.models.definition import TestDefinition
from rue.testing.models.spec import TestSpec, TestSpecCollection


TFunction = TypeVar("TFunction", ast.FunctionDef, ast.AsyncFunctionDef)
RUE_DISCOVERY_PACKAGE = "rue_discovery"


class RuePackageLoader(importlib.abc.Loader):
    """Loader for synthetic package nodes in the discovery namespace."""

    def __init__(self, path: Path) -> None:
        self.path = path

    def create_module(self, spec: importlib.machinery.ModuleSpec) -> None:
        _ = spec

    def exec_module(self, module: ModuleType) -> None:
        module.__file__ = str(self.path)
        module.__path__ = [str(self.path)]


@dataclass(slots=True)
class RueImportSession:
    """Import state for a single discovery pass.

    The ``root_package`` name is derived deterministically from ``root`` so
    that parent and worker processes importing from the same suite root
    produce identical synthetic module names — a prerequisite for correct
    pickling of function objects and consistent ``__module__`` attributes
    across processes.

    Within a single process, ``sys.modules`` caches modules across multiple
    materialization calls on the same suite root. Restarting the process
    is required to pick up on-disk changes to already-imported files.
    """

    root: Path
    root_package: str = field(init=False)
    module_paths: dict[str, Path] = field(default_factory=dict)
    package_paths: dict[str, Path] = field(default_factory=dict)
    path_to_module_name: dict[Path, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.root = self.root.resolve()
        # Deterministic: same root → same package name in every process.
        self.root_package = (
            f"{RUE_DISCOVERY_PACKAGE}"
            f".suite_{hashlib.blake2s(str(self.root).encode(), digest_size=8).hexdigest()}"
        )
        if RUE_DISCOVERY_PACKAGE not in sys.modules:
            module = ModuleType(RUE_DISCOVERY_PACKAGE)
            spec = importlib.machinery.ModuleSpec(
                RUE_DISCOVERY_PACKAGE,
                loader=None,
                is_package=True,
            )
            spec.submodule_search_locations = []
            module.__package__ = RUE_DISCOVERY_PACKAGE
            module.__path__ = []
            module.__spec__ = spec
            sys.modules[RUE_DISCOVERY_PACKAGE] = module

        if _RUE_DISCOVERY_FINDER not in sys.meta_path:
            sys.meta_path.insert(0, _RUE_DISCOVERY_FINDER)

        _RUE_DISCOVERY_FINDER.register(self)

    def package_name_for_dir(self, directory: Path) -> str:
        """Return the synthetic package name for a directory."""
        directory = directory.resolve()
        if directory == self.root:
            return self.root_package

        relative = directory.relative_to(self.root)
        parts = [self.root_package]
        current = Path()
        for depth, part in enumerate(relative.parts):
            current /= part
            parts.append(
                f"pkg_{depth}_{hashlib.blake2s(current.as_posix().encode(), digest_size=4).hexdigest()}"
            )
        return ".".join(parts)

    def register_path(self, path: Path) -> str:
        """Register a file path and return its synthetic module name."""
        path = path.resolve()
        cached = self.path_to_module_name.get(path)
        if cached is not None:
            return cached

        current = path.parent
        while current != self.root:
            package_name = self.package_name_for_dir(current)
            self.package_paths.setdefault(package_name, current)
            current = current.parent

        module_name = f"{self.package_name_for_dir(path.parent)}.{path.stem}"
        self.module_paths[module_name] = path
        self.path_to_module_name[path] = module_name
        return module_name

    def load_module(self, path: Path) -> ModuleType:
        """Import a previously registered path through the session finder."""
        module_name = self.register_path(path)
        return importlib.import_module(module_name)


class RueDiscoveryFinder(importlib.abc.MetaPathFinder):
    """Meta-path finder for per-session synthetic discovery packages."""

    def __init__(self) -> None:
        self._sessions: dict[str, RueImportSession] = {}

    def register(self, session: RueImportSession) -> None:
        """Register a discovery session by its synthetic root package."""
        self._sessions[session.root_package] = session

    def find_spec(
        self,
        fullname: str,
        path: object | None = None,
        target: object | None = None,
    ) -> importlib.machinery.ModuleSpec | None:
        """Resolve synthetic discovery packages and modules."""
        _ = path, target
        session = self._match_session(fullname)
        if session is None:
            return None

        if fullname == session.root_package:
            return self._package_spec(fullname, session.root)

        package_path = session.package_paths.get(fullname)
        if package_path is not None:
            return self._package_spec(fullname, package_path)

        module_path = session.module_paths.get(fullname)
        if module_path is None:
            return None
        return importlib.util.spec_from_loader(
            fullname,
            RueModuleLoader(fullname=fullname, path=module_path),
            origin=str(module_path),
        )

    def _match_session(self, fullname: str) -> RueImportSession | None:
        for root_package, session in self._sessions.items():
            if fullname == root_package or fullname.startswith(
                f"{root_package}."
            ):
                return session
        return None

    @staticmethod
    def _package_spec(
        fullname: str, path: Path
    ) -> importlib.machinery.ModuleSpec:
        spec = importlib.machinery.ModuleSpec(
            fullname,
            RuePackageLoader(path),
            is_package=True,
        )
        spec.submodule_search_locations = [str(path)]
        return spec


_RUE_DISCOVERY_FINDER = RueDiscoveryFinder()


class RueFunctionTransformer(ast.NodeTransformer):
    """Finds all test functions in the module and transforms them."""

    def __init__(self, transformers: list[ast.NodeTransformer]) -> None:
        self.transformers = transformers

    def apply_transformers(self, node: TFunction) -> TFunction:
        """Apply configured transformer pipeline to a single function node."""
        for transformer in self.transformers:
            node = transformer.visit(node)
        return ast.fix_missing_locations(node)

    def visit_FunctionDef(self, node: ast.FunctionDef):
        if node.name.startswith("test_") or any(
            _is_test_decorator(d) for d in node.decorator_list
        ):
            node = self.apply_transformers(node)
            return node
        return self.generic_visit(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef):
        if node.name.startswith("test_") or any(
            _is_test_decorator(d) for d in node.decorator_list
        ):
            node = self.apply_transformers(node)
            return node
        return self.generic_visit(node)


def _is_test_decorator(node: ast.expr) -> bool:
    """Return True if the AST node is any supported @test / @rue.test decorator form."""
    if isinstance(node, ast.Call):
        return _is_test_decorator(node.func)
    if isinstance(node, ast.Name) and node.id == "test":
        return True
    if isinstance(node, ast.Attribute):
        if node.attr == "test" and isinstance(node.value, ast.Name) and node.value.id == "rue":
            return True
        return _is_test_decorator(node.value)
    return False


def _is_metric_decorator(node: ast.expr) -> bool:
    """Return True if the AST node is any supported @metric decorator form."""
    target = node.func if isinstance(node, ast.Call) else node
    if isinstance(target, ast.Name):
        return target.id == "metric"
    if isinstance(target, ast.Attribute) and target.attr == "metric":
        val = target.value
        if isinstance(val, ast.Name) and val.id == "rue":
            return True
        if (
            isinstance(val, ast.Attribute)
            and val.attr == "resource"
            and isinstance(val.value, ast.Name)
            and val.value.id == "rue"
        ):
            return True
    return False


class RueMetricTransformer(ast.NodeTransformer):
    """Find metric functions and transform them."""

    def __init__(self, transformers: list[ast.NodeTransformer]) -> None:
        self.transformers = transformers

    def apply_transformers(self, node: TFunction) -> TFunction:
        for transformer in self.transformers:
            node = transformer.visit(node)
        return ast.fix_missing_locations(node)

    def visit_FunctionDef(self, node: ast.FunctionDef):
        if any(_is_metric_decorator(d) for d in node.decorator_list):
            return self.apply_transformers(node)
        return self.generic_visit(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef):
        if any(_is_metric_decorator(d) for d in node.decorator_list):
            return self.apply_transformers(node)
        return self.generic_visit(node)


class RueModuleLoader(importlib.abc.SourceLoader):
    """Custom loader for Rue test modules with AST transformations."""

    def __init__(self, fullname: str, path: Path) -> None:
        self.fullname = fullname
        self.path = path

    def get_filename(self, fullname: str) -> str:
        return str(self.path)

    def get_data(self, path: str) -> bytes:
        return Path(path).read_bytes()

    def exec_module(self, module: ModuleType) -> None:
        filename = self.get_filename(module.__name__)
        source = self.get_source(module.__name__)
        if source is None:
            msg = f"Cannot get source for module {module.__name__}"
            raise ImportError(msg)

        tree = ast.parse(source, filename=filename)
        for transformer in [
            RewritePytestFixtureDecoratorsTransformer(),
            InjectFixtureResourceDependenciesTransformer(),
            RueMetricTransformer(
                transformers=[
                    InjectAssertionDependenciesTransformer(),
                    AssertTransformer(source),
                ]
            ),
            RueFunctionTransformer(
                transformers=[
                    InjectAssertionDependenciesTransformer(),
                    AssertTransformer(source),
                ]
            ),
        ]:
            tree = transformer.visit(tree)
        validated_tree = ast.fix_missing_locations(tree)

        code = compile(validated_tree, filename=filename, mode="exec")
        exec(code, module.__dict__)


class TestLoader:
    """Materializes :class:`TestSpec` objects into live :class:`TestDefinition` instances.

    Safe to construct in any process.  Given the same :class:`TestSpecCollection`
    (suite root + setup file chain), two ``TestLoader`` instances
    in two different processes will import modules under identical synthetic
    names — a prerequisite for pickle-safe function objects and consistent
    ``__module__`` attributes across processes.

    Registry population is a side-effect of :meth:`prepare_setup`: importing
    the setup files causes resource decorators to fire, and supported
    pytest fixtures are rewritten into equivalent resource decorators
    during import.
    """

    def __init__(self, suite_root: Path) -> None:
        self._suite_root = suite_root.resolve()
        self._session = RueImportSession(self._suite_root)
        self._prepared_paths: set[Path] = set()

    def prepare_setup(self, path: Path) -> None:
        """Import one setup file and register any fixtures/resources it defines.

        Idempotent: calling this more than once for the same path is safe.
        """
        path = path.resolve()
        if path in self._prepared_paths:
            return
        self._prepared_paths.add(path)
        self._session.load_module(path)

    def load_from_collection(
        self, collection: TestSpecCollection
    ) -> list[TestDefinition]:
        """Resolve every spec in a collection to a live TestDefinition."""
        if not collection.specs:
            return []

        by_module: dict[Path, list[TestSpec]] = {}
        for spec in collection.specs:
            by_module.setdefault(spec.module_path, []).append(spec)

        items: list[TestDefinition] = []
        for module_path, requested_specs in by_module.items():
            for setup_ref in collection.setup_chain_for(module_path):
                self.prepare_setup(setup_ref.path)

            module = self._session.load_module(module_path.resolve())
            for spec in requested_specs:
                items.append(self.load_definition(spec, module=module))

        return items

    def load_definition(
        self, spec: TestSpec, module: ModuleType | None = None
    ) -> TestDefinition:
        """Resolve a spec to a live TestDefinition by importing its module.

        When ``module`` is omitted, the module is imported through the session
        (with AST transformations applied).  The callable is looked up by name
        inside the module or class namespace.
        """
        if module is None:
            module = self._session.load_module(spec.module_path.resolve())

        match spec.locator.class_name:
            case str() as class_name:
                cls = pkgutil.resolve_name(f"{module.__name__}:{class_name}")
                fn = pkgutil.resolve_name(
                    f"{module.__name__}:{class_name}.{spec.locator.function_name}"
                )
                if not isinstance(fn, (FunctionType, MethodType)):
                    raise TypeError(
                        f"not a function or method: {module.__name__}:{class_name}.{spec.locator.function_name}"
                    )
                parent_tags = get_tag_data(cls)
            case None:
                fn = pkgutil.resolve_name(
                    f"{module.__name__}:{spec.locator.function_name}"
                )
                if not isinstance(fn, (FunctionType, MethodType)):
                    raise TypeError(
                        f"not a function or method: {module.__name__}:{spec.locator.function_name}"
                    )
                parent_tags = None

        combined_tags = merge_tag_data(parent_tags, get_tag_data(fn))
        spec.update_tags(combined_tags)
        spec.get_execution_from_fn(fn)
        return TestDefinition(spec=spec, fn=fn)
