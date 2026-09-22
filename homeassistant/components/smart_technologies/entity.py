"""Base entity for the SMART Technologies integration."""

from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from datetime import timedelta
from typing import override

from smart_serial import CommandRejectedError, DeviceIdleError, SmartSerialError
from smart_serial.devices.ux60 import PowerState

from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers.entity import EntityDescription
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, SLOW_INTERVAL
from .coordinator import SmartTechnologiesCoordinator, TrackedSetting


@dataclass(frozen=True, kw_only=True)
class SmartTechnologiesEntityDescription(EntityDescription):
    """Description fields shared by every SMART Technologies entity."""

    # How often the setting behind the entity is re-read while the projector is on.
    poll_interval: timedelta = SLOW_INTERVAL
    # Most settings cannot be read or changed while the projector is off. Static
    # information (firmware, hours, ...) keeps showing its last known value.
    requires_power: bool = True


class SmartTechnologiesEntity(CoordinatorEntity[SmartTechnologiesCoordinator]):
    """Common behavior of all entities of a SMART projector."""

    _attr_has_entity_name = True
    entity_description: SmartTechnologiesEntityDescription

    def __init__(
        self,
        coordinator: SmartTechnologiesCoordinator,
        description: SmartTechnologiesEntityDescription,
    ) -> None:
        """Initialize the entity."""
        super().__init__(coordinator)
        self.entity_description = description
        self._attr_unique_id = f"{coordinator.serial_number}_{description.key}"
        self._attr_device_info = coordinator.device_info

    @property
    @override
    def available(self) -> bool:
        """Return whether the entity can currently be read and controlled."""
        if not super().available:
            return False
        return (
            not self.entity_description.requires_power
            or self.coordinator.data.power_state is PowerState.ON
        )

    def _tracked_settings(self) -> Sequence[TrackedSetting]:
        """Return the library settings this entity needs polled."""
        return ()

    @override
    async def async_added_to_hass(self) -> None:
        """Ask the coordinator to keep this entity's settings up to date."""
        await super().async_added_to_hass()
        tracked = self._tracked_settings()
        for setting in tracked:
            self.async_on_remove(self.coordinator.async_track_setting(setting))
        if tracked:
            await self.coordinator.async_request_refresh()

    def _require_power(self) -> None:
        """Refuse an action that the projector cannot perform while it is off."""
        if self.coordinator.data.power_state is not PowerState.ON:
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="device_off",
            )

    async def _async_command[_T](self, call: Callable[[], Awaitable[_T]]) -> _T:
        """Run a library call, translating its errors for the user."""
        try:
            return await call()
        except ValueError as err:
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="invalid_value",
                translation_placeholders={"error": str(err)},
            ) from err
        except DeviceIdleError as err:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="device_idle",
            ) from err
        except CommandRejectedError as err:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="command_rejected",
                translation_placeholders={"error": str(err)},
            ) from err
        except SmartSerialError as err:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="command_failed",
                translation_placeholders={"error": str(err)},
            ) from err
