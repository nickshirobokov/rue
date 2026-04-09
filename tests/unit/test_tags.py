from rue.testing.decorators import get_tag_data, test


def test_tag_decorator_records_metadata():
    @test.tag("slow", "llm")
    @test.tag.skip(reason="network down")
    @test.tag.xfail(reason="flaky", strict=True)
    @test.tag.inline
    def sample():
        pass

    data = get_tag_data(sample)
    assert data.tags == {"slow", "llm", "skip", "xfail", "inline"}
    assert data.skip_reason == "network down"
    assert data.xfail_reason == "flaky"
    assert data.xfail_strict is True
    assert data.inline is True
