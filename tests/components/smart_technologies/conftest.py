"""Common fixtures for the SMART Technologies tests."""

from collections.abc import Generator
import re
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from smart_serial import (
    ConnectionLostError,
    ConnectionNotEstablishedError,
    SerialTimeoutError,
    SmartUX60,
)
from smart_serial.devices.settings import (
    BoolSetting,
    EnumSetting,
    IntSetting,
    IPv4Setting,
    StrSetting,
)

from homeassistant.components.smart_technologies.const import DOMAIN
from homeassistant.const import CONF_DEVICE

from tests.common import MockConfigEntry

MOCK_PORT = "/dev/ttyUSB0"
MOCK_SERIAL_NUMBER = "S123456789"

# Settings that only exist while a suitable input is active (per the command reference).
VGA_ONLY = {"frequency", "tracking"}
VGA_OR_COMPOSITE = {"saturation", "tint", "sharpness"}

_REPLIES = {
    "powerstate": "On",  # served from the power state machine, never read from here
    "serialnum": MOCK_SERIAL_NUMBER,
    "modelnum": "UX60",
    "macaddr": "00:11:22:33:44:55",
    "fwverddp": "1.2.3",
    "fwvernet": "2.3.4",
    "fwvermpu": "3.4.5",
    "fwverecp": "4.5.6",
    "lamphrs": "1234",
    "syshrs": "2345",
    "resolution": "1920x1080",
    "netstatus": "connected",
    "signaldetected": "true",
    "videoinputs": "vga1,hdmi1,hdmi2",
    "input": "hdmi1",
    "usb1source": "disabled",
    "usb2source": "hdmi1",
    "volume": "0",
    "mute": "off",
    "displaymode": "brightroom",
    "brightness": "50",
}


