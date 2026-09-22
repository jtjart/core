"""Test the SMART Technologies number platform."""

from freezegun.api import FrozenDateTimeFactory
import pytest
from smart_serial import UnexpectedResponseError
from syrupy.assertion import SnapshotAssertion

from homeassistant.components.number import (
    ATTR_VALUE,
    DOMAIN as NUMBER_DOMAIN,
    SERVICE_SET_VALUE,
)
from homeassistant.const import ATTR_ENTITY_ID, STATE_UNAVAILABLE, Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
import homeassistant.helpers.entity_registry as er

from . import async_tick, entity_id, setup_integration
from .conftest import EmulatedProjector

from tests.common import MockConfigEntry, snapshot_platform

BRIGHTNESS = "number.smart_ux60_brightness"


async def _setup(
    hass: HomeAssistant, entry: MockConfigEntry, freezer: FrozenDateTimeFactory
) -> None:
    await setup_integration(hass, entry, freezer, [Platform.NUMBER])


@pytest.mark.usefixtures("entity_registry_enabled_by_default")
async def test_numbers(
    hass: HomeAssistant,
    freezer: FrozenDateTimeFactory,
    snapshot: SnapshotAssertion,
    entity_registry: er.EntityRegistry,
    mock_config_entry: MockConfigEntry,
) -> None:
    """Test the number entities."""
    await _setup(hass, mock_config_entry, freezer)
    await snapshot_platform(hass, entity_registry, snapshot, mock_config_entry.entry_id)


async def test_only_popular_numbers_are_enabled_by_default(
    hass: HomeAssistant,
    freezer: FrozenDateTimeFactory,
    entity_registry: er.EntityRegistry,
    mock_config_entry: MockConfigEntry,
) -> None:
    """Test the fine-tuning entities are opt-in."""
    await _setup(hass, mock_config_entry, freezer)

    enabled = {
        entry.entity_id
        for entry in er.async_entries_for_config_entry(
            entity_registry, mock_config_entry.entry_id
        )
        if not entry.disabled_by
    }
    assert enabled == {
        BRIGHTNESS,
        "number.smart_ux60_contrast",
        "number.smart_ux60_auto_power_off_timer",
    }


@pytest.mark.usefixtures("entity_registry_enabled_by_default")
@pytest.mark.parametrize(
    ("key", "setting", "value"),
    [
        ("brightness", "brightness", 70),
        ("contrast", "contrast", 12),
        ("auto_power_off", "autopoweroff", 30),
        ("white_peaking", "whitepeaking", 4),
        ("red", "red", 99),
        ("frequency", "frequency", -3),
        ("vertical_position", "vposition", -2),
        ("projector_id", "projectorid", 7),
    ],
)
async def test_set_value(
    hass: HomeAssistant,
    freezer: FrozenDateTimeFactory,
    mock_config_entry: MockConfigEntry,
    projector: EmulatedProjector,
    key: str,
    setting: str,
    value: int,
) -> None:
    """Test changing a setting writes it, and shows the value the projector confirms."""
    projector.values["input"] = "vga1"  # so VGA-only settings can be read
    await _setup(hass, mock_config_entry, freezer)

    await hass.services.async_call(
        NUMBER_DOMAIN,
        SERVICE_SET_VALUE,
        {ATTR_ENTITY_ID: entity_id("number", key), ATTR_VALUE: value},
        blocking=True,
    )

    assert projector.values[setting] == str(value)
    assert hass.states.get(entity_id("number", key)).state == str(value)


async def test_limits_come_from_the_library(
    hass: HomeAssistant,
    freezer: FrozenDateTimeFactory,
    mock_config_entry: MockConfigEntry,
    projector: EmulatedProjector,
) -> None:
    """Test values outside the projector's range never reach the serial line."""
    await _setup(hass, mock_config_entry, freezer)
    projector.commands.clear()

    with pytest.raises(ServiceValidationError):
        await hass.services.async_call(
            NUMBER_DOMAIN,
            SERVICE_SET_VALUE,
            {ATTR_ENTITY_ID: BRIGHTNESS, ATTR_VALUE: 101},
            blocking=True,
        )

    assert not [c for c in projector.commands if c.startswith("set")]
    state = hass.states.get(BRIGHTNESS)
    assert (state.attributes["min"], state.attributes["max"]) == (0, 100)


async def test_unavailable_when_the_projector_is_off(
    hass: HomeAssistant,
    freezer: FrozenDateTimeFactory,
    mock_config_entry: MockConfigEntry,
    projector: EmulatedProjector,
) -> None:
    """Test the entity cannot be used while the projector is off."""
    await _setup(hass, mock_config_entry, freezer)

    projector.power = "Cooling"
    await async_tick(hass, freezer)

    assert hass.states.get(BRIGHTNESS).state == STATE_UNAVAILABLE


async def test_failed_write_is_reported(
    hass: HomeAssistant,
    freezer: FrozenDateTimeFactory,
    mock_config_entry: MockConfigEntry,
    projector: EmulatedProjector,
) -> None:
    """Test a failed write raises a translated error and keeps the old value."""
    await _setup(hass, mock_config_entry, freezer)
    projector.faults.append(UnexpectedResponseError("set brightness=70", "garbage"))

    with pytest.raises(HomeAssistantError) as excinfo:
        await hass.services.async_call(
            NUMBER_DOMAIN,
            SERVICE_SET_VALUE,
            {ATTR_ENTITY_ID: BRIGHTNESS, ATTR_VALUE: 70},
            blocking=True,
        )

    assert excinfo.value.translation_key == "command_failed"
    assert hass.states.get(BRIGHTNESS).state == "50"
