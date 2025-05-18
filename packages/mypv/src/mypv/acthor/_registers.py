import dataclasses
import enum
from datetime import time, timedelta, timezone
from typing import TYPE_CHECKING, Any, ClassVar, overload

if TYPE_CHECKING:
    from collections.abc import Callable

    from ._features import DeviceFeatures

REG_CONTROL_FW_VERSION = 1016
REG_CONTROL_FW_SUB_VERSION = 1028
REG_SERIAL_NUMBER_RANGE = (1018, 1025 + 1)
"""Range of registers [start, stop) for the serial number.

This is a half-open range, so the stop value is not included.
"""
REG_POWER = 1000
REG_POWER_32_HIGH = 1078
REG_POWER_TIMEOUT = 1004
REG_BOOST_TIME_1_START = 1007
REG_BOOST_TIME_2_START = 1026
REG_BOOST_MODE = 1005
REG_BOOST_ACTIVATE = 1012
REG_MAX_POWER = 1014
REG_DEVICE_NUMBER = 1013
REG_LEGIONELLA_INTERVAL = 1053
REG_OPERATION_MODE = 1065
REG_CONTROL_TYPE = 1070
REG_DEVICE_STATE = 1081

REG_HOT_WATER_MAP = {
    # unit -> (min_temp, max_temp)
    1: (1006, 1002),
    2: (1039, 1037),
    3: (1040, 1038),
}

REG_ROOM_HEATING_MAP = {
    # unit -> (max_temp, min_temp_day, min_temp_night)
    1: (1041, 1044, 1047),
    2: (1042, 1045, 1048),
    3: (1043, 1046, 1049),
}


