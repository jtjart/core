"""Test the SMART Technologies media player and its actions."""

from freezegun.api import FrozenDateTimeFactory
import probatio
import pytest
from smart_serial import UnexpectedResponseError
from syrupy.assertion import SnapshotAssertion

from homeassistant.components.media_player import (
    ATTR_INPUT_SOURCE,
    ATTR_MEDIA_VOLUME_LEVEL,
    ATTR_MEDIA_VOLUME_MUTED,
    DOMAIN as MEDIA_PLAYER_DOMAIN,
    SERVICE_SELECT_SOURCE,
    MediaPlayerState,
)
from homeassistant.components.smart_technologies.const import DOMAIN
from homeassistant.const import (
    ATTR_ENTITY_ID,
    SERVICE_TURN_OFF,
    SERVICE_TURN_ON,
    SERVICE_VOLUME_DOWN,
    SERVICE_VOLUME_MUTE,
    SERVICE_VOLUME_SET,
    SERVICE_VOLUME_UP,
    Platform,
)
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
import homeassistant.helpers.entity_registry as er

from . import async_tick, setup_integration
from .conftest import EmulatedProjector

from tests.common import MockConfigEntry, snapshot_platform

ENTITY_ID = "media_player.smart_ux60"


async def _setup(
    hass: HomeAssistant, entry: MockConfigEntry, freezer: FrozenDateTimeFactory
) -> None:
    await setup_integration(hass, entry, freezer, [Platform.MEDIA_PLAYER])


async def test_media_player(
    hass: HomeAssistant,
    freezer: FrozenDateTimeFactory,
    snapshot: SnapshotAssertion,
    entity_registry: er.EntityRegistry,
    mock_config_entry: MockConfigEntry,
) -> None:
    """Test the media player and its device."""
    await _setup(hass, mock_config_entry, freezer)
    await snapshot_platform(hass, entity_registry, snapshot, mock_config_entry.entry_id)


@pytest.mark.parametrize(
    ("power", "state"),
    [
        ("On", MediaPlayerState.ON),
        ("Powering", MediaPlayerState.ON),
        ("Confirm off", MediaPlayerState.ON),
        ("Cooling", MediaPlayerState.OFF),
        ("Idle", MediaPlayerState.OFF),
    ],
)
async def test_state_follows_the_power_state(
    hass: HomeAssistant,
    freezer: FrozenDateTimeFactory,
    mock_config_entry: MockConfigEntry,
    projector: EmulatedProjector,
    power: str,
    state: MediaPlayerState,
) -> None:
    """Test every power state maps to on or off."""
    await _setup(hass, mock_config_entry, freezer)

    projector.power = power
    await async_tick(hass, freezer)

    assert hass.states.get(ENTITY_ID).state == state


async def test_attributes_when_the_projector_reports_nothing_useful(
    hass: HomeAssistant,
    freezer: FrozenDateTimeFactory,
    mock_config_entry: MockConfigEntry,
    projector: EmulatedProjector,
) -> None:
    """Test unreadable values produce no attributes instead of errors."""
    projector.values["videoinputs"] = ""
    projector.values["input"] = "hdmi1"
    await _setup(hass, mock_config_entry, freezer)

    state = hass.states.get(ENTITY_ID)
    assert state.state == MediaPlayerState.ON
    assert "source_list" not in state.attributes


async def test_turn_on_and_off(
    hass: HomeAssistant,
    freezer: FrozenDateTimeFactory,
    mock_config_entry: MockConfigEntry,
    projector: EmulatedProjector,
) -> None:
    """Test power control, including the projector's shutdown confirmation."""
    projector.power = "Idle"
    await _setup(hass, mock_config_entry, freezer)
    assert hass.states.get(ENTITY_ID).state == MediaPlayerState.OFF

    await hass.services.async_call(
        MEDIA_PLAYER_DOMAIN, SERVICE_TURN_ON, {ATTR_ENTITY_ID: ENTITY_ID}, blocking=True
    )
    assert hass.states.get(ENTITY_ID).state == MediaPlayerState.ON

    projector.commands.clear()
    await hass.services.async_call(
        MEDIA_PLAYER_DOMAIN,
        SERVICE_TURN_OFF,
        {ATTR_ENTITY_ID: ENTITY_ID},
        blocking=True,
    )
    assert projector.commands[:2] == ["off", "off"]  # the second confirms
    assert projector.power == "Cooling"
    assert hass.states.get(ENTITY_ID).state == MediaPlayerState.OFF


