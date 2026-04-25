import pytest

from memnex import Memnex, MemnexConfig


@pytest.fixture
async def mx():
    client = await Memnex.create(config=MemnexConfig(tenant_id="test_tenant"))
    try:
        yield client
    finally:
        await client.close()


@pytest.fixture
async def mx_isolated(request):
    """Per-test client with a unique tenant id."""
    tenant = f"test_{request.node.name}"
    client = await Memnex.create(config=MemnexConfig(tenant_id=tenant))
    try:
        yield client
    finally:
        await client.close()
