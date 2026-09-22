"""Test the SMART Technologies button platform."""

from freezegun.api import FrozenDateTimeFactory
import pytest
from smart_serial import UnexpectedResponseError
from syrupy.assertion import SnapshotAssertion

from homeassistant.components.button import DOMAIN as BUTTON_DOMAIN, SERVICE_PRESS
from homeassistant.const import ATTR_ENTITY_ID, STATE_UNAVAILABLE, Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
import homeassistant.helpers.entity_registry as er

from . import async_settle, async_tick, entity_id, setup_integration
from .conftest import EmulatedProjector

from tests.common import MockConfigEntry, snapshot_platform


async def _press(hass: HomeAssistant, key: str) -> None:
    await hass.services.async_call(
        BUTTON_DOMAIN,
        SERVICE_PRESS,
        {ATTR_ENTITY_ID: entity_id("button", key)},
        blocking=True,
    )


@pytest.mark.usefixtures("entity_registry_enabled_by_default")
async def test_buttons(
    hass: HomeAssistant,
    freezer: FrozenDateTimeFactory,
    snapshot: SnapshotAssertion,
    entity_registry: er.EntityRegistry,
    mock_config_entry: MockConfigEntry,
) -> None:
    """Test the button entities."""
    await setup_integration(hass, mock_config_entry, freezer, [Platform.BUTTON])
    await snapshot_platform(hass, entity_registry, snapshot, mock_config_entry.entry_id)


@pytest.mark.usefixtures("entity_registry_enabled_by_default")
@pytest.mark.parametrize(
    ("key", "command"),
    [("power_off_now", "off now"), ("power_off_low_power", "off low power")],
)
async def test_power_off_buttons(
    hass: HomeAssistant,
    freezer: FrozenDateTimeFactory,
    mock_config_entry: MockConfigEntry,
    projector: EmulatedProjector,
    key: str,
    command: str,
) -> None:
    """Test the immediate power-off variants, with no confirmation step."""
    await setup_integration(
        hass, mock_config_entry, freezer, [Platform.BUTTON, Platform.MEDIA_PLAYER]
    )

    await _press(hass, key)

    assert command in projector.commands
    assert "off" not in projector.commands
    assert projector.power == "Cooling"
    assert hass.states.get("media_player.smart_ux60").state == "off"


@pytest.mark.usefixtures("entity_registry_enabled_by_default")
async def test_reset_lamp_hours(
    hass: HomeAssistant,
    freezer: FrozenDateTimeFactory,
    mock_config_entry: MockConfigEntry,
    projector: EmulatedProjector,
) -> None:
    """Test resetting the lamp counter shows up without waiting for a slow poll."""
    await setup_integration(
        hass, mock_config_entry, freezer, [Platform.BUTTON, Platform.SENSOR]
    )
    lamp = entity_id("sensor", "lamp_hours")
    assert hass.states.get(lamp).state == "1234"

    await _press(hass, "reset_lamp_hours")
    await async_settle(hass, freezer)

    assert projector.values["lamphrs"] == "0"
    assert hass.states.get(lamp).state == "0"


@pytest.mark.usefixtures("entity_registry_enabled_by_default")
async def test_restore_defaults(
    hass: HomeAssistant,
    freezer: FrozenDateTimeFactory,
    mock_config_entry: MockConfigEntry,
    projector: EmulatedProjector,
) -> None:
    """Test a factory reset refreshes every setting that is shown."""
    projector.values["brightness"] = "80"
    await setup_integration(
        hass, mock_config_entry, freezer, [Platform.BUTTON, Platform.NUMBER]
    )
    brightness = entity_id("number", "brightness")
    assert hass.states.get(brightness).state == "80"

    await _press(hass, "restore_defaults")
    await async_settle(hass, freezer)

    assert "set restoredefaults" in projector.commands
    assert hass.states.get(brightness).state == "50"


@pytest.mark.usefixtures("entity_registry_enabled_by_default")
async def test_buttons_unavailable_when_the_projector_is_off(
    hass: HomeAssistant,
    freezer: FrozenDateTimeFactory,
    mock_config_entry: MockConfigEntry,
    projector: EmulatedProjector,
) -> None:
    """Test there is nothing to press while the projector is off."""
    await setup_integration(hass, mock_config_entry, freezer, [Platform.BUTTON])

    projector.power = "Idle"
    await async_tick(hass, freezer)

    assert (
        hass.states.get(entity_id("button", "power_off_now")).state == STATE_UNAVAILABLE
    )


@pytest.mark.usefixtures("entity_registry_enabled_by_default")
async def test_failed_press_is_reported(
    hass: HomeAssistant,
    freezer: FrozenDateTimeFactory,
    mock_config_entry: MockConfigEntry,
    projector: EmulatedProjector,
) -> None:
    """Test a failed command is reported to the user."""
    await setup_integration(hass, mock_config_entry, freezer, [Platform.BUTTON])
    projector.faults.append(UnexpectedResponseError("off now", "garbage"))

    with pytest.raises(HomeAssistantError) as excinfo:
        await _press(hass, "power_off_now")

    assert excinfo.value.translation_key == "command_failed"
