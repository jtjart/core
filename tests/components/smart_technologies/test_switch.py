"""Test the SMART Technologies switch platform."""

from freezegun.api import FrozenDateTimeFactory
import pytest
from syrupy.assertion import SnapshotAssertion

from homeassistant.components.switch import DOMAIN as SWITCH_DOMAIN
from homeassistant.const import (
    ATTR_ENTITY_ID,
    SERVICE_TURN_OFF,
    SERVICE_TURN_ON,
    STATE_OFF,
    STATE_ON,
    STATE_UNAVAILABLE,
    Platform,
)
from homeassistant.core import HomeAssistant
import homeassistant.helpers.entity_registry as er

from . import async_tick, entity_id, setup_integration
from .conftest import EmulatedProjector

from tests.common import MockConfigEntry, snapshot_platform


async def _setup(
    hass: HomeAssistant, entry: MockConfigEntry, freezer: FrozenDateTimeFactory
) -> None:
    await setup_integration(hass, entry, freezer, [Platform.SWITCH])


@pytest.mark.usefixtures("entity_registry_enabled_by_default")
async def test_switches(
    hass: HomeAssistant,
    freezer: FrozenDateTimeFactory,
    snapshot: SnapshotAssertion,
    entity_registry: er.EntityRegistry,
    mock_config_entry: MockConfigEntry,
) -> None:
    """Test the switch entities."""
    await _setup(hass, mock_config_entry, freezer)
    await snapshot_platform(hass, entity_registry, snapshot, mock_config_entry.entry_id)


@pytest.mark.usefixtures("entity_registry_enabled_by_default")
@pytest.mark.parametrize(
    ("key", "setting"),
    [
        ("video_mute", "videomute"),
        ("video_freeze", "videofreeze"),
        ("high_brightness", "highbrightness"),
        ("auto_signal", "autosignal"),
        ("lamp_reminder", "lampreminder"),
        ("volume_control", "volumecontrol"),
        ("dhcp", "dhcp"),
        ("vga_out_and_network_enabled", "vgaoutnetenable"),
    ],
)
async def test_turn_on_and_off(
    hass: HomeAssistant,
    freezer: FrozenDateTimeFactory,
    mock_config_entry: MockConfigEntry,
    projector: EmulatedProjector,
    key: str,
    setting: str,
) -> None:
    """Test each switch writes on/off and shows what the projector confirms."""
    await _setup(hass, mock_config_entry, freezer)
    target = entity_id("switch", key)
    assert hass.states.get(target).state == STATE_OFF

    await hass.services.async_call(
        SWITCH_DOMAIN, SERVICE_TURN_ON, {ATTR_ENTITY_ID: target}, blocking=True
    )
    assert projector.values[setting] == "on"
    assert hass.states.get(target).state == STATE_ON

    await hass.services.async_call(
        SWITCH_DOMAIN, SERVICE_TURN_OFF, {ATTR_ENTITY_ID: target}, blocking=True
    )
    assert projector.values[setting] == "off"
    assert hass.states.get(target).state == STATE_OFF


async def test_state_follows_changes_made_at_the_projector(
    hass: HomeAssistant,
    freezer: FrozenDateTimeFactory,
    mock_config_entry: MockConfigEntry,
    projector: EmulatedProjector,
) -> None:
    """Test freezing the picture with the remote is noticed."""
    await _setup(hass, mock_config_entry, freezer)
    freeze = entity_id("switch", "video_freeze")
    assert hass.states.get(freeze).state == STATE_OFF

    projector.values["videofreeze"] = "on"
    await async_tick(hass, freezer)

    assert hass.states.get(freeze).state == STATE_ON


async def test_unavailable_when_the_projector_is_off(
    hass: HomeAssistant,
    freezer: FrozenDateTimeFactory,
    mock_config_entry: MockConfigEntry,
    projector: EmulatedProjector,
) -> None:
    """Test the switches cannot be used while the projector is off."""
    await _setup(hass, mock_config_entry, freezer)

    projector.power = "Idle"
    await async_tick(hass, freezer)

    assert hass.states.get(entity_id("switch", "video_mute")).state == STATE_UNAVAILABLE
