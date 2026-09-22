"""Text platform for the SMART Technologies integration."""

from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from ipaddress import IPv4Address
from typing import Any, override

from smart_serial import SmartUX60
from smart_serial.devices.settings import BoundReadOnlySetting

from homeassistant.components.text import TextEntity, TextEntityDescription, TextMode
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import (
    SmartTechnologiesConfigEntry,
    SmartTechnologiesCoordinator,
    TrackedSetting,
)
from .entity import SmartTechnologiesEntity, SmartTechnologiesEntityDescription

# One command at a time on the serial line.
PARALLEL_UPDATES = 1

IPV4_PATTERN = r"^(\d{1,3}\.){3}\d{1,3}$"


@dataclass(frozen=True, kw_only=True)
class SmartTextDescription(TextEntityDescription, SmartTechnologiesEntityDescription):
    """Describes a text entity for a string or IP address setting."""

    setting: Callable[[SmartUX60], BoundReadOnlySetting[Any]]
    set_fn: Callable[[SmartUX60, str], Awaitable[Any]]


def _max_length(length: int | None) -> int:
    """Return the length limit of a library string setting."""
    assert length is not None
    return length


def _name(
    key: str,
    setting: Callable[[SmartUX60], BoundReadOnlySetting[Any]],
    set_fn: Callable[[SmartUX60, str], Awaitable[Any]],
    max_length: int | None,
) -> SmartTextDescription:
    return SmartTextDescription(
        key=key,
        translation_key=key,
        entity_category=EntityCategory.CONFIG,
        entity_registry_enabled_default=False,
        mode=TextMode.TEXT,
        native_max=_max_length(max_length),
        setting=setting,
        set_fn=set_fn,
    )


def _address(
    key: str,
    setting: Callable[[SmartUX60], BoundReadOnlySetting[Any]],
    set_fn: Callable[[SmartUX60, str], Awaitable[Any]],
) -> SmartTextDescription:
    return SmartTextDescription(
        key=key,
        translation_key=key,
        entity_category=EntityCategory.CONFIG,
        entity_registry_enabled_default=False,
        mode=TextMode.TEXT,
        native_min=7,
        native_max=15,
        pattern=IPV4_PATTERN,
        setting=setting,
        set_fn=set_fn,
    )


TEXTS: tuple[SmartTextDescription, ...] = (
    _name(
        "group_name",
        lambda device: device.group_name,
        lambda device, value: device.group_name.set(value),
        SmartUX60.group_name.max_length,
    ),
    _name(
        "projector_name",
        lambda device: device.projector_name,
        lambda device, value: device.projector_name.set(value),
        SmartUX60.projector_name.max_length,
    ),
    _name(
        "location_info",
        lambda device: device.location_info,
        lambda device, value: device.location_info.set(value),
        SmartUX60.location_info.max_length,
    ),
    _name(
        "contact_info",
        lambda device: device.contact_info,
        lambda device, value: device.contact_info.set(value),
        SmartUX60.contact_info.max_length,
    ),
    _address(
        "ip_address",
        lambda device: device.ip_address,
        lambda device, value: device.ip_address.set(IPv4Address(value)),
    ),
    _address(
        "subnet_mask",
        lambda device: device.subnet_mask,
        lambda device, value: device.subnet_mask.set(IPv4Address(value)),
    ),
    _address(
        "gateway",
        lambda device: device.gateway,
        lambda device, value: device.gateway.set(IPv4Address(value)),
    ),
    _address(
        "primary_dns",
        lambda device: device.primary_dns,
        lambda device, value: device.primary_dns.set(IPv4Address(value)),
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: SmartTechnologiesConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the text entities."""
    coordinator = entry.runtime_data
    async_add_entities(SmartText(coordinator, description) for description in TEXTS)


class SmartText(SmartTechnologiesEntity, TextEntity):
    """A text entity for a string or IP address setting."""

    entity_description: SmartTextDescription

    def __init__(
        self,
        coordinator: SmartTechnologiesCoordinator,
        description: SmartTextDescription,
    ) -> None:
        """Initialize the text entity."""
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
    def native_value(self) -> str | None:
        """Return the current value."""
        value = self.coordinator.data.values.get(self.entity_description.key)
        return None if value is None else str(value)

    @override
    async def async_set_value(self, value: str) -> None:
        """Change the setting."""
        description = self.entity_description
        confirmed = await self._async_command(
            lambda: description.set_fn(self.coordinator.device, value)
        )
        self.coordinator.async_set_value(description.key, confirmed)
