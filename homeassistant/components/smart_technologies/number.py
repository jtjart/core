"""Number platform for the SMART Technologies integration."""

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any, override

from smart_serial import SmartUX60
from smart_serial.devices.settings import BoundSetting

from homeassistant.components.number import (
    NumberDeviceClass,
    NumberEntity,
    NumberEntityDescription,
)
from homeassistant.const import EntityCategory, UnitOfTime
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


@dataclass(frozen=True, kw_only=True)
class SmartNumberDescription(
    NumberEntityDescription, SmartTechnologiesEntityDescription
):
    """Describes a number backed by a library integer setting."""

    setting: Callable[[SmartUX60], BoundSetting[int]]


def _number(
    key: str,
    setting: Callable[[SmartUX60], BoundSetting[int]],
    bounds: range,
    *,
    enabled: bool = False,
    **kwargs: Any,
) -> SmartNumberDescription:
    """Describe an integer setting; its limits come from the library."""
    return SmartNumberDescription(
        key=key,
        translation_key=key,
        entity_category=EntityCategory.CONFIG,
        entity_registry_enabled_default=enabled,
        native_min_value=bounds.start,
        native_max_value=bounds.stop - 1,
        native_step=1,
        setting=setting,
        **kwargs,
    )


NUMBERS: tuple[SmartNumberDescription, ...] = (
    _number(
        "brightness",
        lambda device: device.brightness,
        SmartUX60.brightness.bounds,
        enabled=True,
    ),
    _number(
        "contrast",
        lambda device: device.contrast,
        SmartUX60.contrast.bounds,
        enabled=True,
    ),
    _number(
        "auto_power_off",
        lambda device: device.auto_power_off,
        SmartUX60.auto_power_off.bounds,
        enabled=True,
        device_class=NumberDeviceClass.DURATION,
        native_unit_of_measurement=UnitOfTime.MINUTES,
    ),
    _number(
        "white_peaking",
        lambda device: device.white_peaking,
        SmartUX60.white_peaking.bounds,
    ),
    _number("degamma", lambda device: device.degamma, SmartUX60.degamma.bounds),
    _number("red", lambda device: device.red, SmartUX60.red.bounds),
    _number("green", lambda device: device.green, SmartUX60.green.bounds),
    _number("blue", lambda device: device.blue, SmartUX60.blue.bounds),
    _number("cyan", lambda device: device.cyan, SmartUX60.cyan.bounds),
    _number("magenta", lambda device: device.magenta, SmartUX60.magenta.bounds),
    _number("yellow", lambda device: device.yellow, SmartUX60.yellow.bounds),
    _number(
        "saturation", lambda device: device.saturation, SmartUX60.saturation.bounds
    ),
    _number("tint", lambda device: device.tint, SmartUX60.tint.bounds),
    _number("sharpness", lambda device: device.sharpness, SmartUX60.sharpness.bounds),
    _number("frequency", lambda device: device.frequency, SmartUX60.frequency.bounds),
    _number("tracking", lambda device: device.tracking, SmartUX60.tracking.bounds),
    _number("zoom", lambda device: device.zoom, SmartUX60.zoom.bounds),
    _number(
        "horizontal_position",
        lambda device: device.horizontal_position,
        SmartUX60.horizontal_position.bounds,
    ),
    _number(
        "vertical_position",
        lambda device: device.vertical_position,
        SmartUX60.vertical_position.bounds,
    ),
    _number(
        "projector_id",
        lambda device: device.projector_id,
        SmartUX60.projector_id.bounds,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: SmartTechnologiesConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the numbers."""
    coordinator = entry.runtime_data
    async_add_entities(SmartNumber(coordinator, description) for description in NUMBERS)


class SmartNumber(SmartTechnologiesEntity, NumberEntity):
    """A number for an integer projector setting."""

    entity_description: SmartNumberDescription

    def __init__(
        self,
        coordinator: SmartTechnologiesCoordinator,
        description: SmartNumberDescription,
    ) -> None:
        """Initialize the number."""
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
    def native_value(self) -> float | None:
        """Return the current value."""
        value: int | None = self.coordinator.data.values.get(
            self.entity_description.key
        )
        return value

    @override
    async def async_set_native_value(self, value: float) -> None:
        """Change the setting."""
        description = self.entity_description
        confirmed = await self._async_command(
            lambda: description.setting(self.coordinator.device).set(int(value))
        )
        self.coordinator.async_set_value(description.key, confirmed)