class Registers:
    """Modbus registers of the AC-THOR device.

    Some registers are only available on the 9s devices or on specific firmware versions.
    These registers can still be read, but will return 0 unless otherwise specified.
    """

    __slots__ = (
        "_features",
        "_values",
    )

    RANGE: tuple[int, int] = (1000, 1088 + 1)
    """The range of registers [start, stop) that are available.

    This is a half-open range, so the stop value is not included.
    """

    def __init__(self, features: "DeviceFeatures") -> None:
        self._values = [0] * (self.RANGE[1] - self.RANGE[0])
        self._features = features

    def has_register(self, register: property) -> bool:
        """Check if the register is available on this device.

        Examples:
            >>> registers = Registers(DeviceFeatures.all())
            >>> registers.has_register(Registers.meter_power_32)
            True
        """
        try:
            f = _REGISTER_CHECKS[register]
        except KeyError:
            if register not in self.__class__.__dict__.values():
                msg = f"Register {register.__name__} ({register}) is not a valid register."
                raise ValueError(msg) from None
            return True
        else:
            return f(self._features)

    def to_dict(self) -> dict[str, Any]:
        """Convert registers to a dictionary.

        This will only include registers available on the device.
        """

        def v(x: Any) -> Any:  # noqa: ANN401
            if hasattr(x, "to_dict") and callable(x.to_dict):
                return x.to_dict()
            return x

        return {
            key: v(prop.__get__(self))
            for key, prop in self.__class__.__dict__.items()
            if isinstance(prop, property) and self.has_register(prop)
        }

    def __len__(self) -> int:
        """Return the number of registers."""
        return len(self._values)

    def __str__(self) -> str:
        """String representation of all the registers."""
        kv = (f"{key}={value!r}" for key, value in self.to_dict().items())
        return f"{self.__class__.__name__}({', '.join(kv)})"

    @overload
    def __getitem__(self, address: int) -> int: ...
    @overload
    def __getitem__(self, address: "slice[int | None, int | None, int | None]") -> list[int]: ...

    def __getitem__(
        self, address: "int | slice[int | None, int | None, int | None]"
    ) -> int | list[int]:
        """Get the value of a register by its address."""
        range_start, range_stop = self.RANGE
        if isinstance(address, slice):
            if address.start is None:
                start = None
            elif range_start <= address.start < range_stop:
                start = address.start - range_start
            else:
                msg = f"Register slice start {address.start} out of range."
                raise IndexError(msg)

            if address.stop is None:
                stop = None
            elif range_start <= address.stop:
                stop = address.stop - range_start
            else:
                msg = f"Register slice stop {address.stop} out of range."
                raise IndexError(msg)

            return self._values[start : stop : address.step]

        if not (range_start <= address < range_stop):
            msg = f"Register {address} out of range."
            raise IndexError(msg)
        return self._values[address - range_start]

    def set_values(self, values: list[int]) -> None:
        """Update the register values."""
        if len(values) != len(self._values):
            msg = f"Expected {len(self._values)} values, got {len(values)}"
            raise ValueError(msg)
        self._values = values

    @property
    def power(self) -> int:
        """Power in W.

        In Multi-Mode this is the power sum of all devices. The value range can then also be larger
        depending on the number of devices.
        """
        return self._values[0]

    @property
    def power_32(self) -> int:
        """32-bit power in W.

        Only for large systems with several units (multi-mode) and output specifications greater
        than 65,535 watts.
        Smaller values can be read through `power`.
        """
        # TODO: can we always read from this for power??
        return self._values[78] << 16 | self._values[79]

    @property
    def power_with_relays(self) -> "PowerStage":
        """Power including the relays in W.

        Only available on 9s devices.
        """
        return PowerStage(self._values[80])

    @property
    def device_power_total(self) -> int:
        """Power of the queried device in W.

        Only available after firmware version `a0020303`.


        This is the same value as `device_power_solar + device_power_grid`.
        """
        return self._values[82]

    @property
    def device_power_solar(self) -> int:
        """Solar part of the device power in W.

        Only available after firmware version `a0020303`.
        """
        return self._values[83]

    @property
    def device_power_grid(self) -> int:
        """Grid part of the device power in W.

        Only available after firmware version `a0020303`.
        """
        return self._values[84]

    @property
    def max_power(self) -> int:
        """Max power in W."""
        return self._values[14]

    @property
    def max_power_abs(self) -> int:
        """Max power currently possible in W.

        Includes the power of all subdevices.
        """
        return self._values[71]

    @property
    def temperatures(self) -> list[float]:
        """Temperatures of the available sensors in °C.

        Only the available temperature sensors will be returned as determined by the device
        features.
        As such, the length of the list may vary by device, but will remain stable for each
        subsequent call.
        Note that this doesn't take into account whether a temperature sensor is actually connected.
        It's only about what the hardware supports.
        """
        registers = [self._values[1], *self._values[30:37]]
        registers = registers[: self._features.temperature_sensors]
        return [reg / 10 for reg in registers]

    @property
    def hot_water_1_temperature_range(self) -> tuple[float, float]:
        """Hot water 1 max temperature range in °C.

        This is a tuple (min, max) of the hot water temperature range.
        """
        return (
            self._values[6] / 10,
            self._values[2] / 10,
        )

    @property
    def hot_water_2_temperature_range(self) -> tuple[float, float]:
        """Hot water 2 max temperature range in °C.

        Marked as "not available" in the data sheet, but included here for completeness.

        This is a tuple (min, max) of the hot water temperature range.
        """
        return self._values[39] / 10, self._values[37] / 10

    @property
    def hot_water_3_temperature_range(self) -> tuple[float, float]:
        """Hot water 3 max temperature range in °C.

        Marked as "not available" in the data sheet, but included here for completeness.

        This is a tuple (min, max) of the hot water temperature range.
        """
        return self._values[40] / 10, self._values[38] / 10

    @property
    def room_heating_1(self) -> "RoomHeatingSettings":
        """Room heating 1 settings."""
        return RoomHeatingSettings(
            max_temp=self._values[41] / 10,
            min_temp_day=self._values[44] / 10,
            min_temp_night=self._values[47] / 10,
        )

    @property
    def room_heating_2(self) -> "RoomHeatingSettings":
        """Room heating 2 settings."""
        return RoomHeatingSettings(
            max_temp=self._values[42] / 10,
            min_temp_day=self._values[45] / 10,
            min_temp_night=self._values[48] / 10,
        )

    @property
    def room_heating_3(self) -> "RoomHeatingSettings":
        """Room heating 3 settings."""
        return RoomHeatingSettings(
            max_temp=self._values[43] / 10,
            min_temp_day=self._values[46] / 10,
            min_temp_night=self._values[49] / 10,
        )

    @property
    def status(self) -> "StatusCode":
        """Status code."""
        return StatusCode(self._values[3])

    @property
    def power_timeout(self) -> timedelta:
        """Power timeout."""
        return timedelta(seconds=self._values[4])

    @property
    def boost_mode(self) -> "BoostMode":
        """Boost mode."""
        return BoostMode(self._values[5])

    @property
    def boost_time_1(self) -> tuple[int, int]:
        """Boost time 1 start, stop hours (0-23, 0-24)."""
        return self._values[7], self._values[8]

    @property
    def boost_time_2(self) -> tuple[int, int]:
        """Boost time 2 start, stop hours (0-23, 0-24)."""
        return self._values[26], self._values[27]

    @property
    def boost_active(self) -> bool:
        """Whether the boost is active."""
        return bool(self._values[12])

    @property
    def time(self) -> time:
        """Time."""
        tzinfo = _UTC_CORRECTION[self._values[51]]
        return time(
            hour=self._values[9],
            minute=self._values[10],
            second=self._values[11],
            tzinfo=tzinfo,
        )

    @property
    def night(self) -> bool:
        """Whether the night mode is active."""
        return bool(self._values[50])

    @property
    def dst_correction(self) -> bool:
        """Whether DST is active."""
        return bool(self._values[52])

    @property
    def device_number(self) -> int:
        """The number of this AC THOR device."""
        return self._values[13]

    @property
    def temperature_chip(self) -> float:
        """Temperature chip temperature in °C."""
        return self._values[15] / 10

    @property
    def control_firmware_version(self) -> "ControlFirmwareVersion":
        """Control firmware version."""
        return ControlFirmwareVersion(version=self._values[16], sub_version=self._values[28])

    @property
    def control_firmware_update_status(self) -> "UpdateStatus":
        """The control firmware update status."""
        return UpdateStatus(self._values[29])

    @property
    def ps_firmware_version(self) -> int:
        """PS firmware version."""
        return self._values[17]

    @property
    def serial_number(self) -> str:
        """Serial number."""
        return b"".join(reg.to_bytes(2, "big") for reg in self._values[18:26]).decode("ascii")

    @property
    def legionella(self) -> "LegionellaSettings":
        """Legionella settings."""
        return LegionellaSettings(
            interval_days=self._values[53],
            start_hour=self._values[54],
            temperature=self._values[55],
            enabled=bool(self._values[56]),
        )

    @property
    def stratification_flag(self) -> bool:
        """Stratification flag."""
        return bool(self._values[57])

    @property
    def relay_1_status(self) -> bool:
        """Whether the relay 1 is active."""
        return bool(self._values[58])

    @property
    def load_state(self) -> tuple[bool, bool, bool]:
        """Load state of the outputs.

        The second and third values are only available on 9s devices.
        """
        value = self._values[59]
        return (
            bool(value & 0b001),
            bool(value & 0b010),
            bool(value & 0b100),
        )

    @property
    def load_nominal_power(self) -> int:
        """Nominal power of the load in W."""
        return self._values[60]

    @property
    def phase_voltages(self) -> tuple[int, int, int]:
        """Voltages of the three phases in V.

        Phase 2 and 3 are only available on 9s devices.
        """
        return (
            self._values[61],
            self._values[67],
            self._values[72],
        )

    @property
    def phase_currents(self) -> tuple[float, float, float]:
        """Currents of the three phases in A.

        Phase 2 and 3 are only available on 9s devices.
        """
        return (
            self._values[62] / 10,
            self._values[68] / 10,
            self._values[73] / 10,
        )

    @property
    def output_voltage(self) -> int:
        """Output voltage in V."""
        return self._values[63]

    @property
    def output_powers(self) -> tuple[int, int, int]:
        """Output powers of the three phases in W.

        This is only available on 9s devices.
        """
        return (
            self._values[74],
            self._values[75],
            self._values[76],
        )

    @property
    def frequency(self) -> float:
        """Frequency in Hz."""
        # Register stores in mHz
        return self._values[64] * 1e6

    @property
    def operation_mode(self) -> "OperationMode":
        """Operation mode."""
        return OperationMode(self._values[65])

    @property
    def operation_state(self) -> "OperationState":
        """Operation state."""
        return OperationState(self._values[77])

    @property
    def meter_power(self) -> int:
        """Meter power in W.

        Negative values indicate a feed-in.
        """
        return self._values[69]

    @property
    def meter_power_32(self) -> int:
        """32-bit meter power in W.

        Negative values indicate a feed-in.

        Only available since firmware version `a0021002`.
        """
        return self._values[87] << 16 | self._values[88]

    @property
    def control_type(self) -> "ControlType | int":
        """Control type.

        If the control type is unknown, the value is returned as an int.
        """
        value = self._values[70]
        try:
            return ControlType(value)
        except ValueError:
            return value

    @property
    def device_state(self) -> bool:
        """Device state.

        Not available on `a00101xx` firmware.
        """
        return bool(self._values[81])

    @property
    def pwm_out(self) -> int:
        """PWM output in % (0-100).

        Only available after firmware version `a0020500`.
        """
        return self._values[85]