async def test_volume(
    hass: HomeAssistant,
    freezer: FrozenDateTimeFactory,
    mock_config_entry: MockConfigEntry,
    projector: EmulatedProjector,
) -> None:
    """Test volume control maps the projector's -20..20 range onto 0..1."""
    await _setup(hass, mock_config_entry, freezer)
    assert hass.states.get(ENTITY_ID).attributes[ATTR_MEDIA_VOLUME_LEVEL] == 0.5

    await hass.services.async_call(
        MEDIA_PLAYER_DOMAIN,
        SERVICE_VOLUME_SET,
        {ATTR_ENTITY_ID: ENTITY_ID, ATTR_MEDIA_VOLUME_LEVEL: 0.75},
        blocking=True,
    )
    assert projector.values["volume"] == "10"
    assert hass.states.get(ENTITY_ID).attributes[ATTR_MEDIA_VOLUME_LEVEL] == 0.75

    await hass.services.async_call(
        MEDIA_PLAYER_DOMAIN,
        SERVICE_VOLUME_UP,
        {ATTR_ENTITY_ID: ENTITY_ID},
        blocking=True,
    )
    assert projector.values["volume"] == "11"

    await hass.services.async_call(
        MEDIA_PLAYER_DOMAIN,
        SERVICE_VOLUME_DOWN,
        {ATTR_ENTITY_ID: ENTITY_ID},
        blocking=True,
    )
    await hass.services.async_call(
        MEDIA_PLAYER_DOMAIN,
        SERVICE_VOLUME_DOWN,
        {ATTR_ENTITY_ID: ENTITY_ID},
        blocking=True,
    )
    assert projector.values["volume"] == "9"
    assert "set volume+1" in projector.commands
    assert "set volume-1" in projector.commands


async def test_mute(
    hass: HomeAssistant,
    freezer: FrozenDateTimeFactory,
    mock_config_entry: MockConfigEntry,
    projector: EmulatedProjector,
) -> None:
    """Test muting."""
    await _setup(hass, mock_config_entry, freezer)

    await hass.services.async_call(
        MEDIA_PLAYER_DOMAIN,
        SERVICE_VOLUME_MUTE,
        {ATTR_ENTITY_ID: ENTITY_ID, ATTR_MEDIA_VOLUME_MUTED: True},
        blocking=True,
    )

    assert projector.values["mute"] == "on"
    assert hass.states.get(ENTITY_ID).attributes[ATTR_MEDIA_VOLUME_MUTED] is True


async def test_select_source(
    hass: HomeAssistant,
    freezer: FrozenDateTimeFactory,
    mock_config_entry: MockConfigEntry,
    projector: EmulatedProjector,
) -> None:
    """Test switching input by its displayed name."""
    await _setup(hass, mock_config_entry, freezer)

    await hass.services.async_call(
        MEDIA_PLAYER_DOMAIN,
        SERVICE_SELECT_SOURCE,
        {ATTR_ENTITY_ID: ENTITY_ID, ATTR_INPUT_SOURCE: "HDMI 2"},
        blocking=True,
    )

    assert projector.values["input"] == "hdmi2"
    assert hass.states.get(ENTITY_ID).attributes[ATTR_INPUT_SOURCE] == "HDMI 2"


async def test_select_unknown_source(
    hass: HomeAssistant,
    freezer: FrozenDateTimeFactory,
    mock_config_entry: MockConfigEntry,
    projector: EmulatedProjector,
) -> None:
    """Test an input the projector does not have is refused before anything is sent."""
    await _setup(hass, mock_config_entry, freezer)
    projector.commands.clear()

    with pytest.raises(ServiceValidationError) as excinfo:
        await hass.services.async_call(
            MEDIA_PLAYER_DOMAIN,
            SERVICE_SELECT_SOURCE,
            {ATTR_ENTITY_ID: ENTITY_ID, ATTR_INPUT_SOURCE: "Betamax"},
            blocking=True,
        )

    assert excinfo.value.translation_key == "invalid_source"
    assert projector.commands == []


