"""DataUpdateCoordinator for the SMART Technologies integration."""

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import timedelta
from types import MappingProxyType
from typing import Any, override

from smart_serial import (
    CommandRejectedError,
    DeviceIdleError,
    SmartSerialError,
    SmartUX60,
    UnexpectedResponseError,
)
from smart_serial.devices.settings import BoundReadOnlySetting
from smart_serial.devices.ux60 import PowerState

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_DEVICE
from homeassistant.core import CALLBACK_TYPE, HomeAssistant, callback
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers import device_registry as dr, issue_registry as ir
from homeassistant.helpers.debounce import Debouncer
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import (
    DOMAIN,
    INTERVAL_SLACK,
    ISSUE_CANNOT_COMMUNICATE,
    ISSUE_THRESHOLD,
    LOGGER,
    REFRESH_COOLDOWN,
    SLOW_INTERVAL,
    UPDATE_INTERVAL,
)

type SmartTechnologiesConfigEntry = ConfigEntry[SmartTechnologiesCoordinator]
type SettingAccessor = Callable[[SmartUX60], BoundReadOnlySetting[Any]]

KEY_FIRMWARE = "projector_firmware_version"
KEY_MAC_ADDRESS = "mac_address"


@dataclass(frozen=True, kw_only=True)
class TrackedSetting:
    """A library setting that the coordinator keeps up to date."""

    key: str
    accessor: SettingAccessor
    interval: timedelta


@dataclass(frozen=True, kw_only=True)
class SmartTechnologiesData:
    """A snapshot of the projector.

    ``values`` maps a setting key to its parsed value. A key is absent when no enabled
    entity needs it, or when the projector could not give a value (for example a
    VGA-only setting while another input is active). ``None`` is a real value, such as
    a USB port routed to no input.
    """

    power_state: PowerState
    values: Mapping[str, Any]


