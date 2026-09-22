"""Button platform for the SMART Technologies integration."""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any, override

from smart_serial import SmartUX60
from smart_serial.devices.ux60 import PowerState

from homeassistant.components.button import ButtonEntity, ButtonEntityDescription
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import SmartTechnologiesConfigEntry, SmartTechnologiesCoordinator
from .entity import SmartTechnologiesEntity, SmartTechnologiesEntityDescription

# One command at a time on the serial line.
PARALLEL_UPDATES = 1


@dataclass(frozen=True, kw_only=True)
class SmartButtonDescription(
    ButtonEntityDescription, SmartTechnologiesEntityDescription
):
    """Describes a button that runs a projector command."""

    press_fn: Callable[[SmartUX60], Awaitable[Any]]
    # Re-read every setting afterwards (the command changes many of them).
    refresh_settings: bool = False


BUTTONS: tuple[SmartButtonDescription, ...] = (
    SmartButtonDescription(
        key="power_off_now",
        translation_key="power_off_now",
        entity_registry_enabled_default=False,
        press_fn=lambda device: device.power_off_now(),
    ),
    SmartButtonDescription(
        key="power_off_low_power",
        translation_key="power_off_low_power",
        entity_registry_enabled_default=False,
        press_fn=lambda device: device.power_off_low_power(),
    ),
    SmartButtonDescription(
        key="reset_lamp_hours",
        translation_key="reset_lamp_hours",
        entity_category=EntityCategory.CONFIG,
        entity_registry_enabled_default=False,
        press_fn=lambda device: device.reset_lamp_hours(),
        refresh_settings=True,
    ),
    SmartButtonDescription(
        key="restore_defaults",
        translation_key="restore_defaults",
        entity_category=EntityCategory.CONFIG,
        entity_registry_enabled_default=False,
        press_fn=lambda device: device.restore_defaults(),
        refresh_settings=True,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: SmartTechnologiesConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the buttons."""
    coordinator = entry.runtime_data
    async_add_entities(SmartButton(coordinator, description) for description in BUTTONS)


class SmartButton(SmartTechnologiesEntity, ButtonEntity):
    """A button that runs a projector command."""

    entity_description: SmartButtonDescription

    def __init__(
        self,
        coordinator: SmartTechnologiesCoordinator,
        description: SmartButtonDescription,
    ) -> None:
        """Initialize the button."""
        super().__init__(coordinator, description)

    @override
    async def async_press(self) -> None:
        """Run the command."""
        description = self.entity_description
        result = await self._async_command(
            lambda: description.press_fn(self.coordinator.device)
        )
        if isinstance(result, PowerState):
            self.coordinator.async_set_power_state(result)
        if description.refresh_settings:
            await self.coordinator.async_refresh_settings()
