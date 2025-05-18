from ipaddress import IPv4Address
from pathlib import Path

import pytest
from pytest_httpx import HTTPXMock

from mypv.acthor._http import ActhorHttpClient

_DATA_DIR = Path(__file__).parent / "data"


@pytest.mark.asyncio
async def test_setup_xml(httpx_mock: HTTPXMock) -> None:
    base_url = "http://localhost:80"

    httpx_mock.add_response(
        url=f"{base_url}/setup.xml",
        content=(_DATA_DIR / "setup-1.xml").read_bytes(),
    )

    client = ActhorHttpClient(base_url)
    setup = await client.get_setup()
    assert setup.mac_address == "98:6D:35:00:00:00"
    assert setup.ip_address == IPv4Address("10.0.1.1")
