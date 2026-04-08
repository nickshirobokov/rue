# RFC: Resource Registration and Injection

**Status:** Draft
**Intended use:** Normative foundation for Rue resource registration, lookup, injection, and lifecycle management
**Version:** 1.0

## Abstract

This document specifies the `rue.resources` API.

It defines:

* resource registration through `ResourceRegistry`
* the default singleton registry `registry`
* decorator-based registration through `resource(...)`
* runtime resolution through `ResourceResolver`
* lifecycle scopes through `Scope`
* hierarchical `SESSION` lookup anchored to the requesting test module path

This RFC is normative for the `rue.resources` package itself.

Convenience re-exports from other packages, such as `rue.testing.resource` or `rue.resource`, are outside the primary API specified here. They MAY exist, but they do not define additional semantics.

---

## 1. Conventions and Normative Language

The key words **MUST**, **MUST NOT**, **SHOULD**, **SHOULD NOT**, and **MAY** are normative.

Unless otherwise stated:

* "resource name" means the registered function name
* "request path" means the current test module path used to anchor hierarchical `SESSION` lookup
* "provider" means the selected `ResourceDef` chosen for one resolution request

This RFC specifies public behavior. It does not freeze private attribute names or internal data structures.

---

## 2. Goals

The goals of the resources API are:

* register injectable dependencies by function name
* support sync, async, generator, and async-generator resources
* provide explicit registry ownership
* provide deterministic scope-aware caching and teardown
* support conftest-style hierarchical `SESSION` resources
* keep decorator ergonomics for normal test authoring

---

## 3. Non-Goals

This RFC does not define:

* arbitrary service-locator behavior
* type-based dependency lookup
* named scopes beyond `CASE`, `SUITE`, and `SESSION`
* automatic registry isolation across threads or processes
* post-`teardown()` resolver reuse semantics
* any API for unregistering one resource by name

---

## 4. Public API Surface

The canonical package surface is:

```python
from rue.resources import (
    ResourceDef,
    ResourceRegistry,
    ResourceResolver,
    Scope,
    registry,
    resource,
)
```

### 4.1 `Scope`

`Scope` is an enum with exactly three values:

* `Scope.CASE`
* `Scope.SUITE`
* `Scope.SESSION`

Their string values are `"case"`, `"suite"`, and `"session"` respectively.

### 4.2 `ResourceDef`

`ResourceDef` is the public definition record for a registered resource.

It contains:

* `name`
* `fn`
* `scope`
* `is_async`
* `is_generator`
* `is_async_generator`
* `dependencies`
* `on_resolve`
* `on_injection`
* `on_teardown`
* `origin_path`
* `origin_dir`

### 4.3 `ResourceRegistry`

`ResourceRegistry` is the canonical registration and selection object.

Its public methods are:

* `resource(...)`
* `get(name)`
* `select(name, request_path)`
* `mark_builtin(name)`
* `reset()`

### 4.4 `registry`

`registry` is the default singleton `ResourceRegistry`.

### 4.5 `resource(...)`

`resource(...)` is decorator sugar for `registry.resource(...)`.

### 4.6 `ResourceResolver`

`ResourceResolver(resource_registry)` resolves and caches resources for execution.

Its public methods are:

* `resolve(name)`
* `resolve_many(names)`
* `fork_for_case()`
* `teardown()`
* `teardown_scope(scope)`

The resolver constructor MUST be passed a `ResourceRegistry`. There is no implicit default.

---

## 5. Registration Model

### 5.1 Naming

Resources are registered by decorated function name.

For example:

```python
@resource
def db():
    ...
```

registers the resource name `db`.

The API does not provide a separate explicit `name=` override.

### 5.2 Dependency discovery

Dependencies are discovered from the function signature.

All parameter names except `self` and `cls` become dependency names.

This rule applies uniformly to:

* sync functions
* async functions
* generator functions
* async-generator functions

### 5.3 Resource kinds

The registry MUST classify each resource as one of:

* sync function
* async function
* generator function
* async-generator function

This classification controls runtime creation and teardown behavior.

### 5.4 Origin metadata

On registration, the registry MUST derive:

