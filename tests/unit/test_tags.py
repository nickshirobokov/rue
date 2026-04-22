import pytest

from rue.testing.decorators import get_tag_data, test as t_decorator


def test_tag_decorator_records_metadata():
    @t_decorator.tag("slow", "llm")
    @t_decorator.tag.skip(reason="network down")
    @t_decorator.tag.xfail(reason="flaky", strict=True)
    def sample():
        pass

    data = get_tag_data(sample)
    assert data.tags == {"slow", "llm", "skip", "xfail"}
    assert data.skip_reason == "network down"
    assert data.xfail_reason == "flaky"
    assert data.xfail_strict is True


def test_inline_tag_is_removed():
    with pytest.raises(AttributeError):
        _ = t_decorator.tag.inline
