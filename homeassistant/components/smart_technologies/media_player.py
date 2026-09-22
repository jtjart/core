"""Media player platform for the SMART Technologies integration."""

from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from typing import override

from smart_serial import SmartUX60, Source
from smart_serial.devices.ux60 import PowerState

from homeassistant.components.media_player import (
    MediaPlayerEntity,
    MediaPlayerEntityDescription,
    MediaPlayerEntityFeature,
    MediaPlayerState,
)
from homeassistant.core import HomeAssistant, ServiceResponse
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import DOMAIN, UPDATE_INTERVAL
from .coordinator import (
    SmartTechnologiesConfigEntry,
    SmartTechnologiesCoordinator,
    TrackedSetting,
)
from .entity import SmartTechnologiesEntity, SmartTechnologiesEntityDescription

# One command at a time on the serial line.
PARALLEL_UPDATES = 1

KEY_INPUT = "input_source"
KEY_VIDEO_INPUTS = "video_inputs"
KEY_VOLUME = "volume"
KEY_MUTE = "mute"

_VOLUME_MIN = SmartUX60.volume.bounds.start
_VOLUME_MAX = SmartUX60.volume.bounds.stop - 1

# "Confirm off" is the ten-second window after the first "off": still on.
_STATES = {
    PowerState.ON: MediaPlayerState.ON,
    PowerState.POWERING: MediaPlayerState.ON,
    PowerState.CONFIRM_OFF: MediaPlayerState.ON,
    PowerState.COOLING: MediaPlayerState.OFF,
    PowerState.IDLE: MediaPlayerState.OFF,
}


@dataclass(frozen=True, kw_only=True)
class SmartMediaPlayerDescription(
    MediaPlayerEntityDescription, SmartTechnologiesEntityDescription
):
    """Describes the SMART Technologies media player."""


