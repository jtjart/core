"""Select platform for the SMART Technologies integration."""

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, override

from smart_serial import SmartUX60, Source
from smart_serial.devices.settings import BoundSetting
from smart_serial.devices.ux60 import (
    AspectRatio,
    ClosedCaptioning,
    DisplayMode,
    Language,
    ProjectionMode,
    StartupScreen,
)

from homeassistant.components.select import SelectEntity, SelectEntityDescription
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import UPDATE_INTERVAL, enum_option
from .coordinator import (
    SmartTechnologiesConfigEntry,
    SmartTechnologiesCoordinator,
    TrackedSetting,
)
from .entity import SmartTechnologiesEntity, SmartTechnologiesEntityDescription

# One command at a time on the serial line.
PARALLEL_UPDATES = 1

OPTION_DISABLED = "disabled"
KEY_VIDEO_INPUTS = "video_inputs"


@dataclass(frozen=True, kw_only=True)
class SmartSelectDescription(
    SelectEntityDescription, SmartTechnologiesEntityDescription
):
    """Describes a select backed by a library enum setting."""

    enum: type[StrEnum]
    setting: Callable[[SmartUX60], BoundSetting[Any]]


def _select(
    key: str,
    enum: type[StrEnum],
    setting: Callable[[SmartUX60], BoundSetting[Any]],
    *,
    configuration: bool = True,
    enabled: bool = False,
    **kwargs: Any,
) -> SmartSelectDescription:
    return SmartSelectDescription(
        key=key,
        translation_key=key,
        options=[enum_option(member) for member in enum],
        entity_category=EntityCategory.CONFIG if configuration else None,
        entity_registry_enabled_default=enabled,
        enum=enum,
        setting=setting,
        **kwargs,
    )


SELECTS: tuple[SmartSelectDescription, ...] = (
    _select(
        "display_mode",
        DisplayMode,
        lambda device: device.display_mode,
        configuration=False,
        enabled=True,
        poll_interval=UPDATE_INTERVAL,
    ),
    _select(
        "aspect_ratio", AspectRatio, lambda device: device.aspect_ratio, enabled=True
    ),
    _select(
        "closed_captioning",
        ClosedCaptioning,
        lambda device: device.closed_captioning,
    ),
    _select("projection_mode", ProjectionMode, lambda device: device.projection_mode),
    _select("startup_screen", StartupScreen, lambda device: device.startup_screen),
    _select("language", Language, lambda device: device.language),
)


@dataclass(frozen=True, kw_only=True)
class SmartUsbSourceDescription(
    SelectEntityDescription, SmartTechnologiesEntityDescription
):
    """Describes the select that routes a USB port to a video input."""

    setting: Callable[[SmartUX60], BoundSetting[Source | None]]


USB_SOURCES: tuple[SmartUsbSourceDescription, ...] = (
    SmartUsbSourceDescription(
        key="usb1_source",
        translation_key="usb1_source",
        entity_category=EntityCategory.CONFIG,
        entity_registry_enabled_default=False,
        setting=lambda device: device.usb1_source,
    ),
    SmartUsbSourceDescription(
        key="usb2_source",
        translation_key="usb2_source",
        entity_category=EntityCategory.CONFIG,
        entity_registry_enabled_default=False,
        setting=lambda device: device.usb2_source,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: SmartTechnologiesConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the selects."""
    coordinator = entry.runtime_data
    async_add_entities(
        [SmartSelect(coordinator, description) for description in SELECTS]
        + [
            SmartUsbSourceSelect(coordinator, description)
            for description in USB_SOURCES
        ]
    )


class SmartSelect(SmartTechnologiesEntity, SelectEntity):
    """A select for a setting that takes one of a fixed set of values."""

    entity_description: SmartSelectDescription

    def __init__(
        self,
        coordinator: SmartTechnologiesCoordinator,
        description: SmartSelectDescription,
    ) -> None:
        """Initialize the select."""
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
    def current_option(self) -> str | None:
        """Return the selected option."""
        member: StrEnum | None = self.coordinator.data.values.get(
            self.entity_description.key
        )
        return enum_option(member) if member is not None else None

    @override
    async def async_select_option(self, option: str) -> None:
        """Change the setting."""
        description = self.entity_description
        member = description.enum[option.upper()]
        confirmed = await self._async_command(
            lambda: description.setting(self.coordinator.device).set(member)
        )
        self.coordinator.async_set_value(description.key, confirmed)


class SmartUsbSourceSelect(SmartTechnologiesEntity, SelectEntity):
    """Select which video input a USB port is routed to.

    The available inputs depend on the model and firmware, so the options come
    from the projector rather than from a fixed list.
    """

    entity_description: SmartUsbSourceDescription

    def __init__(
        self,
        coordinator: SmartTechnologiesCoordinator,
        description: SmartUsbSourceDescription,
    ) -> None:
        """Initialize the select."""
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
            TrackedSetting(
                key=KEY_VIDEO_INPUTS,
                accessor=lambda device: device.video_inputs,
                interval=description.poll_interval,
            ),
        )

    @property
    def _current(self) -> Source | None:
        current: Source | None = self.coordinator.data.values.get(
            self.entity_description.key
        )
        return current

    @property
    @override
    def options(self) -> list[str]:
        """Return "disabled" and the inputs the projector offers."""
        inputs: tuple[Source, ...] = (
            self.coordinator.data.values.get(KEY_VIDEO_INPUTS) or ()
        )
        options = [OPTION_DISABLED, *(source.value for source in inputs)]
        if (current := self._current) is not None and current.value not in options:
            options.append(current.value)
        return options

    @property
    @override
    def current_option(self) -> str | None:
        """Return the input the port is routed to."""
        if self.entity_description.key not in self.coordinator.data.values:
            return None
        current = self._current
        return current.value if current is not None else OPTION_DISABLED

    @override
    async def async_select_option(self, option: str) -> None:
        """Route the port to an input, or disable it."""
        description = self.entity_description
        target = None if option == OPTION_DISABLED else Source(option)
        confirmed = await self._async_command(
            lambda: description.setting(self.coordinator.device).set(target)
        )
        self.coordinator.async_set_value(description.key, confirmed)