@pytest.mark.parametrize(
    ("service", "data"),
    [
        (SERVICE_VOLUME_SET, {ATTR_MEDIA_VOLUME_LEVEL: 0.3}),
        (SERVICE_VOLUME_UP, {}),
        (SERVICE_VOLUME_MUTE, {ATTR_MEDIA_VOLUME_MUTED: True}),
        (SERVICE_SELECT_SOURCE, {ATTR_INPUT_SOURCE: "HDMI 2"}),
    ],
)
async def test_actions_that_need_the_projector_on(
    hass: HomeAssistant,
    freezer: FrozenDateTimeFactory,
    mock_config_entry: MockConfigEntry,
    projector: EmulatedProjector,
    service: str,
    data: dict,
) -> None:
    """Test controls are refused with a clear message while the projector is off."""
    await _setup(hass, mock_config_entry, freezer)
    projector.power = "Idle"
    await async_tick(hass, freezer)
    projector.commands.clear()

    with pytest.raises(ServiceValidationError) as excinfo:
        await hass.services.async_call(
            MEDIA_PLAYER_DOMAIN,
            service,
            {ATTR_ENTITY_ID: ENTITY_ID, **data},
            blocking=True,
        )

    assert excinfo.value.translation_key == "device_off"
    assert projector.commands == []


async def test_projector_that_went_to_standby_since_the_last_poll(
    hass: HomeAssistant,
    freezer: FrozenDateTimeFactory,
    mock_config_entry: MockConfigEntry,
    projector: EmulatedProjector,
) -> None:
    """Test the race where the projector sleeps between polls gives a helpful error."""
    await _setup(hass, mock_config_entry, freezer)
    projector.power = "Idle"  # Home Assistant does not know yet

    with pytest.raises(HomeAssistantError) as excinfo:
        await hass.services.async_call(
            MEDIA_PLAYER_DOMAIN,
            SERVICE_VOLUME_UP,
            {ATTR_ENTITY_ID: ENTITY_ID},
            blocking=True,
        )

    assert excinfo.value.translation_key == "device_idle"


async def test_failed_command_is_reported(
    hass: HomeAssistant,
    freezer: FrozenDateTimeFactory,
    mock_config_entry: MockConfigEntry,
    projector: EmulatedProjector,
) -> None:
    """Test a communication failure becomes a translated error."""
    await _setup(hass, mock_config_entry, freezer)
    projector.faults.append(UnexpectedResponseError("set volume+1", "garbage"))

    with pytest.raises(HomeAssistantError) as excinfo:
        await hass.services.async_call(
            MEDIA_PLAYER_DOMAIN,
            SERVICE_VOLUME_UP,
            {ATTR_ENTITY_ID: ENTITY_ID},
            blocking=True,
        )

    assert excinfo.value.translation_domain == DOMAIN
    assert excinfo.value.translation_key == "command_failed"


# --------------------------------------------------------------------------- actions


async def test_get_value_action(
    hass: HomeAssistant,
    freezer: FrozenDateTimeFactory,
    mock_config_entry: MockConfigEntry,
) -> None:
    """Test reading a raw value returns it as the action response."""
    await _setup(hass, mock_config_entry, freezer)

    response = await hass.services.async_call(
        DOMAIN,
        "get_value",
        {ATTR_ENTITY_ID: ENTITY_ID, "key": "brightness"},
        blocking=True,
        return_response=True,
    )

    assert response == {ENTITY_ID: {"value": "50"}}


async def test_set_value_action(
    hass: HomeAssistant,
    freezer: FrozenDateTimeFactory,
    mock_config_entry: MockConfigEntry,
    projector: EmulatedProjector,
) -> None:
    """Test writing a raw value, for the active input and for another input."""
    await _setup(hass, mock_config_entry, freezer)

    response = await hass.services.async_call(
        DOMAIN,
        "set_value",
        {ATTR_ENTITY_ID: ENTITY_ID, "key": "brightness", "value": "65"},
        blocking=True,
        return_response=True,
    )
    assert response == {ENTITY_ID: {"value": "65"}}
    assert projector.values["brightness"] == "65"
    assert (
        hass.states.get("number.smart_ux60_brightness") is None
    )  # platform not loaded

    await hass.services.async_call(
        DOMAIN,
        "set_value",
        {
            ATTR_ENTITY_ID: ENTITY_ID,
            "key": "brightness",
            "value": "40",
            "source": "VGA 1",
        },
        blocking=True,
    )
    assert projector.source_writes == [("brightness", "vga1", "40")]
    assert projector.values["brightness"] == "65"  # the active input is untouched


