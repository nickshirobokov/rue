"""Import/session machinery for discovered Rue test modules."""

import ast
import hashlib
import importlib
import importlib.abc
import importlib.machinery
import importlib.util
import sys
from dataclasses import dataclass, field
from pathlib import Path
from types import ModuleType
from typing import TypeVar
from uuid import uuid4

from rue.assertions.transformers import (
    AssertTransformer,
    InjectAssertionDependenciesTransformer,
)


TFunction = TypeVar("TFunction", ast.FunctionDef, ast.AsyncFunctionDef)
RUE_DISCOVERY_PACKAGE = "rue_discovery"


def _short_hash(value: str) -> str:
    return hashlib.blake2s(value.encode(), digest_size=4).hexdigest()


def _ensure_discovery_package() -> None:
    if RUE_DISCOVERY_PACKAGE in sys.modules:
        return

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
    """Import state for a single discovery pass."""

    root: Path
    root_package: str = field(init=False)
    module_paths: dict[str, Path] = field(default_factory=dict)
    package_paths: dict[str, Path] = field(default_factory=dict)
    path_to_module_name: dict[Path, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.root = self.root.resolve()
        self.root_package = f"{RUE_DISCOVERY_PACKAGE}.session_{uuid4().hex}"
        _ensure_discovery_package()
        _install_discovery_finder()
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
            parts.append(f"pkg_{depth}_{_short_hash(current.as_posix())}")
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


def _install_discovery_finder() -> None:
    if _RUE_DISCOVERY_FINDER not in sys.meta_path:
        sys.meta_path.insert(0, _RUE_DISCOVERY_FINDER)


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
        if node.name.startswith("test_"):
            node = self.apply_transformers(node)
            return node
        return self.generic_visit(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef):
        if node.name.startswith("test_"):
            node = self.apply_transformers(node)
            return node
        return self.generic_visit(node)


def _is_metric_decorator(node: ast.expr) -> bool:
    """Return True if the AST node is any supported @metric decorator form.

    Matches:
      @metric
      @rue.metric
      @rue.resource.metric
      @metric(...)
      @rue.metric(...)
      @rue.resource.metric(...)
    """
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
    """Find metric functions (decorated with `@rue.resource.metric` / `@metric`) and transform them."""

    def __init__(self, transformers: list[ast.NodeTransformer]) -> None:
        self.transformers = transformers

    def apply_transformers(self, node: TFunction) -> TFunction:
        """Apply configured transformer pipeline to a single function node."""
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
    """Custom loader for Rue test modules with AST transformations.

    This loader participates in Python's import protocol and handles
    AST transformation and injection of Rue-specific globals during
    module execution.
    """

    def __init__(self, fullname: str, path: Path) -> None:
        """Initialize the loader.

        Args:
            fullname: The fully qualified module name.
            path: Path to the module file.
        """
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

        module_transformers = [
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
        ]
        tree = ast.parse(source, filename=filename)
        for transformer in module_transformers:
            tree = transformer.visit(tree)
        validated_tree = ast.fix_missing_locations(tree)

        code = compile(validated_tree, filename=filename, mode="exec")
        exec(code, module.__dict__)