class SmartTechnologiesCoordinator(DataUpdateCoordinator[SmartTechnologiesData]):
    """Poll a SMART projector over its serial port."""

    config_entry: SmartTechnologiesConfigEntry

    def __init__(
        self, hass: HomeAssistant, config_entry: SmartTechnologiesConfigEntry
    ) -> None:
        """Initialize the coordinator."""
        super().__init__(
            hass,
            LOGGER,
            config_entry=config_entry,
            name=DOMAIN,
            update_interval=UPDATE_INTERVAL,
            # Entities register the settings they need as they are added. Coalesce
            # that burst into one refresh instead of one per entity.
            request_refresh_debouncer=Debouncer(
                hass, LOGGER, cooldown=REFRESH_COOLDOWN, immediate=False
            ),
        )
        assert config_entry.unique_id is not None
        self.serial_number: str = config_entry.unique_id
        self.port: str = config_entry.data[CONF_DEVICE]
        self.device = SmartUX60.create(self.port)

        self._power_state: PowerState | None = None
        self._values: dict[str, Any] = {}
        self._tracked: dict[str, tuple[TrackedSetting, int]] = {}
        self._last_read: dict[str, float] = {}
        self._failures = 0

        # Needed for the device registry entry, whether or not an entity shows them.
        self.async_track_setting(
            TrackedSetting(
                key=KEY_FIRMWARE,
                accessor=lambda device: device.projector_firmware_version,
                interval=SLOW_INTERVAL,
            )
        )
        self.async_track_setting(
            TrackedSetting(
                key=KEY_MAC_ADDRESS,
                accessor=lambda device: device.mac_address,
                interval=SLOW_INTERVAL,
            )
        )

    @property
    def device_info(self) -> DeviceInfo:
        """Return the device registry information for the projector."""
        info = DeviceInfo(
            identifiers={(DOMAIN, self.serial_number)},
            manufacturer=SmartUX60.vendor,
            model=SmartUX60.model,
            name=self.config_entry.title,
            serial_number=self.serial_number,
        )
        if firmware := self._values.get(KEY_FIRMWARE):
            info["sw_version"] = firmware
        if connection := self._mac_connection():
            info["connections"] = {connection}
        return info

    @property
    def tracked_keys(self) -> list[str]:
        """Return the settings currently being polled."""
        return sorted(self._tracked)

    @callback
    def async_track_setting(self, setting: TrackedSetting) -> CALLBACK_TYPE:
        """Keep ``setting`` up to date until the returned callback is called."""
        current, references = self._tracked.get(setting.key, (setting, 0))
        self._tracked[setting.key] = (
            TrackedSetting(
                key=setting.key,
                accessor=current.accessor,
                interval=min(current.interval, setting.interval),
            ),
            references + 1,
        )

        @callback
        def untrack() -> None:
            tracked, count = self._tracked[setting.key]
            if count <= 1:
                del self._tracked[setting.key]
                self._last_read.pop(setting.key, None)
            else:
                self._tracked[setting.key] = (tracked, count - 1)

        return untrack

    @callback
    def async_set_value(self, key: str, value: Any) -> None:
        """Store a value confirmed by the projector after a write."""
        self._values[key] = value
        self._async_publish()

    @callback
    def async_set_power_state(self, power_state: PowerState) -> None:
        """Store a power state reported by the projector after a command."""
        self._power_state = power_state
        self._async_publish()

    async def async_refresh_settings(self) -> None:
        """Re-read every tracked setting on the next update (e.g. after a factory reset)."""
        self._last_read.clear()
        await self.async_request_refresh()

    @override
    async def _async_setup(self) -> None:
        """Open the serial port."""
        try:
            await self.device.connect()
        except SmartSerialError as err:
            raise ConfigEntryNotReady(
                translation_domain=DOMAIN,
                translation_key="cannot_connect",
                translation_placeholders={"port": self.port, "error": str(err)},
            ) from err
        self.config_entry.async_on_unload(self.device.disconnect)
        self.config_entry.async_on_unload(self._async_delete_issue)

    @override
    async def _async_update_data(self) -> SmartTechnologiesData:
        """Read the power state and whichever settings are due."""
        try:
            if not self.device.is_connected:
                await self.device.connect()
            power_state = await self.device.get_power_state()
            if power_state is PowerState.ON:
                if self._power_state is not PowerState.ON:
                    # Settings may have been changed with the remote while the
                    # projector was off or unreachable.
                    self._last_read.clear()
                await self._async_read_due_settings()
        except SmartSerialError as err:
            self._failures += 1
            if self._failures == ISSUE_THRESHOLD:
                self._async_create_issue()
            raise UpdateFailed(
                translation_domain=DOMAIN,
                translation_key="communication_error",
                translation_placeholders={"port": self.port, "error": str(err)},
            ) from err

        self._power_state = power_state
        if self._failures >= ISSUE_THRESHOLD:
            self._async_delete_issue()
        self._failures = 0
        self._async_sync_device_registry()
        return self._snapshot(power_state)

    async def _async_read_due_settings(self) -> None:
        """Read every tracked setting whose polling interval has elapsed."""
        now = self.hass.loop.time()
        for key, (setting, _) in sorted(self._tracked.items()):
            last_read = self._last_read.get(key)
            if (
                last_read is not None
                and now - last_read < setting.interval.total_seconds() - INTERVAL_SLACK
            ):
                continue
            try:
                self._values[key] = await setting.accessor(self.device).get()
            except DeviceIdleError:
                # The projector went idle mid-update: keep what we know and let
                # the next update report the new power state.
                LOGGER.debug("Projector went idle while reading %s", key)
                return
            except (CommandRejectedError, UnexpectedResponseError) as err:
                # Some settings only apply to certain inputs, so a refusal is
                # not an error: the value is simply unknown for now.
                LOGGER.debug("Could not read %s: %s", key, err)
                self._values.pop(key, None)
            self._last_read[key] = now

    def _snapshot(self, power_state: PowerState) -> SmartTechnologiesData:
        return SmartTechnologiesData(
            power_state=power_state, values=MappingProxyType(dict(self._values))
        )

    @callback
    def _async_publish(self) -> None:
        """Push locally known values to the entities without polling."""
        if self._power_state is not None:
            self.async_set_updated_data(self._snapshot(self._power_state))

    def _mac_connection(self) -> tuple[str, str] | None:
        mac = self._values.get(KEY_MAC_ADDRESS)
        if not mac:
            return None
        formatted = dr.format_mac(mac)
        # An unset or malformed address must not become a bogus device connection.
        return (dr.CONNECTION_NETWORK_MAC, formatted) if len(formatted) == 17 else None

    @callback
    def _async_sync_device_registry(self) -> None:
        """Keep the firmware version and MAC address of the device up to date."""
        registry = dr.async_get(self.hass)
        device = registry.async_get_device_by_identifier(
            (DOMAIN, self.serial_number), self.config_entry.entry_id
        )
        if device is None:
            return
        firmware = self._values.get(KEY_FIRMWARE)
        connection = self._mac_connection()
        if firmware and device.sw_version != firmware:
            registry.async_update_device(device.id, sw_version=firmware)
        if connection and connection not in device.connections:
            registry.async_update_device(device.id, new_connections={connection})

    @callback
    def _async_create_issue(self) -> None:
        ir.async_create_issue(
            self.hass,
            DOMAIN,
            f"{ISSUE_CANNOT_COMMUNICATE}_{self.config_entry.entry_id}",
            is_fixable=False,
            severity=ir.IssueSeverity.WARNING,
            translation_key=ISSUE_CANNOT_COMMUNICATE,
            translation_placeholders={
                "title": self.config_entry.title,
                "port": self.port,
            },
        )

    @callback
    def _async_delete_issue(self) -> None:
        ir.async_delete_issue(
            self.hass,
            DOMAIN,
            f"{ISSUE_CANNOT_COMMUNICATE}_{self.config_entry.entry_id}",
        )
