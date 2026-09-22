"""Binary sensor platform for the SMART Technologies integration."""

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import override

from smart_serial import SmartUX60
from smart_serial.devices.settings import BoundReadOnlySetting

from homeassistant.components.binary_sensor import (
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import UPDATE_INTERVAL
from .coordinator import (
    SmartTechnologiesConfigEntry,
    SmartTechnologiesCoordinator,
    TrackedSetting,
)
from .entity import SmartTechnologiesEntity, SmartTechnologiesEntityDescription

# Read-only entities served by the coordinator: no limit needed.
PARALLEL_UPDATES = 0


@dataclass(frozen=True, kw_only=True)
class SmartBinarySensorDescription(
    BinarySensorEntityDescription, SmartTechnologiesEntityDescription
):
    """Describes a SMART Technologies binary sensor."""

    setting: Callable[[SmartUX60], BoundReadOnlySetting[bool]]


BINARY_SENSORS: tuple[SmartBinarySensorDescription, ...] = (
    SmartBinarySensorDescription(
        key="signal_detected",
        translation_key="signal_detected",
        poll_interval=UPDATE_INTERVAL,
        setting=lambda device: device.signal_detected,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: SmartTechnologiesConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the binary sensors."""
    coordinator = entry.runtime_data
    async_add_entities(
        SmartBinarySensor(coordinator, description) for description in BINARY_SENSORS
    )


class SmartBinarySensor(SmartTechnologiesEntity, BinarySensorEntity):
    """A binary sensor reading a projector setting."""

    entity_description: SmartBinarySensorDescription

    def __init__(
        self,
        coordinator: SmartTechnologiesCoordinator,
        description: SmartBinarySensorDescription,
    ) -> None:
        """Initialize the binary sensor."""
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
