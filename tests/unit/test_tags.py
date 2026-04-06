from rue.testing.decorators.tags import get_tag_data, tag


def test_tag_decorator_records_metadata():
    @tag("slow", "llm")
    @tag.skip(reason="network down")
    @tag.xfail(reason="flaky", strict=True)
    def sample():
        pass

    data = get_tag_data(sample)
    assert data.tags == {"slow", "llm", "skip", "xfail"}
    assert data.skip_reason == "network down"
    assert data.xfail_reason == "flaky"
    assert data.xfail_strict is True
