import dataclasses
import ipaddress
import xml.etree.ElementTree as ET
from typing import Self

import httpx


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
        """Create a Setup instance from an XML element.

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


class ActhorHttpClient:
    def __init__(self, base_url: httpx.URL | str) -> None:
        self._client = httpx.AsyncClient(base_url=base_url)

    async def get_setup(self) -> Setup:
        # TODO: Missing equivalent for JSON version.
        resp = await self._client.get("/setup.xml")
        resp.raise_for_status()
        root = ET.fromstring(resp.content)  # noqa: S314 (We trust the XML returned by the ACTHOR device.)
        return Setup.from_xml(root)
