from datetime import UTC, datetime
from ipaddress import IPv4Address, IPv6Address
from types import TracebackType
from typing import TYPE_CHECKING, Literal, Self

from pymodbus.client import AsyncModbusTcpClient, ModbusBaseClient

from ._features import DeviceFeatures
from ._registers import REG_HOT_WATER_MAP, REG_POWER, REG_POWER_32_HIGH, Registers

if TYPE_CHECKING:
    from collections.abc import Awaitable

    from pymodbus.client.mixin import ModbusClientMixin
    from pymodbus.pdu import ModbusPDU


type Host = str | IPv4Address | IPv6Address


class Acthor:
    """AC-THOR device client.

    The underlying modbus client is not concurrent-safe, so neither is this class.
    In practice this means you shouldn't run multiple methods at the same time.
    """

    __slots__ = (
        "_client",
        "_device_id",
        "_features",
        "_last_update",
        "_registers",
    )

    def __init__(
        self,
        client: "ModbusClientMixin[Awaitable[ModbusPDU]]",
        *,
        features: DeviceFeatures,
        device_id: int = 1,
    ) -> None:
        """Create a new Acthor instance.

        Only use this constructor if you know what you're doing.
        Prefer using the `connect` class method.
        """
        self._client = client
        self._features = features
        self._device_id = device_id
        self._last_update: datetime | None = None
        self._registers = Registers(features)

    @classmethod
    async def from_modbus(
        cls, client: "ModbusClientMixin[Awaitable[ModbusPDU]]", device_id: int = 1
    ) -> Self:
        """Connect to a device with an existing modbus client.

        This class takes ownership of the client and will close it when done.
        You should not use the client after this call.
        """
        try:
            features = await DeviceFeatures.read(client, device_id=device_id)
            acthor = cls(client, features=features, device_id=device_id)
            await acthor.update_registers()
        except:
            if isinstance(client, ModbusBaseClient):
                client.close()
            raise
        return acthor

    @classmethod
    async def connect(cls, host: Host, *, device_id: int = 1, port: int = 502) -> Self:
        """Connect to a device."""
        client = AsyncModbusTcpClient(
            str(host),
            port=port,
            name="acthor",
        )
        await client.connect()
        return await cls.from_modbus(client, device_id=device_id)

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        if isinstance(self._client, ModbusBaseClient):
            self._client.close()

    @property
    def features(self) -> DeviceFeatures:
        """Device features."""
        return self._features

    @property
    def registers(self) -> Registers:
        """Register values."""
        return self._registers

    async def update_registers(self) -> None:
        """Updates the register values."""
        read_count = self._features.readable_registers
        pdu = await self._client.read_holding_registers(
            self._registers.RANGE.start,
            count=read_count,
            slave=self._device_id,
        )
        if (padding_count := len(self._registers) - read_count) > 0:
            # Pad the registers with zeros
            pdu.registers.extend([0] * padding_count)

        self._registers.set_values(pdu.registers)
        self._last_update = datetime.now(UTC)

    async def set_power(self, power: int) -> None:
        """Set the power (W) of the device.

        This function will automatically switch to the 32-bit power register if necessary.
        """
        if not (0 <= power <= 0xFFFF_FFFF):  # noqa: PLR2004
            msg = "Power must be between 0 and 0xFFFF_FFFF"
            raise ValueError(msg)

        if power > 0xFFFF:  # noqa: PLR2004
            await self._client.write_registers(
                REG_POWER_32_HIGH,
                values=[power >> 16, power & 0xFFFF],
                slave=self._device_id,
            )
        else:
            await self._client.write_register(REG_POWER, power, slave=self._device_id)

    async def set_hot_water_range(
        self,
        *,
        min_temp: float | None,
        max_temp: float | None,
        unit: Literal[1, 2, 3] = 1,
    ) -> None:
        """Set the "hot water" temperature range.

        Temperature values are in degrees Celsius, with one decimal place.
        `None` values will not be written to the device and instead left at their current value.

        HW 2 and HW 3 are marked as "not available" in the data sheet, so they probably don't work.
        The API includes them for completeness.

        This function should not be called more than once per day to protect the lifespan of the
        non-volatile memory.
        """
        min_reg, max_reg = REG_HOT_WATER_MAP[unit]
        for reg, value in ((max_reg, max_temp), (min_reg, min_temp)):
            if value is None:
                continue
            if not (_HW_TEMP_MIN <= value <= _HW_TEMP_MAX):
                msg = f"Temperature must be between {_HW_TEMP_MIN} and {_HW_TEMP_MAX}"
                raise ValueError(msg)
            await self._client.write_register(reg, round(value * 10), slave=self._device_id)


# Values taken from frontend
_HW_TEMP_MIN = 5.0
_HW_TEMP_MAX = 90.0