_REGISTER_CHECKS: "dict[property, Callable[[DeviceFeatures], bool]]" = {
    Registers.hot_water_2_temperature_range: lambda f: f.water_heating_units >= 2,  # noqa: PLR2004
    Registers.hot_water_3_temperature_range: lambda f: f.water_heating_units >= 3,  # noqa: PLR2004
    Registers.max_power_abs: lambda f: f.has_max_power_abs,
    Registers.output_powers: lambda f: f.has_power_outputs,
    Registers.power_with_relays: lambda f: f.has_power_with_relays,
    Registers.device_state: lambda f: f.readable_registers >= 82,  # noqa: PLR2004
    Registers.device_power_total: lambda f: f.has_device_powers,
    Registers.device_power_solar: lambda f: f.has_device_powers,
    Registers.device_power_grid: lambda f: f.has_device_powers,
    Registers.pwm_out: lambda f: f.has_pwm_out,
    Registers.meter_power_32: lambda f: f.has_meter_power_32,
}


@dataclasses.dataclass(kw_only=True, frozen=True)
class RoomHeatingSettings:
    """Room heating settings."""

    max_temp: float
    """Max temperature for room heating."""
    min_temp_day: float
    """Min temperature during the day."""
    min_temp_night: float
    """Min temperature during the night."""

    def to_dict(self) -> dict[str, Any]:
        """Convert room heating settings to a dictionary."""
        return dataclasses.asdict(self)


