import itertools
from collections.abc import Iterable, Iterator
from datetime import UTC, datetime, timedelta
from ipaddress import IPv4Address, IPv6Address
from types import TracebackType
from typing import TYPE_CHECKING, Literal, Self, cast

from pymodbus.client import AsyncModbusTcpClient, ModbusBaseClient

from ._features import DeviceFeatures
from ._registers import (
    REG_BOOST_ACTIVATE,
    REG_BOOST_MODE,
    REG_BOOST_TIME_1_START,
    REG_BOOST_TIME_2_START,
    REG_CONTROL_TYPE,
    REG_DEVICE_NUMBER,
    REG_DEVICE_STATE,
    REG_HOT_WATER_MAP,
    REG_LEGIONELLA_INTERVAL,
    REG_MAX_POWER,
    REG_OPERATION_MODE,
    REG_POWER,
    REG_POWER_32_HIGH,
    REG_POWER_TIMEOUT,
    REG_ROOM_HEATING_MAP,
    BoostMode,
    ControlType,
    LegionellaSettings,
    OperationMode,
    Registers,
    RoomHeatingSettings,
)

if TYPE_CHECKING:
    from collections.abc import Awaitable

    from pymodbus.client.mixin import ModbusClientMixin
    from pymodbus.pdu import ModbusPDU


type Host = str | IPv4Address | IPv6Address


