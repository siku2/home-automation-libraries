import dataclasses
import ipaddress
import xml.etree.ElementTree as ET
from types import TracebackType
from typing import TYPE_CHECKING, Any, Self

from ._acthor import Host

if TYPE_CHECKING:
    from httpx import URL


class ActhorHttpClient:
    """HTTP client for the AC-THOR device.

    Currently only supports the removed XML interface because I don't have access to a device with
    the JSON interface.
    """

    def __init__(self, base_url: "URL | str") -> None:
        try:
            import httpx
        except ImportError as err:
            msg = (
                f"{__package__} was installed without the 'http' extra "
                "(Use `pip install '{__package__}[http]'`)."
            )
            raise RuntimeError(msg) from err

        self._client = httpx.AsyncClient(base_url=base_url)

    @classmethod
    def from_host(cls, host: Host) -> Self:
        """Create a client for the specified host."""
        return cls(f"http://{host}")

    async def __aenter__(self) -> Self:
        await self._client.__aenter__()
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        await self._client.__aexit__(exc_type, exc_value, traceback)

    async def get_setup(self) -> "Setup":
        """Get the setup information from the AC-THOR device.

        Raises:
            HTTPStatusError: If the request to the device fails.
            ValueError: If the response is invalid.
        """
        # TODO: Missing equivalent for JSON version.
        resp = await self._client.get("/setup.xml")
        resp.raise_for_status()
        root = ET.fromstring(resp.content)  # noqa: S314 (We trust the XML returned by the ACTHOR device.)
        return Setup.from_xml(root)


@dataclasses.dataclass(kw_only=True, frozen=True)
class Setup:
    """Setup information of the ACTHOR device."""

    serial_number: str
    """Serial number of the device."""
    mac_address: str
    """MAC address of the device.

    Format: `XX:XX:XX:XX:XX:XX`
    """
    ip_address: ipaddress.IPv4Address | ipaddress.IPv6Address
    """IP address of the device."""

    @classmethod
    def from_xml(cls, root: ET.Element) -> Self:
        """Parse the setup information from the XML response.

        Raises:
            ValueError: If the XML is missing required elements or has invalid data.
        """

        def el_text(root: ET.Element, name: str) -> str:
            el = root.find(name)
            if el is None or el.text is None:
                msg = f"Missing <{name}> element in XML"
                raise ValueError(msg)
            return el.text

        return cls(
            serial_number=el_text(root, "serialno"),
            mac_address=el_text(root, "macadr").replace("-", ":"),
            ip_address=ipaddress.ip_address(el_text(root, "ip")),
        )

    def to_dict(self) -> dict[str, Any]:
        """Convert the setup information to a dictionary."""
        return {
            "serial_number": self.serial_number,
            "mac_address": self.mac_address,
            "ip_address": self.ip_address,
        }