@dataclasses.dataclass(kw_only=True, frozen=True)
class LegionellaSettings:
    """Legionella settings."""

    enabled: bool
    """Whether legionella mode is enabled."""
    temperature: int
    """Legionella temperature in °C.

    Unlike most temperatures, the resolution here is only 1 °C.
    """
    interval_days: int
    """Interval in days."""
    start_hour: int
    """Start hour (0-23)."""

    def to_dict(self) -> dict[str, Any]:
        """Convert legionella settings to a dictionary."""
        return dataclasses.asdict(self)


class UpdateStatus(enum.IntEnum):
    """Update status returned by `Registers.update_status`."""

    UP_TO_DATE = 0
    """No new AFW available."""
    UPDATE_AVAILABLE = 1
    """New AFW available (download not started)"""
    DOWNLOAD_INI = 2
    """Download started (ini-file download)"""
    DOWNLOAD_BIN = 3
    """Download started (afw.bin-file download)"""
    DOWNLOAD_OTHER_FILES = 4
    """Downloading other files"""
    DOWNLOAD_INTERRUPT = 5
    """Download interrupted"""
    WAITING_FOR_INSTALLATION = 10
    """Download finished, waiting for installation"""

    @property
    def downloading(self) -> bool:
        """Whether the device is currently downloading an update."""
        return self in (
            UpdateStatus.DOWNLOAD_INI,
            UpdateStatus.DOWNLOAD_BIN,
            UpdateStatus.DOWNLOAD_OTHER_FILES,
        )

    @property
    def update_in_progress(self) -> bool:
        """Whether the device is currently updating."""
        return self.downloading or self in (UpdateStatus.WAITING_FOR_INSTALLATION,)


