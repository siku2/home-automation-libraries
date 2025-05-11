"""Discover my-PV devices on the network."""

import asyncio
import dataclasses
import enum
import logging
import socket
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from ipaddress import IPv4Address
from typing import Any, Protocol, Self

from pymodbus.framer.rtu import FramerRTU

_LOGGER = logging.getLogger(__name__)

_DISCOVERY_PORT = 16124


class DeviceIdentification(enum.IntEnum):
    """Device identification codes."""

    AC_THOR_9S = 0x4F4C
    AC_THOR = 0x4E84
    MY_PV_METER = 0x4E8E
    AC_ELWA_2 = 0x3F16
    AC_ELWA_E = 0x3EFC

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}.{self.name}"

    @property
    def device_name(self) -> str:
        """Device name."""
        return _DEVICE_NAMES[self]


_DEVICE_NAMES = {
    DeviceIdentification.AC_THOR_9S: "AC-THOR 9S",
    DeviceIdentification.AC_THOR: "AC-THOR",
    DeviceIdentification.MY_PV_METER: "my-PV Meter",
    DeviceIdentification.AC_ELWA_2: "AC ELWA 2",
    DeviceIdentification.AC_ELWA_E: "AC ELWA-E",
}


@dataclasses.dataclass(frozen=True, kw_only=True)
class DiscoveryRequest:
    """Discovery request."""

    # Type   | Name
    # u16    | crc
    # u8[16] | name
    # _      | reserved

    device_id: DeviceIdentification
    """Device to scan for."""

    def encode(self) -> bytes:
        """Encode the discovery request to bytes."""

        buf = bytearray(32)
        buf[2:4] = self.device_id.value.to_bytes(2, "big")
        name_bytes = self.device_id.device_name.encode("ascii")
        buf[4 : 4 + len(name_bytes)] = name_bytes

        crc = _crc16(buf[2:])
        buf[0:2] = crc.to_bytes(2, "big")
        return bytes(buf)


@dataclasses.dataclass(frozen=True, kw_only=True)
class DiscoveryReply:
    """Discovery reply."""

    # Type   | Name
    # u16    | crc
    # u16    | identification
    # u8[4]  | ip address
    # u8[16] | serial number
    # u8[2]  | firmware version
    # u8     | elwa number
    # _      | reserved

    device_id: DeviceIdentification
    addr: IPv4Address
    serial_number: str
    firmware_version: str
    elwa_number: int

    @classmethod
    def decode(cls, data: bytes) -> Self:
        if len(data) != 64:
            raise ValueError(
                f"Invalid data length: {len(data)} != 64 for data: {data.hex()}"
            )
        crc = int.from_bytes(data[0:2], "big")
        calculated_crc = _crc16(data[2:])
        if crc != calculated_crc:
            raise ValueError(
                f"Invalid CRC: {crc} != {calculated_crc} for data: {data.hex()}"
            )

        id = int.from_bytes(data[2:4], "big")
        ip = IPv4Address(data[4:8])
        # TODO: handle null
        serial_number = data[8:24].decode("ascii")
        firmware_version = data[24:26].decode("ascii")
        elwa_number = data[26]
        return cls(
            device_id=DeviceIdentification(id),
            addr=ip,
            serial_number=serial_number,
            firmware_version=firmware_version,
            elwa_number=elwa_number,
        )


def _crc16(data: bytes) -> int:
    """Calculate the CRC16 checksum of the given data."""
    # We re-use pymodbus' implemtation so we don't have to maintain our own.
    # It's explicitly stated that mypv uses the Modbus CRC.
    return FramerRTU.compute_CRC(data)


class DiscoveryCallback(Protocol):
    def __call__(self, reply: DiscoveryReply | None) -> None:
        """Callback for discovery replies."""


class _Protocol(asyncio.DatagramProtocol):
    def __init__(self, callback: DiscoveryCallback) -> None:
        self._callback = callback

    def connection_made(self, transport: asyncio.DatagramTransport) -> None:
        req = DiscoveryRequest(
            device_id=DeviceIdentification.AC_THOR,
        )
        _LOGGER.debug("Sending discovery request: %s", req)
        transport.sendto(req.encode(), ("255.255.255.255", _DISCOVERY_PORT))

    def connection_lost(self, exc: Exception | None) -> None:
        _LOGGER.debug("Connection lost: %s", exc)
        # TODO: do we need to ensure this is never called twice?
        self._callback(None)

    def datagram_received(self, data: bytes, addr: tuple[str | Any, int]) -> None:
        try:
            reply = DiscoveryReply.decode(data)
            _LOGGER.debug("Received discovery reply from %s: %s", addr, reply)
        except Exception:
            _LOGGER.debug(
                "Failed to decode discovery reply from %s: %s",
                addr,
                data,
                exc_info=True,
            )
            return

        self._callback(reply)


@asynccontextmanager
async def discover_with_callback(
    callback: DiscoveryCallback,
    *,
    interface: str | None = None,
):
    loop = asyncio.get_event_loop()
    transport, _protocol = await loop.create_datagram_endpoint(
        lambda: _Protocol(callback),
        family=socket.AF_INET,
        proto=socket.IPPROTO_UDP,
        allow_broadcast=True,
        local_addr=(interface, 0) if interface else None,
    )

    try:
        yield
    finally:
        transport.close()


async def discover(
    interface: str | None = None,
    timeout: float = 5.0,
) -> AsyncIterator[DiscoveryReply]:
    queue: asyncio.Queue[DiscoveryReply] = asyncio.Queue()

    def callback(reply: DiscoveryReply | None) -> None:
        if reply is None:
            queue.shutdown()
        else:
            queue.put_nowait(reply)

    loop = asyncio.get_running_loop()
    timeout_handle = loop.call_later(timeout, queue.shutdown)

    try:
        async with discover_with_callback(
            callback,
            interface=interface,
        ):
            try:
                item = await queue.get()
            except asyncio.QueueShutDown:
                return
            yield item
    finally:
        timeout_handle.cancel()


if __name__ == "__main__":

    async def main() -> None:
        logging.basicConfig(level=logging.DEBUG)
        async for reply in discover():
            print(reply)

    asyncio.run(main())