def _default_values() -> dict[str, str]:
    """Return a plausible raw value for every setting the library declares."""
    values: dict[str, str] = {}
    for setting in SmartUX60.settings().values():
        if setting.key in _REPLIES:
            values[setting.key] = _REPLIES[setting.key]
        elif isinstance(setting, IntSetting):
            values[setting.key] = str(setting.bounds.start + len(setting.bounds) // 2)
        elif isinstance(setting, BoolSetting):
            values[setting.key] = "off"
        elif isinstance(setting, EnumSetting):
            values[setting.key] = next(iter(setting.enum)).value
        elif isinstance(setting, StrSetting):
            values[setting.key] = "Test"
        elif isinstance(setting, IPv4Setting):
            values[setting.key] = "192.168.1.10"
        else:  # pragma: no cover
            raise AssertionError(f"no default for {setting.key}")
    return values


class EmulatedProjector:
    """The console of a SMART projector, as it answers on the RS-232 line."""

    def __init__(self) -> None:
        """Initialize a projector that is on and idle-free."""
        self.power = "On"
        self.values = _default_values()
        self.commands: list[str] = []
        self.source_writes: list[tuple[str, str, str]] = []
        self.connections = 0
        self.disconnects = 0
        # Raised by the next exchanges, one per exchange.
        self.faults: list[BaseException] = []
        # Every exchange times out while the projector is unreachable.
        self.offline = False
        # Raised when a transport tries to open the port.
        self.connect_error: BaseException | None = None
        # Drop to standby after this many more commands (None: never).
        self.idle_after: int | None = None

    def handle(self, command: str) -> str:
        """Answer one console command."""
        self.commands.append(command)
        if self.idle_after is not None:
            if self.idle_after <= 0:
                self.power = "Idle"
                self.idle_after = None
            else:
                self.idle_after -= 1
        if command == "get powerstate":
            return f"powerstate={self.power}"
        if command == "on":
            self.power = "On"
            return "powerstate=On"
        if command in ("off now", "off low power"):
            self.power = "Cooling"
            return "powerstate=Cooling"
        if command == "off":
            self.power = "Confirm off" if self.power == "On" else "Cooling"
            return f"powerstate={self.power}"
        if self.power not in ("On", "Confirm off"):
            return f"invalid cmd={command}"
        return self._handle_setting(command)

    def _handle_setting(self, command: str) -> str:
        if command == "set restoredefaults":
            self.values = _default_values()
            return "restoredefaults=done"
        if command.startswith("get "):
            key = command[4:]
            if key not in self.values or self._unavailable(key):
                return f"invalid cmd={command}"
            return f"{key}={self.values[key]}"
        if match := re.fullmatch(
            r"set (?P<key>[a-z0-9]+)(?: (?P<source>\S+))?(?P<sign>[+-])(?P<amount>\d+)",
            command,
        ):
            key = match["key"]
            if key not in self.values:
                return f"invalid cmd={command}"
            change = int(match["amount"]) * (1 if match["sign"] == "+" else -1)
            if match["source"] is None:
                self.values[key] = str(int(self.values[key]) + change)
            return f"{key}={self.values[key]}"
        if match := re.fullmatch(
            r"set (?P<key>[a-z0-9]+)(?: (?P<source>\S+))?=(?P<value>.*)", command
        ):
            key = match["key"]
            if key not in self.values:
                return f"invalid cmd={command}"
            if match["source"] is None:
                self.values[key] = match["value"]
            else:
                self.source_writes.append((key, match["source"], match["value"]))
            return f"{key}={match['value']}"
        return f"invalid cmd={command}"

    def _unavailable(self, key: str) -> bool:
        active = self.values["input"]
        if key in VGA_ONLY:
            return not active.startswith("vga")
        return key in VGA_OR_COMPOSITE and not active.startswith(("vga", "composite"))


class EmulatedTransport:
    """The Transport the library talks to; one per opened serial connection."""

    def __init__(self, projector: EmulatedProjector, port: str) -> None:
        """Initialize a transport that is not yet connected."""
        self._projector = projector
        self._port = port
        self._connected = False

    @property
    def is_connected(self) -> bool:
        """Return whether the port is open."""
        return self._connected

    async def connect(self) -> None:
        """Open the port."""
        if self._projector.connect_error is not None:
            raise self._projector.connect_error
        self._connected = True
        self._projector.connections += 1

    async def disconnect(self) -> None:
        """Close the port."""
        if self._connected:
            self._projector.disconnects += 1
        self._connected = False

    async def exchange(self, command: str) -> str:
        """Send a command and return the reply."""
        if not self._connected:
            raise ConnectionNotEstablishedError(self._port)
        if self._projector.faults:
            fault = self._projector.faults.pop(0)
            if isinstance(fault, ConnectionLostError):
                self._connected = False
            raise fault
        if self._projector.offline:
            raise SerialTimeoutError(self._port, command)
        return f"\r\n{self._projector.handle(command)}\r\n"


@pytest.fixture
def projector() -> EmulatedProjector:
    """Return the emulated projector."""
    return EmulatedProjector()


@pytest.fixture(autouse=True)
def mock_create(projector: EmulatedProjector) -> Generator[MagicMock]:
    """Make every SmartUX60.create() talk to the emulated projector."""

    def create(port: str, settings: Any = None) -> SmartUX60:
        return SmartUX60(EmulatedTransport(projector, port))

    with patch.object(SmartUX60, "create", side_effect=create) as mock:
        yield mock


@pytest.fixture
def mock_setup_entry() -> Generator[AsyncMock]:
    """Override async_setup_entry."""
    with patch(
        "homeassistant.components.smart_technologies.async_setup_entry",
        return_value=True,
    ) as mock_setup_entry:
        yield mock_setup_entry


@pytest.fixture
def mock_config_entry() -> MockConfigEntry:
    """Return the default mocked config entry."""
    return MockConfigEntry(
        domain=DOMAIN,
        title="SMART UX60",
        unique_id=MOCK_SERIAL_NUMBER,
        data={CONF_DEVICE: MOCK_PORT},
    )
