import json
from collections.abc import Awaitable
from pathlib import Path

import pytest
from pymodbus.client.mixin import ModbusClientMixin
from pymodbus.pdu import ModbusPDU

from mypv.acthor import (
    Acthor,
    BoostMode,
    ControlFirmwareVersion,
    ControlType,
    OperationMode,
    OperationState,
    StatusCode,
    UpdateStatus,
)

_DATA_DIR = Path(__file__).parent / "data"


class MockModbusClient(ModbusClientMixin[Awaitable[ModbusPDU]]):
    def __init__(self, name: str) -> None:
        super().__init__()
        self._register_bank: list[int] = json.loads((_DATA_DIR / f"{name}.json").read_text())

    async def execute(self, no_response_expected: bool, request: ModbusPDU) -> ModbusPDU:
        assert no_response_expected is False
        assert request.function_code == 0x03
        assert request.dev_id == 1

        start = request.address
        count = request.count
        assert start >= 1000
        start -= 1000
        end = start + count
        assert end <= len(self._register_bank)

        return ModbusPDU(
            dev_id=request.dev_id,
            transaction_id=request.transaction_id,
            address=request.address,
            count=request.count,
            registers=self._register_bank[start:end],
        )


@pytest.mark.asyncio
async def test_registers() -> None:
    client = MockModbusClient("registers-1")
    acthor = await Acthor.from_modbus(client)

    r = acthor.registers
    assert r.power == 0
    assert r.power_32 == 0
    assert r.max_power == 3000
    assert r.temperatures == [18.4, 0.0, 0.0, 0.0]
    assert r.hot_water_1_temperature_range == (50.0, 60.0)
    assert r.room_heating_1.max_temp == 21.0
    assert r.room_heating_1.min_temp_day == 5.0
    assert r.room_heating_1.min_temp_night == 5.0
    assert r.room_heating_2.max_temp == 22.0
    assert r.room_heating_2.min_temp_day == 20.0
    assert r.room_heating_2.min_temp_night == 20.0
    assert r.room_heating_3.max_temp == 22.0
    assert r.room_heating_3.min_temp_day == 20.0
    assert r.room_heating_3.min_temp_night == 20.0
    assert r.status == StatusCode.OFF
    assert r.power_timeout.total_seconds() == 90
    assert r.boost_mode == BoostMode.ON
    assert r.boost_time_1 == (0, 0)
    assert r.boost_time_2 == (0, 0)
    assert r.boost_active is False
    assert str(r.time) == "00:06:22+01:00"
    assert r.night is True
    assert r.dst_correction is True
    assert r.device_number == 1
    assert r.temperature_chip == 24.0
    assert r.control_firmware_version == ControlFirmwareVersion(101, 3)
    assert r.control_firmware_update_status == UpdateStatus.UP_TO_DATE
    assert r.ps_firmware_version == 106
    # Only the first 6 chars are preserved, the rest is redacted.
    assert r.serial_number == "2001010000000000"
    assert r.legionella.enabled is False
    assert r.legionella.temperature == 60.0
    assert r.legionella.interval_days == 7
    assert r.legionella.start_hour == 20
    assert r.stratification_flag is False
    assert r.relay_1_status is False
    assert r.load_state == (True, False, False)
    assert r.load_nominal_power == 1390
    assert r.phase_voltages == (238, 0, 0)
    assert r.phase_currents == (0.0, 0.0, 0.0)
    assert r.output_voltage == 0
    assert r.frequency == 49994000000.0
    assert r.operation_mode == OperationMode.ROOM_HEATING_1_CIRCUIT
    assert r.operation_state == OperationState.HEATING_WITH_PV_EXCESS
    assert r.meter_power == 0
    assert r.control_type == ControlType.MODBUS_TCP

    # Make sure calling to_dict() doesn't raise an exception
    assert r.to_dict()
