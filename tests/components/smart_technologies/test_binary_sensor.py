"""Test the SMART Technologies binary sensor platform."""

from freezegun.api import FrozenDateTimeFactory
from syrupy.assertion import SnapshotAssertion

from homeassistant.const import STATE_OFF, STATE_ON, Platform
from homeassistant.core import HomeAssistant
import homeassistant.helpers.entity_registry as er

from . import async_tick, entity_id, setup_integration
from .conftest import EmulatedProjector

from tests.common import MockConfigEntry, snapshot_platform


async def test_binary_sensors(
    hass: HomeAssistant,
    freezer: FrozenDateTimeFactory,
    snapshot: SnapshotAssertion,
    entity_registry: er.EntityRegistry,
    mock_config_entry: MockConfigEntry,
) -> None:
    """Test the binary sensor entities."""
    await setup_integration(hass, mock_config_entry, freezer, [Platform.BINARY_SENSOR])
    await snapshot_platform(hass, entity_registry, snapshot, mock_config_entry.entry_id)


async def test_signal_detected_follows_the_projector(
    hass: HomeAssistant,
    freezer: FrozenDateTimeFactory,
    mock_config_entry: MockConfigEntry,
    projector: EmulatedProjector,
) -> None:
    """Test a source being plugged in or switched off is noticed."""
    await setup_integration(hass, mock_config_entry, freezer, [Platform.BINARY_SENSOR])
    signal = entity_id("binary_sensor", "signal_detected")
    assert hass.states.get(signal).state == STATE_ON

    projector.values["signaldetected"] = "false"
    await async_tick(hass, freezer)

    assert hass.states.get(signal).state == STATE_OFF
