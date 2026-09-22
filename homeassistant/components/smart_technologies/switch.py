"""Switch platform for the SMART Technologies integration."""

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any, override

from smart_serial import SmartUX60
from smart_serial.devices.settings import BoundSetting

from homeassistant.components.switch import SwitchEntity, SwitchEntityDescription
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import UPDATE_INTERVAL
from .coordinator import (
    SmartTechnologiesConfigEntry,
    SmartTechnologiesCoordinator,
    TrackedSetting,
)
from .entity import SmartTechnologiesEntity, SmartTechnologiesEntityDescription

# One command at a time on the serial line.
PARALLEL_UPDATES = 1


@dataclass(frozen=True, kw_only=True)
class SmartSwitchDescription(
    SwitchEntityDescription, SmartTechnologiesEntityDescription
):
    """Describes a switch backed by a library on/off setting."""

    setting: Callable[[SmartUX60], BoundSetting[bool]]


def _configuration(
    key: str,
    setting: Callable[[SmartUX60], BoundSetting[bool]],
    *,
    enabled: bool = False,
    **kwargs: Any,
) -> SmartSwitchDescription:
    return SmartSwitchDescription(
        key=key,
        translation_key=key,
        entity_category=EntityCategory.CONFIG,
        entity_registry_enabled_default=enabled,
        setting=setting,
        **kwargs,
    )


SWITCHES: tuple[SmartSwitchDescription, ...] = (
    SmartSwitchDescription(
        key="video_mute",
        translation_key="video_mute",
        poll_interval=UPDATE_INTERVAL,
        setting=lambda device: device.video_mute,
    ),
    SmartSwitchDescription(
        key="video_freeze",
        translation_key="video_freeze",
        poll_interval=UPDATE_INTERVAL,
        setting=lambda device: device.video_freeze,
    ),
    _configuration(
        "high_brightness", lambda device: device.high_brightness, enabled=True
    ),
    _configuration("auto_signal", lambda device: device.auto_signal),
    _configuration("lamp_reminder", lambda device: device.lamp_reminder),
    _configuration("volume_control", lambda device: device.volume_control),
    _configuration("dhcp", lambda device: device.dhcp),
    _configuration(
        "vga_out_and_network_enabled", lambda device: device.vga_out_and_network_enabled
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: SmartTechnologiesConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the switches."""
    coordinator = entry.runtime_data
    async_add_entities(
        SmartSwitch(coordinator, description) for description in SWITCHES
    )


class SmartSwitch(SmartTechnologiesEntity, SwitchEntity):
    """A switch for an on/off projector setting."""

    entity_description: SmartSwitchDescription

    def __init__(
        self,
        coordinator: SmartTechnologiesCoordinator,
        description: SmartSwitchDescription,
    ) -> None:
        """Initialize the switch."""
        super().__init__(coordinator, description)

    @override
    def _tracked_settings(self) -> Sequence[TrackedSetting]:
        description = self.entity_description
        return (
            TrackedSetting(
                key=description.key,
                accessor=description.setting,
                interval=description.poll_interval,
            ),
        )

    @property
    @override
    def is_on(self) -> bool | None:
        """Return whether the setting is on."""
        value: bool | None = self.coordinator.data.values.get(
            self.entity_description.key
        )
        return value

    @override
    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn the setting on."""
        await self._async_set(True)

    @override
    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn the setting off."""
        await self._async_set(False)

    async def _async_set(self, value: bool) -> None:
        description = self.entity_description
        confirmed = await self._async_command(
            lambda: description.setting(self.coordinator.device).set(value)
        )
        self.coordinator.async_set_value(description.key, confirmed)
