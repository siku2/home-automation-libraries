import dataclasses
import logging
from typing import TYPE_CHECKING, Self

from mypv.discovery import DeviceType

from ._registers import (
    REG_CONTROL_FW_SUB_VERSION,
    REG_CONTROL_FW_VERSION,
    REG_SERIAL_NUMBER_RANGE,
    ControlFirmwareVersion,
    Registers,
)

if TYPE_CHECKING:
    from collections.abc import Awaitable

    from pymodbus.client.mixin import ModbusClientMixin
    from pymodbus.pdu import ModbusPDU

_LOGGER = logging.getLogger(__name__)


@dataclasses.dataclass(kw_only=True, frozen=True)
class DeviceFeatures:
    readable_registers: int
    """Number of readable registers.

    The manual states 89 registers (1000-1088), but this doesn't match some devices.
    My devices with FW a0010103 only support 81 registers (1000-1080).
    """

    temperature_sensors: int
    """Number of available temperature sensors."""
    water_heating_units: int
    """Number of available water heating units."""
    has_load_state_outputs: bool
    """Whether the `Registers.load_state` register supports individual outputs."""
    has_three_phases: bool
    """Whether the device provides values for all three phases."""
    has_max_power_abs: bool
    """Whether the `Registers.max_power_abs` register is available."""
    has_power_outputs: bool
    """Whether the device provides power measurements for the outputs."""
    has_power_with_relays: bool
    """Whether the `Registers.power_with_relays` register is available."""
    has_device_powers: bool
    """Whether the device reports its own power values.

    This includes the following registers:
        - `Registers.device_power_total`
        - `Registers.device_power_solar`
        - `Registers.device_power_grid`
    """
    has_pwm_out: bool
    """Whether the `Registers.pwm_out` register is available."""
    has_meter_power_32: bool
    """Whether the `Registers.meter_power_32` registers are available."""

    @classmethod
    def all(cls) -> Self:
        """All features enabled."""
        return cls(
            readable_registers=Registers.RANGE.stop - Registers.RANGE.start,
            temperature_sensors=8,
            water_heating_units=3,
            has_load_state_outputs=True,
            has_three_phases=True,
            has_max_power_abs=True,
            has_power_outputs=True,
            has_power_with_relays=True,
            has_device_powers=True,
            has_pwm_out=True,
            has_meter_power_32=True,
        )

    @classmethod
    async def read(cls, client: "ModbusClientMixin[Awaitable[ModbusPDU]]", device_id: int) -> Self:
        """Determine the available device features for the given device."""
        _LOGGER.debug("Reading registers to identify device features (device_id=%d)", device_id)
        # The range we're reading contains the following registers:
        # - Control firmware version (including sub-version)
        # - Serial number
        pdu = await client.read_holding_registers(
            REG_CONTROL_FW_VERSION,
            count=(REG_CONTROL_FW_SUB_VERSION - REG_CONTROL_FW_VERSION + 1),
            slave=device_id,
        )
        sn_start = REG_SERIAL_NUMBER_RANGE.start - REG_CONTROL_FW_VERSION
        sn_end = REG_SERIAL_NUMBER_RANGE.stop - REG_CONTROL_FW_VERSION
        serial_number = b"".join(
            reg.to_bytes(2, "big") for reg in pdu.registers[sn_start:sn_end]
        ).decode("ascii")
        try:
            device_type = DeviceType.from_serial_number(serial_number)
        except ValueError:
            _LOGGER.warning(
                "Unable to determine device type from serial number %s. "
                "Assuming it's not a 9S device.",
                serial_number,
            )
            is_9s = False
        else:
            is_9s = device_type.is_acthor_9s

        fw_version = ControlFirmwareVersion(
            version=pdu.registers[0],
            sub_version=pdu.registers[REG_CONTROL_FW_SUB_VERSION - REG_CONTROL_FW_VERSION],
        )
        return cls._build(fw_version=fw_version, is_9s=is_9s)

    @classmethod
    def _build(cls, *, fw_version: ControlFirmwareVersion, is_9s: bool) -> Self:
        readable_registers = Registers.RANGE.stop - Registers.RANGE.start
        if fw_version.version == 101:  # noqa: PLR2004
            # The manual states 89 registers (1000-1088), but this doesn't match some devices.
            # My devices with FW a0010103 only support 81 registers (1000-1080).
            readable_registers = 81

        return cls(
            readable_registers=readable_registers,
            # As per the manual, the last 4 are marked as "not available".
            temperature_sensors=4,
            # As per the manual, HW 2 and 3 are marked as "not available".
            water_heating_units=1,
            has_load_state_outputs=fw_version >= ControlFirmwareVersion(202, 1),
            has_three_phases=is_9s,
            has_max_power_abs=fw_version >= ControlFirmwareVersion(102, 5),
            has_power_outputs=is_9s,
            has_power_with_relays=is_9s,
            has_device_powers=fw_version >= ControlFirmwareVersion(203, 3),
            has_pwm_out=fw_version >= ControlFirmwareVersion(205, 0),
            has_meter_power_32=fw_version >= ControlFirmwareVersion(210, 2),
        )
