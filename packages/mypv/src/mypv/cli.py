"""Command line interface."""

# We want to use 'print' here.
# ruff: noqa: T201

import argparse
import asyncio
import enum
import importlib.metadata
import ipaddress
import logging
from collections.abc import Callable, Coroutine
from typing import Any, Protocol, cast

import mypv.discovery
from mypv.acthor import Acthor

_VERSION = importlib.metadata.version("mypv")


class Args(Protocol):
    """Command line arguments."""

    verbose: int
    func: Callable[["Args"], Coroutine[None, None, None]]


class ReadArgs(Args):
    """Arguments for the read command."""

    netloc: str
    device_id: int
    dump_registers: bool


def _print_kv(key: str, value: Any, *, indent: str = "") -> None:  # noqa: ANN401
    if isinstance(value, dict):
        print(f"{indent}{key}:")
        for k, v in value.items():  # type: ignore
            assert isinstance(k, str)  # noqa: S101
            _print_kv(k, v, indent=indent + "  ")
        return

    display_value = value.name if isinstance(value, enum.Enum) else value
    print(f"{indent}{key}: {display_value}")


async def read(args: ReadArgs) -> None:
    """Read command."""
    host, _, port = args.netloc.partition(":")
    if not host:
        msg = "Host name or IP address is required."
        raise ValueError(msg)
    if not port:
        port = "502"
    try:
        port = int(port)
    except ValueError:
        msg = f"Invalid port number: {port}"
        raise ValueError(msg) from None

    acthor = await Acthor.connect(
        host=host,
        port=port,
        device_id=args.device_id,
    )
    if args.dump_registers:
        print(f"Raw register values: {acthor.registers[:]}")

    registers = acthor.registers.to_dict()
    for key, value in registers.items():
        _print_kv(key, value)


class DiscoverArgs(Args):
    """Arguments for the discover command."""

    interface: str
    duration: float


async def discover(args: DiscoverArgs) -> None:
    """Discover command."""
    interface = ipaddress.ip_interface(args.interface)
    async for discovery in mypv.discovery.discover(interface=interface, duration=args.duration):
        print(f"{discovery.device_id.name} ({discovery.serial_number})")
        _print_kv("addr", discovery.addr, indent="  ")
        _print_kv("fw_version", discovery.firmware_version, indent="  ")
        _print_kv("elwa_number", discovery.elwa_number, indent="  ")
        _print_kv("device_type", discovery.device_type or "Unknown", indent="  ")
        print()


def main() -> None:
    """Main entry point for the CLI."""
    parser = argparse.ArgumentParser(
        prog="mypv",
        description="Command line interface for myPV devices.",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {_VERSION}",
    )
    verbose_arg = parser.add_argument(
        "-v",
        "--verbose",
        action="count",
        default=0,
        help="Increase verbosity level. Use up to 2 times for debug output.",
    )

    subparsers = parser.add_subparsers(
        title="subcommands",
        description="Available subcommands",
        required=True,
    )

    parser_read = subparsers.add_parser(
        "read",
        help="Read registers from the myPV device.",
    )
    parser_read.set_defaults(func=read)
    parser_read.add_argument(
        "netloc",
        type=str,
        help="Host name or IP address of the myPV device. May include a port number.",
    )
    parser_read.add_argument(
        "--device-id",
        type=int,
        default=1,
        help="Device ID of the myPV device (default: 1).",
    )
    parser_read.add_argument(
        "--dump-registers",
        action="store_true",
        help="Dump all registers to the console.",
    )

    parser_discover = subparsers.add_parser(
        "discover",
        help="Discover myPV devices on the network.",
    )
    parser_discover.set_defaults(func=discover)
    parser_discover.add_argument(
        "--interface",
        type=str,
        default="0.0.0.0/0",
        help="Network interface to use for discovery.",
    )
    parser_discover.add_argument(
        "--duration",
        type=float,
        default=1.0,
        help="Duration for discovery in seconds (default: 1.0).",
    )

    args = cast("Args", parser.parse_args())
    match args.verbose:
        case 0:
            logging.basicConfig(level=logging.WARNING)
        case 1:
            logging.basicConfig(level=logging.INFO)
        case 2:
            logging.basicConfig(level=logging.DEBUG)
        case _:
            msg = "May only be used 0, 1 or 2 times"
            raise argparse.ArgumentError(verbose_arg, msg)

    asyncio.run(args.func(args))
