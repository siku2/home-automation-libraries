"""Discover my-PV devices on the network.

Examples:
    >>> import asyncio
    >>> import mypv.discovery
    >>>
    >>> async def main() -> None:
    >>>     async for reply in mypv.discovery.discover():
    >>>         print(f"Found device: {reply}")
    >>>
    >>> asyncio.run(main())
"""

import asyncio
import dataclasses
import enum
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from ipaddress import IPv4Address, IPv4Interface, IPv6Interface
from typing import Any, ClassVar, Protocol, Self

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
        """Return a string representation of the device identification."""
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


class DeviceType(enum.StrEnum):
    """my-PV device type."""

    ACTHOR_9S = "200300"
    ACTHOR = "200100"
    ACTHOR_I = "200103"
    ACTHOR_CH = "200101"
    AC_ELWA_2 = "160150"
    AC_ELWA_2_FOR_AC_ELWA_2 = "160151"
    """Electronic unit without heating element for AC ELWA 2."""
    AC_ELWA_2_FOR_AC_ELWA_E = "160152"
    """Electronic unit without heating element for AC ELWA-E."""
    AC_ELWA_E = "160124"
    AC_ELWA_E_CH = "160140"
    AC_ELWA_E_ECU = "160129"
    """Electronic unit without heating element."""
    AC_ELWA_E_CH_ECU = "160142"
    """Electronic unit without heating element (Switzerland)."""
    SOL_THOR = "140100"

    @classmethod
    def from_serial_number(cls, sn: str) -> Self:
        """Determine the device type from the serial number.

        This is not recommended by my-PV, but they don't provide a better alternative either.

        Raises:
            ValueError: If the serial number is unknown.
        """
        return cls(sn[:6])

    @property
    def is_acthor_9s(self) -> bool:
        """Whether the device is an AC-THOR 9S."""
        return self == self.ACTHOR_9S


@dataclasses.dataclass(frozen=True, kw_only=True)
class DiscoveryRequest:
    """Discovery request.

    Wire format:
        - crc: 2 bytes
        - identification: 2 bytes
        - name: 16 bytes
        - reserved: 14 bytes
    """

    device_id: DeviceIdentification
    """Device to scan for."""

    LENGTH: ClassVar[int] = 32

    def encode(self) -> bytes:
        """Encode the discovery request to bytes."""
        buf = bytearray(self.LENGTH)
        buf[2:4] = self.device_id.value.to_bytes(2, "big")
        name_bytes = self.device_id.device_name.encode("ascii")
        buf[4 : 4 + len(name_bytes)] = name_bytes

        crc = _crc16(bytes(buf[2:]))
        buf[0:2] = crc.to_bytes(2, "little")
        return bytes(buf)

    @classmethod
    def decode(cls, data: bytes) -> Self:
        """Decode a raw discovery request body.

        Raises:
            ValueError: If the data is invalid.
        """
        if len(data) != cls.LENGTH:
            msg = f"Invalid data length: {len(data)} != {cls.LENGTH} for data: {data.hex()}"
            raise ValueError(msg)

        crc = int.from_bytes(data[0:2], "little")
        calculated_crc = _crc16(data[2:])
        if crc != calculated_crc:
            msg = f"Invalid CRC: {crc} != {calculated_crc} for data: {data.hex()}"
            raise ValueError(msg)

        dev_id = int.from_bytes(data[2:4], "big")
        return cls(device_id=DeviceIdentification(dev_id))


