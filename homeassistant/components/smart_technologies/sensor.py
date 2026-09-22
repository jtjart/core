"""Sensor platform for the SMART Technologies integration."""

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, override

from smart_serial import SmartUX60
from smart_serial.devices.settings import BoundReadOnlySetting
from smart_serial.devices.ux60 import NetworkStatus, PowerState

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import EntityCategory, UnitOfTime
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.typing import StateType

from .const import UPDATE_INTERVAL, enum_option
from .coordinator import (
    SmartTechnologiesConfigEntry,
    SmartTechnologiesCoordinator,
    SmartTechnologiesData,
    TrackedSetting,
)
from .entity import SmartTechnologiesEntity, SmartTechnologiesEntityDescription

# Read-only entities served by the coordinator: no limit needed.
PARALLEL_UPDATES = 0


def _value(key: str) -> Callable[[SmartTechnologiesData], StateType]:
    def value(data: SmartTechnologiesData) -> StateType:
        result: StateType = data.values.get(key)
        return result

    return value


def _option(key: str) -> Callable[[SmartTechnologiesData], StateType]:
    def option(data: SmartTechnologiesData) -> StateType:
        member: StrEnum | None = data.values.get(key)
        return enum_option(member) if member is not None else None

    return option


@dataclass(frozen=True, kw_only=True)
class SmartSensorDescription(
    SensorEntityDescription, SmartTechnologiesEntityDescription
):
    """Describes a SMART Technologies sensor."""

    value_fn: Callable[[SmartTechnologiesData], StateType]
    # ``None`` for values the coordinator already has (the power state).
    setting: Callable[[SmartUX60], BoundReadOnlySetting[Any]] | None = None


def _diagnostic(
    key: str,
    setting: Callable[[SmartUX60], BoundReadOnlySetting[Any]],
    **kwargs: Any,
) -> SmartSensorDescription:
    """Describe static device information: disabled by default, kept while off."""
    return SmartSensorDescription(
        key=key,
        translation_key=key,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        requires_power=False,
        setting=setting,
        value_fn=_value(key),
        **kwargs,
    )


SENSORS: tuple[SmartSensorDescription, ...] = (
    SmartSensorDescription(
        key="power_state",
        translation_key="power_state",
        device_class=SensorDeviceClass.ENUM,
        options=[enum_option(member) for member in PowerState],
        requires_power=False,
        value_fn=lambda data: enum_option(data.power_state),
    ),
    SmartSensorDescription(
        key="lamp_hours",
        translation_key="lamp_hours",
        device_class=SensorDeviceClass.DURATION,
        native_unit_of_measurement=UnitOfTime.HOURS,
        # Resetting the lamp counter starts a new cycle from zero.
        state_class=SensorStateClass.TOTAL_INCREASING,
        entity_category=EntityCategory.DIAGNOSTIC,
        requires_power=False,
        setting=lambda device: device.lamp_hours,
        value_fn=_value("lamp_hours"),
    ),
    SmartSensorDescription(
        key="system_hours",
        translation_key="system_hours",
        device_class=SensorDeviceClass.DURATION,
        native_unit_of_measurement=UnitOfTime.HOURS,
        state_class=SensorStateClass.TOTAL_INCREASING,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        requires_power=False,
        setting=lambda device: device.system_hours,
        value_fn=_value("system_hours"),
    ),
    SmartSensorDescription(
        key="network_status",
        translation_key="network_status",
        device_class=SensorDeviceClass.ENUM,
        options=[enum_option(member) for member in NetworkStatus],
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        setting=lambda device: device.network_status,
        value_fn=_option("network_status"),
    ),
    SmartSensorDescription(
        key="resolution",
        translation_key="resolution",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        poll_interval=UPDATE_INTERVAL,
        setting=lambda device: device.resolution,
        value_fn=_value("resolution"),
    ),
    _diagnostic("mac_address", lambda device: device.mac_address),
    _diagnostic("model_number", lambda device: device.model_number),
    _diagnostic("serial_number", lambda device: device.serial_number),
    _diagnostic(
        "projector_firmware_version", lambda device: device.projector_firmware_version
    ),
    _diagnostic(
        "network_firmware_version", lambda device: device.network_firmware_version
    ),
    _diagnostic(
        "processor_firmware_version", lambda device: device.processor_firmware_version
    ),
    _diagnostic("esp_firmware_version", lambda device: device.esp_firmware_version),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: SmartTechnologiesConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the sensors."""
    coordinator = entry.runtime_data
    async_add_entities(SmartSensor(coordinator, description) for description in SENSORS)


class SmartSensor(SmartTechnologiesEntity, SensorEntity):
    """A sensor reading a projector setting."""

    entity_description: SmartSensorDescription

    def __init__(
        self,
        coordinator: SmartTechnologiesCoordinator,
        description: SmartSensorDescription,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, description)

    @override
    def _tracked_settings(self) -> Sequence[TrackedSetting]:
        description = self.entity_description
        if description.setting is None:
            return ()
        return (
            TrackedSetting(
                key=description.key,
                accessor=description.setting,
                interval=description.poll_interval,
            ),
        )

    @property
    @override
    def native_value(self) -> StateType:
        """Return the value of the sensor."""
        return self.entity_description.value_fn(self.coordinator.data)