class ActhorModbusClient:
    """AC-THOR modbus client.

    The underlying modbus client is not concurrent-safe, so neither is this class.
    In practice this means you shouldn't run multiple methods at the same time.

    Note:
        Most write methods should not be called more than once per day to protect the lifespan of
        the non-volatile memory.

        The write methods also don't automatically update the internal state after writing.
        You should call `update_registers` after writing to ensure the internal state is up to date.
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
        cls,
        client: "ModbusClientMixin[Awaitable[ModbusPDU]]",
        device_id: int = 1,
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
        """Register values.

        This will always be the same instance of the registers object. This allows you to pass it
        around and calling `update_registers` on it will update the values in all references.
        """
        return self._registers

    async def update_registers(self) -> None:
        """Update all the register values."""
        read_count = self._features.readable_registers
        pdu = await self._client.read_holding_registers(
            self._registers.RANGE[0],
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

        This function is safe to call frequently without damaging the non-volatile memory.

        Raises:
            ValueError: If the power is not in the supported range.
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

    async def set_power_timeout(self, power_timeout: timedelta) -> None:
        """Set the power timeout.

        Must be in between 10 seconds and 10 minutes.
        The value is rounded to the nearest second.

        This function should not be called more than once per day to protect the lifespan of the
        non-volatile memory.

        Raises:
            ValueError: If the timeout is not in the supported range.
        """
        power_timeout_rounded = timedelta(seconds=round(power_timeout.total_seconds()))
        if not (_POWER_TIMEOUT_MIN <= power_timeout_rounded <= _POWER_TIMEOUT_MAX):
            msg = f"Timeout must be between {_POWER_TIMEOUT_MIN} and {_POWER_TIMEOUT_MAX}"
            raise ValueError(msg)
        await self._client.write_register(
            REG_POWER_TIMEOUT,
            int(power_timeout_rounded.total_seconds()),
            slave=self._device_id,
        )

    async def set_max_power(self, max_power: int) -> None:
        """Set the max power (W) of the device.

        The power range is different between AC-THOR and AC-THOR 9s devices:
            - AC-THOR: 500-3000 W
            - AC-THOR 9s: 1500-9000 W

        The supported value range can be read from `DeviceFeatures.max_power_range`.

        This function should not be called more than once per day to protect the lifespan of the
        non-volatile memory.

        Raises:
            ValueError: If the power is not in the supported range.
        """
        min_supported, max_supported = self._features.max_power_range
        if not (min_supported <= max_power <= max_supported):
            msg = f"Power must be between {min_supported} and {max_supported}"
            raise ValueError(msg)
        await self._client.write_register(
            REG_MAX_POWER,
            max_power,
            slave=self._device_id,
        )

    async def activate_boost(self) -> None:
        """Activate the boost.

        This function is safe to call frequently without damaging the non-volatile memory.
        """
        # TODO is it possible to disable the boost?
        await self._client.write_register(
            REG_BOOST_ACTIVATE,
            1,
            slave=self._device_id,
        )

    async def set_boost_config(
        self,
        *,
        boost_time_1: tuple[int, int] | None = None,
        boost_time_2: tuple[int, int] | None = None,
        boost_mode: BoostMode | None = None,
    ) -> None:
        """Set the boost configuration.

        All values are optional. If a value is `None`, it will not be written to the device and
        instead left at its current value. Calling this function without any values is a no-op.

        Args:
            boost_time_1: The start, stop hours of the first boost time (0-23, 0-24).
            boost_time_2: The start, stop hours of the second boost time (0-23, 0-24).
            boost_mode: The boost mode to set.

        This function should not be called more than once per day to protect the lifespan of the
        non-volatile memory.

        Raises:
            ValueError: If any of the provided values are outside their respective range.
        """

        async def write_boost_time_config(start_reg: int, start: int, stop: int) -> None:
            if not (0 <= start <= 23):  # noqa: PLR2004
                msg = "boost start time must be between 0 and 23 inclusive"
                raise ValueError(msg)
            if not (0 <= stop <= 24):  # noqa: PLR2004
                msg = "boost stop time must be between 0 and 24 inclusive"
                raise ValueError(msg)
            await self._client.write_registers(start_reg, [start, stop], slave=self._device_id)

        if boost_time_1 is not None:
            await write_boost_time_config(
                REG_BOOST_TIME_1_START,
                start=boost_time_1[0],
                stop=boost_time_1[1],
            )
        if boost_time_2 is not None:
            await write_boost_time_config(
                REG_BOOST_TIME_2_START,
                start=boost_time_2[0],
                stop=boost_time_2[1],
            )

        if boost_mode is not None:
            await self._client.write_register(
                REG_BOOST_MODE,
                boost_mode.value,
                slave=self._device_id,
            )

    async def set_hot_water_config(
        self,
        *,
        min_temp: float | None,
        max_temp: float | None,
        unit: Literal[1, 2, 3] = 1,
    ) -> None:
        """Set the "hot water" temperature range.

        Temperature values are in °C, rounded to one decimal place.
        `None` values will not be written to the device and instead left at their current value.

        This function should not be called more than once per day to protect the lifespan of the
        non-volatile memory.

        Args:
            min_temp: The minimum temperature in °C to set.
            max_temp: The maximum temperature in °C to set.
            unit: The unit to use. All known devices only support unit 1.

        Raises:
            ValueError: If either the min or max temperature value is out of range, or if the unit
                        is not available on the device as determined by the `DeviceFeatures`.
        """
        if unit > self._features.water_heating_units:
            msg = f"Unit {unit} is not available on this device"
            raise ValueError(msg)

        min_reg, max_reg = REG_HOT_WATER_MAP[unit]
        for reg, value in ((max_reg, max_temp), (min_reg, min_temp)):
            if value is None:
                continue
            rounded_value = round(value, 1)
            if not (_HW_TEMP_MIN <= rounded_value <= _HW_TEMP_MAX):
                msg = f"Temperature must be between {_HW_TEMP_MIN} and {_HW_TEMP_MAX}"
                raise ValueError(msg)
            await self._client.write_register(reg, int(rounded_value * 10), slave=self._device_id)

    async def set_room_heating_config(
        self,
        room_heating: RoomHeatingSettings | None = None,
        *,
        max_temp: float | None,
        min_temp_day: float | None,
        min_temp_night: float | None,
        unit: Literal[1, 2, 3],
    ) -> None:
        """Set the room heating temperature range.

        Temperature values are in °C, rounded to one decimal place.

        This function should not be called more than once per day to protect the lifespan of the
        non-volatile memory.

        You can either pass the `room_heating` argument or the individual values through kwargs.
        Using `room_heating` will always write to all registers.
        If both the `room_heating` and kwargs are passed, the kwargs values will take precedence
        (unless the value is None).

        Args:
            room_heating: Room heating configuration to use. kwargs take precedence over this.
            max_temp: The maximum temperature in °C to set.
            min_temp_day: The minimum daytime temperature in °C to set.
            min_temp_night: The minimum nighttime temperature in °C to set.
            unit: The unit to use.
        """
        if room_heating is not None:
            max_temp = room_heating.max_temp if max_temp is None else max_temp
            min_temp_day = room_heating.min_temp_day if min_temp_day is None else min_temp_day
            min_temp_night = (
                room_heating.min_temp_night if min_temp_night is None else min_temp_night
            )

        max_reg, max_day_reg, max_night_reg = REG_ROOM_HEATING_MAP[unit]
        for reg, value in (
            (max_reg, max_temp),
            (max_day_reg, min_temp_day),
            (max_night_reg, min_temp_night),
        ):
            if value is None:
                continue
            rounded_value = round(value, 1)
            await self._client.write_register(reg, int(rounded_value * 10), slave=self._device_id)

    async def set_device_number(self, device_number: int) -> None:
        """Set the device number.

        This function should not be called more than once per day to protect the lifespan of the
        non-volatile memory.
        """
        await self._client.write_register(REG_DEVICE_NUMBER, device_number, slave=self._device_id)

    async def _write_registers_with_holes(
        self,
        start_address: int,
        values: Iterable[int | None],
    ) -> None:
        """Helper function to write a list of consecutive registers maybe containing holes.

        This function will only write non-None values to the device in as few calls as possible.
        """
        for is_none, group_values in itertools.groupby(enumerate(values), lambda x: x[1] is None):
            if is_none:
                continue
            # At this point we know that 'group_values' is a non-empty iterator containing only int
            # values.
            group_values = cast("Iterator[tuple[int, int]]", group_values)
            reg_offset, first_value = next(group_values)
            reg_values = [first_value, *(v for _, v in group_values)]
            await self._client.write_registers(
                start_address + reg_offset,
                values=reg_values,
                slave=self._device_id,
            )

    async def set_legionella_config(
        self,
        settings: LegionellaSettings | None = None,
        *,
        enabled: bool | None = None,
        temperature: int | None = None,
        interval_days: int | None = None,
        start_hour: int | None = None,
    ) -> None:
        """Set the legionella configuration.

        You can either pass the `settings` argument or the individual values through kwargs.
        Using `settings` will always write to all registers.
        If both the `settings` and kwargs are passed, the kwargs values will take precedence
        (unless the value is None).

        This function should not be called more than once per day to protect the lifespan of the
        non-volatile memory.
        """
        if settings is not None:
            enabled = settings.enabled if enabled is None else enabled
            temperature = settings.temperature if temperature is None else temperature
            interval_days = settings.interval_days if interval_days is None else interval_days
            start_hour = settings.start_hour if start_hour is None else start_hour

        # Order must match the register layout!
        values: list[int | None] = [
            interval_days,
            start_hour,
            temperature,
            1 if enabled is True else 0 if enabled is False else None,
        ]
        await self._write_registers_with_holes(REG_LEGIONELLA_INTERVAL, values)

    async def set_operation_mode(self, mode: OperationMode) -> None:
        """Set the operation mode of the device.

        This function should not be called more than once per day to protect the lifespan of the
        non-volatile memory.
        """
        # TODO: the manual lists "since version 204.10", but it's clearly already present in my
        #       devices with 103. How come?
        await self._client.write_register(
            REG_OPERATION_MODE,
            mode.value,
            slave=self._device_id,
        )

    async def set_control_type(self, control_type: ControlType | int) -> None:
        """Set the control type of the device.

        This function should not be called more than once per day to protect the lifespan of the
        non-volatile memory.
        """
        await self._client.write_register(
            REG_CONTROL_TYPE,
            int(control_type),
            slave=self._device_id,
        )

    async def set_device_state(self, state: bool) -> None:  # noqa: FBT001 (since it's unclear what the device state is)
        """Set the device state.

        Not available on `a00101xx` firmware.

        This function should not be called more than once per day to protect the lifespan of the
        non-volatile memory.

        Raises:
            RuntimeError: If the device state register is not available on this device.
        """
        if not self._registers.has_register(Registers.device_state):
            msg = "Device state register not available on this device"
            raise RuntimeError(msg)
        await self._client.write_register(
            REG_DEVICE_STATE,
            int(state),
            slave=self._device_id,
        )


# Values taken from frontend
_HW_TEMP_MIN = 5.0
_HW_TEMP_MAX = 90.0

_POWER_TIMEOUT_MIN = timedelta(seconds=10)
_POWER_TIMEOUT_MAX = timedelta(minutes=10)