async def test_adjust_value_action(
    hass: HomeAssistant,
    freezer: FrozenDateTimeFactory,
    mock_config_entry: MockConfigEntry,
    projector: EmulatedProjector,
) -> None:
    """Test relative adjustment."""
    await _setup(hass, mock_config_entry, freezer)

    response = await hass.services.async_call(
        DOMAIN,
        "adjust_value",
        {ATTR_ENTITY_ID: ENTITY_ID, "key": "brightness", "delta": -10},
        blocking=True,
        return_response=True,
    )

    assert response == {ENTITY_ID: {"value": "40"}}
    assert "set brightness-10" in projector.commands


async def test_action_with_a_key_the_projector_does_not_know(
    hass: HomeAssistant,
    freezer: FrozenDateTimeFactory,
    mock_config_entry: MockConfigEntry,
) -> None:
    """Test a rejected command is reported, not swallowed."""
    await _setup(hass, mock_config_entry, freezer)

    with pytest.raises(HomeAssistantError) as excinfo:
        await hass.services.async_call(
            DOMAIN,
            "get_value",
            {ATTR_ENTITY_ID: ENTITY_ID, "key": "nosuchsetting"},
            blocking=True,
            return_response=True,
        )

    assert excinfo.value.translation_key == "command_rejected"


@pytest.mark.parametrize("key", ["bright ness", "get\rset", "", "a;b"])
async def test_action_rejects_keys_that_are_not_setting_names(
    hass: HomeAssistant,
    freezer: FrozenDateTimeFactory,
    mock_config_entry: MockConfigEntry,
    projector: EmulatedProjector,
    key: str,
) -> None:
    """Test a key cannot be used to smuggle other commands onto the serial line."""
    await _setup(hass, mock_config_entry, freezer)
    projector.commands.clear()

    with pytest.raises(probatio.Invalid):
        await hass.services.async_call(
            DOMAIN,
            "get_value",
            {ATTR_ENTITY_ID: ENTITY_ID, "key": key},
            blocking=True,
            return_response=True,
        )

    assert projector.commands == []


async def test_action_with_a_value_containing_a_line_break(
    hass: HomeAssistant,
    freezer: FrozenDateTimeFactory,
    mock_config_entry: MockConfigEntry,
    projector: EmulatedProjector,
) -> None:
    """Test the library refuses a value that would start a second command."""
    await _setup(hass, mock_config_entry, freezer)
    projector.commands.clear()

    with pytest.raises(ServiceValidationError) as excinfo:
        await hass.services.async_call(
            DOMAIN,
            "set_value",
            {
                ATTR_ENTITY_ID: ENTITY_ID,
                "key": "projectorname",
                "value": "a\rset volume=20",
            },
            blocking=True,
        )

    assert excinfo.value.translation_key == "invalid_value"
    assert projector.commands == []


async def test_actions_need_the_projector_on(
    hass: HomeAssistant,
    freezer: FrozenDateTimeFactory,
    mock_config_entry: MockConfigEntry,
    projector: EmulatedProjector,
) -> None:
    """Test the raw actions are refused while the projector is off."""
    await _setup(hass, mock_config_entry, freezer)
    projector.power = "Idle"
    await async_tick(hass, freezer)

    for service, data in (
        ("get_value", {"key": "brightness"}),
        ("set_value", {"key": "brightness", "value": "1"}),
        ("adjust_value", {"key": "brightness", "delta": 1}),
    ):
        with pytest.raises(ServiceValidationError) as excinfo:
            await hass.services.async_call(
                DOMAIN,
                service,
                {ATTR_ENTITY_ID: ENTITY_ID, **data},
                blocking=True,
                return_response=service == "get_value",
            )
        assert excinfo.value.translation_key == "device_off"