DESCRIPTION = SmartMediaPlayerDescription(
    key="media_player",
    name=None,
    requires_power=False,
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: SmartTechnologiesConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the media player."""
    async_add_entities([SmartTechnologiesMediaPlayer(entry.runtime_data)])


class SmartTechnologiesMediaPlayer(SmartTechnologiesEntity, MediaPlayerEntity):
    """The projector as a media player: power, input, volume and mute."""

    entity_description: SmartMediaPlayerDescription

    _attr_supported_features = (
        MediaPlayerEntityFeature.TURN_ON
        | MediaPlayerEntityFeature.TURN_OFF
        | MediaPlayerEntityFeature.VOLUME_SET
        | MediaPlayerEntityFeature.VOLUME_STEP
        | MediaPlayerEntityFeature.VOLUME_MUTE
        | MediaPlayerEntityFeature.SELECT_SOURCE
    )

    def __init__(self, coordinator: SmartTechnologiesCoordinator) -> None:
        """Initialize the media player."""
        super().__init__(coordinator, DESCRIPTION)

    @override
    def _tracked_settings(self) -> Sequence[TrackedSetting]:
        return (
            TrackedSetting(
                key=KEY_INPUT,
                accessor=lambda device: device.input_source,
                interval=UPDATE_INTERVAL,
            ),
            TrackedSetting(
                key=KEY_VOLUME,
                accessor=lambda device: device.volume,
                interval=UPDATE_INTERVAL,
            ),
            TrackedSetting(
                key=KEY_MUTE,
                accessor=lambda device: device.mute,
                interval=UPDATE_INTERVAL,
            ),
            TrackedSetting(
                key=KEY_VIDEO_INPUTS,
                accessor=lambda device: device.video_inputs,
                interval=self.entity_description.poll_interval,
            ),
        )

    @property
    @override
    def state(self) -> MediaPlayerState:
        """Return the state of the projector."""
        return _STATES[self.coordinator.data.power_state]

    @property
    def _inputs(self) -> dict[str, Source]:
        """Return the available inputs by display name."""
        sources: tuple[Source, ...] = (
            self.coordinator.data.values.get(KEY_VIDEO_INPUTS) or ()
        )
        return {source.display_name: source for source in sources}

    @property
    @override
    def source_list(self) -> list[str] | None:
        """Return the names of the available inputs."""
        return list(self._inputs) or None

    @property
    @override
    def source(self) -> str | None:
        """Return the name of the active input."""
        active: Source | None = self.coordinator.data.values.get(KEY_INPUT)
        return active.display_name if active else None

    @property
    @override
    def volume_level(self) -> float | None:
        """Return the volume as a fraction of the projector's range."""
        volume: int | None = self.coordinator.data.values.get(KEY_VOLUME)
        if volume is None:
            return None
        return (volume - _VOLUME_MIN) / (_VOLUME_MAX - _VOLUME_MIN)

    @property
    @override
    def is_volume_muted(self) -> bool | None:
        """Return whether the audio is muted."""
        muted: bool | None = self.coordinator.data.values.get(KEY_MUTE)
        return muted

    @override
    async def async_turn_on(self) -> None:
        """Turn the projector on."""
        device = self.coordinator.device
        state = await self._async_command(device.power_on)
        self.coordinator.async_set_power_state(state)

    @override
    async def async_turn_off(self) -> None:
        """Turn the projector off, confirming the shutdown prompt if needed."""
        device = self.coordinator.device
        await self._async_command(device.turn_off)
        state = await self._async_command(device.get_power_state)
        self.coordinator.async_set_power_state(state)

    @override
    async def async_set_volume_level(self, volume: float) -> None:
        """Set the volume."""
        self._require_power()
        level = _VOLUME_MIN + round(volume * (_VOLUME_MAX - _VOLUME_MIN))
        await self._async_set_volume(lambda: self.coordinator.device.volume.set(level))

    @override
    async def async_volume_up(self) -> None:
        """Raise the volume by one step."""
        self._require_power()
        await self._async_set_volume(lambda: self.coordinator.device.volume.adjust(1))

    @override
    async def async_volume_down(self) -> None:
        """Lower the volume by one step."""
        self._require_power()
        await self._async_set_volume(lambda: self.coordinator.device.volume.adjust(-1))

    @override
    async def async_mute_volume(self, mute: bool) -> None:
        """Mute or unmute the audio."""
        self._require_power()
        confirmed = await self._async_command(
            lambda: self.coordinator.device.mute.set(mute)
        )
        self.coordinator.async_set_value(KEY_MUTE, confirmed)

    @override
    async def async_select_source(self, source: str) -> None:
        """Switch to another input."""
        self._require_power()
        if (target := self._inputs.get(source)) is None:
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="invalid_source",
                translation_placeholders={"source": source},
            )
        confirmed = await self._async_command(
            lambda: self.coordinator.device.select_input(target)
        )
        self.coordinator.async_set_value(KEY_INPUT, confirmed)

    async def _async_set_volume(self, call: Callable[[], Awaitable[int]]) -> None:
        confirmed = await self._async_command(call)
        self.coordinator.async_set_value(KEY_VOLUME, confirmed)

    async def async_service_get_value(self, key: str) -> ServiceResponse:
        """Read a raw value from the projector."""
        self._require_power()
        value = await self._async_command(
            lambda: self.coordinator.device.get_value(key)
        )
        return {"value": value}

    async def async_service_set_value(
        self, key: str, value: str, source: str | None = None
    ) -> ServiceResponse:
        """Write a raw value to the projector."""
        self._require_power()
        confirmed = await self._async_command(
            lambda: self.coordinator.device.set_value(key, value, source=source)
        )
        await self.coordinator.async_refresh_settings()
        return {"value": confirmed}

    async def async_service_adjust_value(
        self, key: str, delta: int, source: str | None = None
    ) -> ServiceResponse:
        """Change a raw value on the projector by a relative amount."""
        self._require_power()
        confirmed = await self._async_command(
            lambda: self.coordinator.device.adjust_value(key, delta, source=source)
        )
        await self.coordinator.async_refresh_settings()
        return {"value": confirmed}