* `origin_path`
* `origin_dir`

from `fn.__code__.co_filename`.

If the filename is synthetic, such as `<string>`, both fields MUST be `None`.

### 5.5 Decorator options

The `resource(...)` decorator and `ResourceRegistry.resource(...)` support:

* `scope`
* `on_resolve`
* `on_injection`
* `on_teardown`

`scope` MAY be passed as either `Scope` or its string value.

---

## 6. Registry Semantics

### 6.1 `get(name)`

`get(name)` returns the flat definition currently registered under `name`, or `None`.

It does not perform hierarchical lookup.

### 6.2 Registration precedence

The registry maintains both:

* a flat definition map
* a session-only hierarchical index

Registration rules are:

* non-`SESSION` resources replace the flat definition for their name
* `SESSION` resources are appended to the session index for their name
* a `SESSION` resource replaces the flat definition only when the current flat definition is absent or also `SESSION`

As a result:

* `CASE` and `SUITE` resources win over same-name `SESSION` resources for direct DI selection
* multiple `SESSION` resources with the same name can coexist in the hierarchical index

### 6.3 `select(name, request_path)`

`select(name, request_path)` chooses the active provider for dependency injection.

It returns a selected provider object containing:

* `definition`
* `provider_dir`

Selection rules are:

* if a flat non-`SESSION` definition exists, it MUST be selected immediately
* otherwise, `SESSION` selection MUST use hierarchical lookup
* if no name exists in either flat or session indexes, `ValueError("Unknown resource: <name>")` MUST be raised

### 6.4 Hierarchical `SESSION` lookup

Hierarchical `SESSION` lookup is anchored to `request_path.parent`.

A `SESSION` definition is eligible if:

* it has `origin_dir`
* `request_path.parent` is inside that `origin_dir`

Among eligible candidates, the registry MUST pick the deepest ancestor.

If multiple eligible `SESSION` definitions exist at the same depth, the latest registered definition wins.

If no eligible hierarchical match exists, the registry MUST fall back to the flat definition for that name.

Consequences:

* child tests see the nearest ancestor `SESSION` resource
* sibling branches do not see unrelated child overrides
* mixed-scope clashes still prefer non-`SESSION` resources
* without a request path, `SESSION` lookup falls back to flat latest-registration behavior

### 6.5 Builtin preservation

`mark_builtin(name)` snapshots the currently active resource under `name` into the builtin baseline.

`reset()` MUST:

* clear all non-builtin definitions
* restore builtin flat definitions
* restore builtin `SESSION` indexes

The default singleton registry uses this mechanism for framework-provided resources.

---

## 7. Scope Semantics

### 7.1 General

Scope controls sharing and teardown ownership inside a resolver tree.

The API itself defines resolver-relative semantics. Rue's runner builds on top of those semantics to deliver run-level behavior.

### 7.2 `CASE`

`CASE` resources are owned by the current resolver instance.

They are:

* cached per resolver
* not shared upward to parent resolvers
* torn down by `teardown_scope(Scope.CASE)` or `teardown()`

### 7.3 `SUITE`

`SUITE` resources are flat by name.

Within a resolver family:

* they are owned by the nearest parent owner resolver
* child resolvers reuse the parent's cached value
* teardown is delegated to the owner resolver

### 7.4 `SESSION`

`SESSION` resources are selected hierarchically, then cached by provider identity.

The cache identity includes:

* scope
* resource name
* selected provider directory

This means two same-name `SESSION` resources from different directories MUST produce distinct cached instances.

---

## 8. Resolver Semantics

### 8.1 `resolve(name)`

`resolve(name)` MUST:

* ask the registry to select the active provider using the current request path
* compute a cache key from scope, name, and selected provider directory
* detect circular dependencies
* create or reuse the value according to scope ownership
* apply `on_injection` before returning

### 8.2 Request path source

When used inside Rue execution, the resolver derives `request_path` from the current test context.

If no current test context exists, the resolver passes `None`, which causes `SESSION` selection to use flat fallback behavior.

### 8.3 Dependency resolution

Dependencies are resolved recursively by parameter name.

