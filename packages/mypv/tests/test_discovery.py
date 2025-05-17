from ipaddress import IPv4Address

import pytest

from mypv.discovery import DeviceIdentification, DiscoveryReply, DiscoveryRequest


@pytest.mark.parametrize(
    ("message", "expected"),
    [
        pytest.param(
            DiscoveryRequest(device_id=DeviceIdentification.AC_THOR),
            "cb7a4e8441432d54484f5200000000000000",
            id="request",
        ),
        pytest.param(
            DiscoveryReply(
                device_id=DeviceIdentification.AC_THOR,
                addr=IPv4Address("127.0.0.1"),
                serial_number="hello",
                firmware_version="000a",
                elwa_number=1,
            ),
            "75764e847f00000168656c6c6f0000000000000000000000000a01",
            id="response",
        ),
    ],
)
def test_codec(message: DiscoveryReply | DiscoveryRequest, expected: bytes | str) -> None:
    message_cls = type(message)
    if isinstance(expected, str):
        expected = bytes.fromhex(expected).ljust(message_cls.LENGTH, b"\x00")

    encoded = message.encode()
    assert encoded.hex() == expected.hex()
    decoded = message_cls.decode(encoded)
    assert decoded == message


@pytest.mark.asyncio
async def test_discovery() -> None:
    pass