class BoostMode(enum.IntEnum):
    OFF = 0
    ON = 1
    RELAY_BOOST_ON = 3


class StatusCodeCategory(enum.IntEnum):
    OFF = 0
    START_UP = 1
    OPERATION = 9
    ERROR = 200


class StatusCode(int):
    OFF: ClassVar["StatusCode"]

    def __repr__(self) -> str:
        """Return a string representation of the status code."""
        return f"{self.__class__.__name__}({int(self)})"

    def __str__(self) -> str:
        """Return a string representation of the status code."""
        return f"{self.category.name} ({int(self)})"

    @property
    def category(self) -> StatusCodeCategory:
        """Get the status code category."""
        if self >= StatusCodeCategory.ERROR:
            return StatusCodeCategory.ERROR
        if self >= StatusCodeCategory.OPERATION:
            return StatusCodeCategory.OPERATION
        if self >= StatusCodeCategory.START_UP:
            return StatusCodeCategory.START_UP
        # 0 or negative
        return StatusCodeCategory.OFF


StatusCode.OFF = StatusCode(0)


class OperationMode(enum.IntEnum):
    WATER_HEATING_3KW = 1
    WATER_HEATING_STRATIFIED = 2
    WATER_HEATING_6KW = 3
    WATER_HEATING_HEAT_PUMP = 4
    WATER_HEATING_ROOM_HEATING = 5
    ROOM_HEATING_1_CIRCUIT = 6
    WATER_HEATING_PWM = 7
    FREQUENCY_MODE = 8


class PowerStageOutput(enum.IntEnum):
    OFF = 0
    OUT_1 = 1
    OUT_2 = 2
    OUT_3 = 3


class PowerStage(int):
    def to_dict(self) -> dict[str, Any]:
        """Convert power stage to a dictionary."""
        return {
            "relay_out_2": self.relay_out_2,
            "relay_out_3": self.relay_out_3,
            "power_stage": self.output.name,
            "power_stage_power": self.power,
        }

    def __repr__(self) -> str:
        """Return a string representation of the power stage."""
        return f"{self.__class__.__name__}({int(self)})"

    def __str__(self) -> str:
        kv = (f"{key}={value!r}" for key, value in self.to_dict().items())
        return f"{self.__class__.__name__}({', '.join(kv)})"

    @property
    def relay_out_2(self) -> bool:
        """Whether relay output 2 is active."""
        # bit 14
        return bool(self & (1 << 14))

    @property
    def relay_out_3(self) -> bool:
        """Whether relay output 3 is active."""
        # bit 15
        return bool(self & (1 << 15))

    @property
    def output(self) -> PowerStageOutput:
        """Power stage output."""
        # bits 13 and 12
        return PowerStageOutput((self & (0b11 << 12)) >> 12)

    @property
    def power(self) -> int:
        """Power stage output power in W."""
        # bits 11 - 0
        return self & 0b111111111111


class OperationState(enum.IntEnum):
    STANDBY = 0
    """Stand-by, waiting for excess.

    Screen icon: Green tick flashes.
    """
    HEATING_WITH_PV_EXCESS = 1
    """Heating with excess PV power.

    Screen icon: Yellow wave is on.
    """
    BOOST_BACKUP_MODE = 2
    """Boost backup mode.

    Screen icon: Yellow wave flashes.
    """
    TEMPERATURE_SETPOINT_REACHED = 3
    """Temperature setpoint reached.

    Screen icon: Green tick in front of yellow wave.
    """
    NO_CONTROL_SIGNAL = 4
    """No control signal.

    Screen icon: Red cross.
    """
    RED_CROSS_FLASHES = 5
    """This state is unknown as it is not documented in the data sheet."""


@dataclasses.dataclass(frozen=True, order=True)
class ControlFirmwareVersion:
    version: int
    sub_version: int

    def __str__(self) -> str:
        return f"a{self.version:05}{self.sub_version:02}"