During dependency resolution, the runtime binds the direct consumer resource name as the current resource consumer context.

This means dependency hooks MAY observe which resource requested them.

### 8.4 `on_resolve`

`on_resolve` runs after the underlying resource value is created and before it is cached.

It therefore runs once per created instance, not once per injection.

### 8.5 `on_injection`

`on_injection` runs on every successful `resolve(name)` return path, including cached values.

It MAY transform the returned value.

### 8.6 `fork_for_case()`

`fork_for_case()` creates a child resolver that:

* shares `SUITE` and `SESSION` cache entries from its parent
* keeps `CASE` scope isolated
* delegates `SUITE` and `SESSION` teardown registration to the correct owner

### 8.7 `resolve_many(names)`

`resolve_many(names)` returns a `dict[str, Any]` keyed by requested resource name.

Resolution order follows the input list order.

---

## 9. Generator and Teardown Semantics

### 9.1 Generator resources

For generator and async-generator resources:

* the first yielded value is the injected value
* the generator instance is retained for teardown

### 9.2 `teardown()`

`teardown()` runs all registered teardowns in reverse registration order.

For generator resources:

* the generator is resumed once to perform finalization
* after generator finalization, `on_teardown` runs, if present

If multiple teardown errors occur, the resolver MAY raise an `ExceptionGroup`.

### 9.3 `teardown_scope(scope)`

`teardown_scope(scope)` tears down only resources matching the specified scope.

It MUST:

* execute matching teardowns in reverse registration order
* remove matching cache entries from the owner resolver
* leave other scopes intact

### 9.4 Post-teardown reuse

Resolvers are not intended for continued reuse after full `teardown()`.

This RFC does not specify post-`teardown()` cache behavior.

---

## 10. Error Semantics

### 10.1 Unknown resource

Resolving an unknown resource MUST raise:

* `ValueError("Unknown resource: <name>")`

### 10.2 Circular dependency

If dependency resolution revisits the same cache key in the active resolution path, the resolver MUST raise a `RuntimeError` describing the cycle.

For hierarchical `SESSION` resources, the cycle label includes the selected provider directory.

### 10.3 Resource body failures

If the underlying resource function raises during creation, that exception propagates.

### 10.4 Hook failures

If `on_resolve`, `on_injection`, or `on_teardown` fails, the resolver MUST wrap the failure in `RuntimeError` naming the hook and resource.

### 10.5 Generator finalization failures

If a generator raises during teardown, the teardown error MUST surface from `teardown()` or `teardown_scope(...)`.

---

## 11. Default Singleton Registry

The default singleton registry is exported as `rue.resources.registry`.

The default decorator `rue.resources.resource(...)` registers into that singleton.

The package import also registers builtin resources into that singleton and marks them builtin so they survive `registry.reset()`.

Builtin resources currently include:

* `captured_output`

`registry.reset()` MUST preserve those builtins.

---

## 12. Recommended Usage

### 12.1 Application and test authoring

Most user code SHOULD use the default decorator:

```python
from rue.resources import resource

@resource(scope="session")
def db():
    return connect()
```

### 12.2 Explicit registry ownership

Framework code, tests, and advanced embedding code SHOULD pass a specific registry object explicitly:

```python
resource_registry = ResourceRegistry()
resolver = ResourceResolver(resource_registry)
```

### 12.3 Hierarchical `SESSION` resources

Directory-scoped `SESSION` overrides SHOULD be defined in files whose source path reflects the intended hierarchy, such as Rue `confrue_*` modules.

The request path used during resolution determines which ancestor `SESSION` provider is active.

---

## 13. Summary of Normative Invariants

The following invariants are required:

* resource names come from function names
* dependency names come from parameters except `self` and `cls`
* resolver construction is explicit and requires a registry
* non-`SESSION` resources win over same-name `SESSION` resources
* `SESSION` selection is nearest-ancestor by request path
* same-name `SESSION` resources from different provider directories do not share cache entries
* `on_resolve` runs once per created instance
* `on_injection` runs on every injection, including cached values
* `on_teardown` runs after generator finalization
* `registry.reset()` restores builtin resources only
