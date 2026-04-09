import rue
import rue.testing


def test_public_test_namespace_exists():
    assert hasattr(rue, "test")
    assert hasattr(rue.test, "iterate")
    assert hasattr(rue.test.iterate, "params")
    assert hasattr(rue.test.iterate, "cases")
    assert hasattr(rue.test.iterate, "groups")
    assert hasattr(rue.test, "tag")
    assert hasattr(rue.test.tag, "skip")
    assert hasattr(rue.test.tag, "xfail")
    assert callable(rue.test.tag.inline)


def test_old_public_decorator_exports_are_removed():
    for module in (rue, rue.testing):
        for name in (
            "parametrize",
            "repeat",
            "iter_cases",
            "iter_case_groups",
            "run_inline",
            "tag",
        ):
            assert not hasattr(module, name)