@dataclasses.dataclass(frozen=True, kw_only=True)
class DiscoveryReply:
    """Discovery reply.

    Wire format:
        - crc: 2 bytes
        - identification: 2 bytes
        - ip address: 4 bytes
        - serial number: 16 bytes
        - firmware version: 2 bytes
        - elwa number: 1 byte
        - reserved: 35 bytes
    """

    device_id: DeviceIdentification
    addr: IPv4Address
    serial_number: str
    firmware_version: int
    elwa_number: int

    LENGTH: ClassVar[int] = 64

    @property
    def device_type(self) -> DeviceType | None:
        """Device type."""
        try:
            return DeviceType.from_serial_number(self.serial_number)
        except ValueError:
            return None

    def encode(self) -> bytes:
        """Encode the discovery reply to bytes."""
        buf = bytearray(self.LENGTH)
        buf[2:4] = self.device_id.value.to_bytes(2, "big")
        buf[4:8] = self.addr.packed
        buf[8:24] = self.serial_number.encode("ascii").ljust(16, b"\x00")
        buf[24:26] = self.firmware_version.to_bytes(2, "big")
        buf[26] = self.elwa_number
        crc = _crc16(bytes(buf[2:]))
        buf[0:2] = crc.to_bytes(2, "little")
        return bytes(buf)

    @classmethod
    def decode(cls, data: bytes) -> Self:
        """Decode a raw discovery reply body.

        Raises:
            ValueError: If the data is invalid.
        """
        if len(data) != cls.LENGTH:
            msg = f"Invalid data length: {len(data)} != {cls.LENGTH} for data: {data.hex()}"
            raise ValueError(msg)

        crc = int.from_bytes(data[0:2], "little")
        calculated_crc = _crc16(data[2:])
        if crc != calculated_crc:
            msg = f"Invalid CRC: {crc} != {calculated_crc} for data: {data.hex()}"
            raise ValueError(msg)

        dev_id = int.from_bytes(data[2:4], "big")
        ip = IPv4Address(data[4:8])
        serial_number = data[8:24].decode("ascii").rstrip("\x00")
        firmware_version = int.from_bytes(data[24:26], "big")
        elwa_number = data[26]
        return cls(
            device_id=DeviceIdentification(dev_id),
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
    """Callback for discovery replies."""

    def __call__(self, reply: DiscoveryReply | None) -> None:
        """Callback for discovery replies."""


class _Protocol(asyncio.DatagramProtocol):
    def __init__(
        self, interface: IPv4Interface | IPv6Interface, callback: DiscoveryCallback
    ) -> None:
        self._interface = interface
        self._callback: DiscoveryCallback | None = callback

    def connection_made(self, transport: asyncio.DatagramTransport) -> None:
        req = DiscoveryRequest(
            device_id=DeviceIdentification.AC_THOR,
        )
        addr = (str(self._interface.network.broadcast_address), _DISCOVERY_PORT)
        _LOGGER.debug("Sending discovery request to %s: %s", addr, req)
        transport.sendto(req.encode(), addr)

    def connection_lost(self, exc: Exception | None) -> None:
        if exc is not None:
            _LOGGER.debug("Connection lost: %s", exc)
        if cb := self._callback:
            cb(None)
            self._callback = None

    def datagram_received(self, data: bytes, addr: tuple[str | Any, int]) -> None:
        if len(data) == DiscoveryRequest.LENGTH:
            # Ignore requests
            return
        try:
            reply = DiscoveryReply.decode(data)
            _LOGGER.debug("Received discovery reply from %s: %s", addr, reply)
        except ValueError:
            _LOGGER.debug(
                "Failed to decode discovery reply from %s: %s",
                addr,
                data.hex(),
                exc_info=True,
            )
            return

        if cb := self._callback:
            cb(reply)

    def error_received(self, exc: Exception) -> None:
        _LOGGER.debug("Error received: %s", exc)
        if cb := self._callback:
            cb(None)
            self._callback = None


@asynccontextmanager
async def discover_with_callback(
    callback: DiscoveryCallback,
    *,
    interface: IPv4Interface | IPv6Interface | None = None,
) -> AsyncIterator[None]:
    """Discover my-PV devices on the network.

    Returns:
        A context manager, which, when entered, sends a discovery request to
        the network and listens for replies.
        Any valid replies will be passed to the callback function.
        Leaving the context will stop the listener and close the socket.
    """
    if interface is None:
        interface = IPv4Interface("0.0.0.0/0")
    loop = asyncio.get_event_loop()
    transport, _protocol = await loop.create_datagram_endpoint(
        lambda: _Protocol(interface, callback),
        allow_broadcast=True,
        local_addr=(str(interface.ip), _DISCOVERY_PORT),
    )

    try:
        yield
    finally:
        transport.close()


async def discover(
    *,
    interface: IPv4Interface | IPv6Interface | None = None,
    duration: float = 5.0,
) -> AsyncIterator[DiscoveryReply]:
    """Discover my-PV devices on the network.

    Returns:
        An async iterator yielding discovery replies. The iterator will stop after
        `duration` has elapsed.
    """
    queue: asyncio.Queue[DiscoveryReply] = asyncio.Queue()

    def callback(reply: DiscoveryReply | None) -> None:
        if reply is None:
            queue.shutdown()
        else:
            queue.put_nowait(reply)

    loop = asyncio.get_running_loop()
    handle = loop.call_later(duration, queue.shutdown)

    try:
        async with discover_with_callback(
            callback,
            interface=interface,
        ):
            while True:
                try:
                    item = await queue.get()
                except asyncio.QueueShutDown:
                    break
                yield item
    finally:
        handle.cancel()