class ControlType(enum.IntEnum):
    HTTP = 1
    MODBUS_TCP = 2
    FRONIUS_AUTO = 3
    FRONIUS_MANUAL = 4
    SMA_HOME_MANAGER = 5
    STECA_AUTO = 6
    VARTA_AUTO = 7
    VARTA_MANUAL = 8
    MY_PV_POWER_METER_AUTO = 9
    MY_PV_POWER_METER_MANUAL = 10
    MY_PV_POWER_METER_DIRECT = 11
    MODBUS_RTU = 12
    SLAVE = 13
    RCT_POWER_MANUAL = 14
    ADJUSTABLE_MODBUS_TCP = 15
    SMA_DIRECT_METER_COMMUNICATION_AUTO = 17
    SMA_DIRECT_METER_COMMUNICATION_MANUAL = 18
    DIRECT_METER_P1 = 19
    FREQUENCY = 20
    FRONIUS_SUNSPEC_MANUAL = 100
    KACO_TL1_TL3_MANUAL = 101
    KOSTAL_PIKO_IQ_PLENTICORE_PLUS_MANUAL = 102
    KOSTAL_SMART_ENERGY_METER_MANUAL = 103
    MEC_ELECTRONICS_MANUAL = 104
    SOLAREDGE_MANUAL = 105
    VICTRON_1PH_MANUAL = 106
    VICTRON_3PH_MANUAL = 107
    HUAWEI_MANUAL = 108
    CARLO_GAVAZZI_EM24_MANUAL = 109
    SUNGROW_MANUAL = 111
    FRONIUS_GEN24_MANUAL = 112
    GOOD_WE_MANUAL = 113
    HUAWEI_MODBUS_RTU = 200
    GROWATT_MODBUS_RTU = 201
    SOLAX_MODBUS_RTU = 202
    QCELLS_MODBUS_RTU = 203
    IME_CONTO_D4_MODBUS_RTU = 204


# Table reconstructed from the frontend code.
_UTC_CORRECTION: list[timezone] = [
    timezone(timedelta(hours=-11), "SST"),
    timezone(timedelta(hours=-10), "HST"),
    timezone(timedelta(hours=-9, minutes=-30), "MART"),
    timezone(timedelta(hours=-9), "HADT"),
    timezone(timedelta(hours=-8), "AKDT"),
    timezone(timedelta(hours=-7), "PDT"),
    timezone(timedelta(hours=-6), "CST"),
    timezone(timedelta(hours=-5), "EST"),
    timezone(timedelta(hours=-4, minutes=-30), "VET"),
    timezone(timedelta(hours=-4), "AST"),
    timezone(timedelta(hours=-3), "BRT"),
    timezone(timedelta(hours=-2, minutes=-30), "NDT"),
    timezone(timedelta(hours=-2), "WGST"),
    timezone(timedelta(hours=-1), "CVT"),
    timezone(timedelta(hours=0), "GMT"),
    timezone(timedelta(hours=1), "CET"),
    timezone(timedelta(hours=2), "CAT"),
    timezone(timedelta(hours=3), "EAT"),
    timezone(timedelta(hours=4), "GST"),
    timezone(timedelta(hours=4, minutes=30), "AFT"),
    timezone(timedelta(hours=5), "MAWT"),
    timezone(timedelta(hours=5, minutes=30), "IST"),
    timezone(timedelta(hours=5, minutes=45), "NPT"),
    timezone(timedelta(hours=6), "VOST"),
    timezone(timedelta(hours=6, minutes=30), "MMT"),
    timezone(timedelta(hours=7), "DAVT"),
    timezone(timedelta(hours=8), "WST"),
    timezone(timedelta(hours=8, minutes=45), "CWST"),
    timezone(timedelta(hours=9), "TLT"),
    timezone(timedelta(hours=9, minutes=30), "CST"),
    timezone(timedelta(hours=10), "DDUT"),
    timezone(timedelta(hours=10, minutes=30), "LHST"),
    timezone(timedelta(hours=11), "MIST"),
    timezone(timedelta(hours=11, minutes=30), "NFT"),
    timezone(timedelta(hours=12), "NZST"),
    timezone(timedelta(hours=12, minutes=45), "CHAST"),
    timezone(timedelta(hours=13), "WST"),
    timezone(timedelta(hours=14), "LINT"),
]
