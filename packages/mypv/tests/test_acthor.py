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

    assert acthor.registers.power == 0
    assert acthor.registers.power_32 == 0
    assert acthor.registers.max_power == 3000
    assert acthor.registers.temperatures == [18.4, 0.0, 0.0, 0.0]
    assert acthor.registers.hot_water_1_temperature_range == (50.0, 60.0)
    assert acthor.registers.room_heating_1.max_temp == 21.0
    assert acthor.registers.room_heating_1.min_temp_day == 5.0
    assert acthor.registers.room_heating_1.min_temp_night == 5.0
    assert acthor.registers.room_heating_2.max_temp == 22.0
    assert acthor.registers.room_heating_2.min_temp_day == 20.0
    assert acthor.registers.room_heating_2.min_temp_night == 20.0
    assert acthor.registers.room_heating_3.max_temp == 22.0
    assert acthor.registers.room_heating_3.min_temp_day == 20.0
    assert acthor.registers.room_heating_3.min_temp_night == 20.0
    assert acthor.registers.status == StatusCode.OFF
    assert acthor.registers.power_timeout.total_seconds() == 90
    assert acthor.registers.boost_mode == BoostMode.ON
    assert acthor.registers.boost_time_1_start == 0
    assert acthor.registers.boost_time_1_stop == 0
    assert acthor.registers.boost_time_2_start == 0
    assert acthor.registers.boost_time_2_stop == 0
    assert acthor.registers.boost_active is False
    assert str(acthor.registers.time) == "00:06:22+01:00"
    assert acthor.registers.night is True
    assert acthor.registers.dst_correction is True
    assert acthor.registers.device_number == 1
    assert acthor.registers.temperature_chip == 24.0
    assert acthor.registers.control_firmware_version == ControlFirmwareVersion(101, 3)
    assert acthor.registers.control_firmware_update_status == UpdateStatus.UP_TO_DATE
    assert acthor.registers.ps_firmware_version == 106
    # Only the first 6 chars are preserved, the rest is redacted.
    assert acthor.registers.serial_number == "2001010000000000"
    assert acthor.registers.legionella.enabled is False
    assert acthor.registers.legionella.temperature == 60.0
    assert acthor.registers.legionella.interval_days == 7
    assert acthor.registers.legionella.start_hour == 20
    assert acthor.registers.stratification_flag is False
    assert acthor.registers.relay_1_status is False
    assert acthor.registers.load_state == (True, False, False)
    assert acthor.registers.load_nominal_power == 1390
    assert acthor.registers.phase_voltages == (238, 0, 0)
    assert acthor.registers.phase_currents == (0.0, 0.0, 0.0)
    assert acthor.registers.output_voltage == 0
    assert acthor.registers.frequency == 49994000000.0
    assert acthor.registers.operation_mode == OperationMode.ROOM_HEATING_1_CIRCUIT
    assert acthor.registers.operation_state == OperationState.HEATING_WITH_PV_EXCESS
    assert acthor.registers.meter_power == 0
    assert acthor.registers.control_type == ControlType.MODBUS_TCP

    # Make sure calling to_dict() doesn't raise an exception
    assert acthor.registers.to_dict()
