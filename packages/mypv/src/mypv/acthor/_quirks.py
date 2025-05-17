import logging
from typing import TYPE_CHECKING, Self

from ._registers import REG_CONTROL_FW_SUB_VERSION, REG_CONTROL_FW_VERSION, ControlFirmwareVersion

if TYPE_CHECKING:
    from pymodbus.client import ModbusBaseClient

_LOGGER = logging.getLogger(__name__)


class Quirks:
    """Undocumented quirks for specific devices."""

    __slots__ = ("_fw_version",)

    def __init__(self, fw_version: ControlFirmwareVersion) -> None:
        self._fw_version = fw_version

    @classmethod
    async def read(cls, client: "ModbusBaseClient", device_id: int) -> Self:
        _LOGGER.debug("Reading quirks for device %d", device_id)
        pdu = await client.read_holding_registers(
            REG_CONTROL_FW_VERSION,
            count=(REG_CONTROL_FW_SUB_VERSION - REG_CONTROL_FW_VERSION + 1),
            slave=device_id,
        )
        fw_version = ControlFirmwareVersion(
            version=pdu.registers[0],
            sub_version=pdu.registers[REG_CONTROL_FW_SUB_VERSION - REG_CONTROL_FW_VERSION],
        )
        return cls(fw_version=fw_version)

    @property
    def register_count(self) -> int:
        """The number of registers to read.

        The manual states 89 registers (1000-1088), but this doesn't match some devices.
        My devices with FW a0010103 only support 81 registers (1000-1080).
        """
        if self._fw_version.version == 101:  # noqa: PLR2004
            return 81
        return 89
