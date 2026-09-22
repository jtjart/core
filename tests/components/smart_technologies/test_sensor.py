"""Test the SMART Technologies sensor platform."""

from freezegun.api import FrozenDateTimeFactory
import pytest
from syrupy.assertion import SnapshotAssertion

from homeassistant.const import STATE_UNKNOWN, Platform
from homeassistant.core import HomeAssistant
import homeassistant.helpers.entity_registry as er

from . import async_tick, entity_id, setup_integration
from .conftest import EmulatedProjector

from tests.common import MockConfigEntry, snapshot_platform


async def _setup(
    hass: HomeAssistant, entry: MockConfigEntry, freezer: FrozenDateTimeFactory
) -> None:
    await setup_integration(hass, entry, freezer, [Platform.SENSOR])


@pytest.mark.usefixtures("entity_registry_enabled_by_default")
async def test_sensors(
    hass: HomeAssistant,
    freezer: FrozenDateTimeFactory,
    snapshot: SnapshotAssertion,
    entity_registry: er.EntityRegistry,
    mock_config_entry: MockConfigEntry,
) -> None:
    """Test the sensor entities."""
    await _setup(hass, mock_config_entry, freezer)
    await snapshot_platform(hass, entity_registry, snapshot, mock_config_entry.entry_id)


@pytest.mark.parametrize(
    ("power", "state"),
    [
        ("Powering", "powering"),
        ("On", "on"),
        ("Confirm off", "confirm_off"),
        ("Cooling", "cooling"),
        ("Idle", "idle"),
    ],
)
async def test_power_state(
    hass: HomeAssistant,
    freezer: FrozenDateTimeFactory,
    mock_config_entry: MockConfigEntry,
    projector: EmulatedProjector,
    power: str,
    state: str,
) -> None:
    """Test the detailed power state, e.g. to wait for the projector to cool down."""
    await _setup(hass, mock_config_entry, freezer)

    projector.power = power
    await async_tick(hass, freezer)

    assert hass.states.get(entity_id("sensor", "power_state")).state == state


async def test_only_useful_sensors_are_enabled_by_default(
    hass: HomeAssistant,
    freezer: FrozenDateTimeFactory,
    entity_registry: er.EntityRegistry,
    mock_config_entry: MockConfigEntry,
) -> None:
    """Test device information that duplicates the device page is opt-in."""
    await _setup(hass, mock_config_entry, freezer)

    enabled = {
        entry.entity_id
        for entry in er.async_entries_for_config_entry(
            entity_registry, mock_config_entry.entry_id
        )
        if not entry.disabled_by
    }
    assert enabled == {
        entity_id("sensor", "power_state"),
        entity_id("sensor", "lamp_hours"),
    }


@pytest.mark.usefixtures("entity_registry_enabled_by_default")
async def test_network_status_and_resolution_follow_the_projector(
    hass: HomeAssistant,
    freezer: FrozenDateTimeFactory,
    mock_config_entry: MockConfigEntry,
    projector: EmulatedProjector,
) -> None:
    """Test the live diagnostic values are refreshed."""
    await _setup(hass, mock_config_entry, freezer)
    resolution = entity_id("sensor", "resolution")
    assert hass.states.get(resolution).state == "1920x1080"

    projector.values["resolution"] = "1280x720"
    await async_tick(hass, freezer)

    assert hass.states.get(resolution).state == "1280x720"


@pytest.mark.usefixtures("entity_registry_enabled_by_default")
async def test_static_information_is_unknown_until_the_projector_is_on(
    hass: HomeAssistant,
    freezer: FrozenDateTimeFactory,
    mock_config_entry: MockConfigEntry,
    projector: EmulatedProjector,
) -> None:
    """Test a projector that is off at startup has nothing to show yet."""
    projector.power = "Idle"

    await _setup(hass, mock_config_entry, freezer)

    assert hass.states.get(entity_id("sensor", "lamp_hours")).state == STATE_UNKNOWN

    projector.power = "On"
    await async_tick(hass, freezer)

    assert hass.states.get(entity_id("sensor", "lamp_hours")).state == "1234"
