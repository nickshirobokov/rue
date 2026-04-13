import rue
import pytest

@rue.resource
def some_rue_resource():
    return "some_rue_resource"


@pytest.fixture
def some_pytest_fixture():
    return "some_pytest_fixture"


@rue.test
def test_resources_and_fixtures(some_rue_resource, some_pytest_fixture):
    assert some_rue_resource == "some_rue_resource"
    assert some_pytest_fixture == "some_pytest_fixture"