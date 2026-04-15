"""Example demonstrating concurrency gains with parallel test execution.

Run with different concurrency levels to see the difference:

    # Sequential (default) - ~3 seconds
    rue test examples/test_example_concurrency.py

    # Concurrent with 5 workers - ~1.2 seconds
    rue test examples/test_example_concurrency.py --concurrency 5

    # Unlimited concurrency (capped at 10) - ~0.6 seconds
    rue test examples/test_example_concurrency.py --concurrency 0
"""

import asyncio

import rue


@rue.resource(scope="module")
async def shared_client():
    """Suite-scoped resource shared across concurrent tests."""
    await asyncio.sleep(0.1)  # Simulate connection setup
    yield {"id": "shared-client", "requests": 0}


@rue.test
async def test_slow_api_call_1(shared_client):
    """Simulates a slow API call."""
    await asyncio.sleep(0.5)
    shared_client["requests"] += 1
    assert shared_client["id"] == "shared-client"


@rue.test
async def test_slow_api_call_2(shared_client):
    """Simulates another slow API call."""
    await asyncio.sleep(0.5)
    shared_client["requests"] += 1
    assert shared_client["id"] == "shared-client"


@rue.test
async def test_slow_api_call_3(shared_client):
    """Simulates yet another slow API call."""
    await asyncio.sleep(0.5)
    shared_client["requests"] += 1
    assert shared_client["id"] == "shared-client"


@rue.test
async def test_slow_api_call_4(shared_client):
    """Simulates a fourth slow API call."""
    await asyncio.sleep(0.5)
    shared_client["requests"] += 1
    assert shared_client["id"] == "shared-client"


@rue.test
async def test_slow_api_call_5(shared_client):
    """Simulates a fifth slow API call."""
    await asyncio.sleep(0.5)
    shared_client["requests"] += 1
    assert shared_client["id"] == "shared-client"


@rue.test
async def test_slow_api_call_6(shared_client):
    """Simulates a sixth slow API call."""
    await asyncio.sleep(0.5)
    shared_client["requests"] += 1
    assert shared_client["id"] == "shared-client"


@rue.test.iterate(5)
async def test_slow_api_call_7(shared_client):
    """Simulates a seventh slow API call."""
    await asyncio.sleep(1.5)
    shared_client["requests"] += 1
    assert shared_client["id"] == "shared-client"
