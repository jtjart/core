"""Test the SMART Technologies select platform."""

from freezegun.api import FrozenDateTimeFactory
import pytest
from syrupy.assertion import SnapshotAssertion

from homeassistant.components.select import (
    ATTR_OPTION,
    ATTR_OPTIONS,
    DOMAIN as SELECT_DOMAIN,
    SERVICE_SELECT_OPTION,
)
from homeassistant.const import ATTR_ENTITY_ID, STATE_UNKNOWN, Platform
from homeassistant.core import HomeAssistant
import homeassistant.helpers.entity_registry as er

from . import async_tick, entity_id, setup_integration
from .conftest import EmulatedProjector

from tests.common import MockConfigEntry, snapshot_platform

DISPLAY_MODE = "select.smart_ux60_display_mode"
USB1 = "select.smart_ux60_usb_1_source"
USB2 = "select.smart_ux60_usb_2_source"


async def _setup(
    hass: HomeAssistant, entry: MockConfigEntry, freezer: FrozenDateTimeFactory
) -> None:
    await setup_integration(hass, entry, freezer, [Platform.SELECT])


@pytest.mark.usefixtures("entity_registry_enabled_by_default")
async def test_selects(
    hass: HomeAssistant,
    freezer: FrozenDateTimeFactory,
    snapshot: SnapshotAssertion,
    entity_registry: er.EntityRegistry,
    mock_config_entry: MockConfigEntry,
) -> None:
    """Test the select entities."""
    await _setup(hass, mock_config_entry, freezer)
    await snapshot_platform(hass, entity_registry, snapshot, mock_config_entry.entry_id)


@pytest.mark.usefixtures("entity_registry_enabled_by_default")
@pytest.mark.parametrize(
    ("key", "setting", "option", "raw"),
    [
        ("display_mode", "displaymode", "darkroom", "darkroom"),
        ("display_mode", "displaymode", "srgb", "sRGB"),  # exact casing on the wire
        ("display_mode", "displaymode", "smartpresentation", "SMARTpresentation"),
        ("aspect_ratio", "aspectratio", "r16_9", "16:9"),
        ("projection_mode", "projectionmode", "rear_ceiling", "rear ceiling"),
        ("language", "language", "portuguese_brazil", "Portuguese (Brazil)"),
        ("closed_captioning", "cc", "cc2", "cc2"),
        ("startup_screen", "startupscreen", "usercapture", "usercapture"),
    ],
)
async def test_select_option(
    hass: HomeAssistant,
    freezer: FrozenDateTimeFactory,
    mock_config_entry: MockConfigEntry,
    projector: EmulatedProjector,
    key: str,
    setting: str,
    option: str,
    raw: str,
) -> None:
    """Test choosing an option sends the projector's own spelling of it."""
    await _setup(hass, mock_config_entry, freezer)

    await hass.services.async_call(
        SELECT_DOMAIN,
        SERVICE_SELECT_OPTION,
        {ATTR_ENTITY_ID: entity_id("select", key), ATTR_OPTION: option},
        blocking=True,
    )

    assert projector.values[setting] == raw
    assert hass.states.get(entity_id("select", key)).state == option


async def test_replies_are_matched_case_insensitively(
    hass: HomeAssistant,
    freezer: FrozenDateTimeFactory,
    mock_config_entry: MockConfigEntry,
    projector: EmulatedProjector,
) -> None:
    """Test the projector's inconsistent capitalisation does not matter."""
    projector.values["displaymode"] = "DARKROOM"

    await _setup(hass, mock_config_entry, freezer)

    assert hass.states.get(DISPLAY_MODE).state == "darkroom"


@pytest.mark.usefixtures("entity_registry_enabled_by_default")
async def test_usb_source_options_come_from_the_projector(
    hass: HomeAssistant,
    freezer: FrozenDateTimeFactory,
    mock_config_entry: MockConfigEntry,
    projector: EmulatedProjector,
) -> None:
    """Test the USB routing offers exactly the inputs this projector has."""
    await _setup(hass, mock_config_entry, freezer)

    state = hass.states.get(USB1)
    assert state.attributes[ATTR_OPTIONS] == ["disabled", "vga1", "hdmi1", "hdmi2"]
    assert state.state == "disabled"
    assert hass.states.get(USB2).state == "hdmi1"

    await hass.services.async_call(
        SELECT_DOMAIN,
        SERVICE_SELECT_OPTION,
        {ATTR_ENTITY_ID: USB1, ATTR_OPTION: "vga1"},
        blocking=True,
    )
    assert projector.values["usb1source"] == "vga1"
    assert hass.states.get(USB1).state == "vga1"

    await hass.services.async_call(
        SELECT_DOMAIN,
        SERVICE_SELECT_OPTION,
        {ATTR_ENTITY_ID: USB1, ATTR_OPTION: "disabled"},
        blocking=True,
    )
    assert projector.values["usb1source"] == "disabled"
    assert hass.states.get(USB1).state == "disabled"


@pytest.mark.usefixtures("entity_registry_enabled_by_default")
async def test_usb_source_routed_to_an_input_that_is_not_listed(
    hass: HomeAssistant,
    freezer: FrozenDateTimeFactory,
    mock_config_entry: MockConfigEntry,
    projector: EmulatedProjector,
) -> None:
    """Test the current routing is always a valid option."""
    projector.values["usb1source"] = "displayport"

    await _setup(hass, mock_config_entry, freezer)

    state = hass.states.get(USB1)
    assert state.state == "displayport"
    assert "displayport" in state.attributes[ATTR_OPTIONS]


@pytest.mark.usefixtures("entity_registry_enabled_by_default")
async def test_usb_source_unknown_when_it_cannot_be_read(
    hass: HomeAssistant,
    freezer: FrozenDateTimeFactory,
    mock_config_entry: MockConfigEntry,
    projector: EmulatedProjector,
) -> None:
    """Test an unreadable routing is unknown rather than wrongly "disabled"."""
    del projector.values["usb1source"]

    await _setup(hass, mock_config_entry, freezer)

    assert hass.states.get(USB1).state == STATE_UNKNOWN


async def test_display_mode_is_polled_often(
    hass: HomeAssistant,
    freezer: FrozenDateTimeFactory,
    mock_config_entry: MockConfigEntry,
    projector: EmulatedProjector,
) -> None:
    """Test a change made with the remote shows up at the next regular poll."""
    await _setup(hass, mock_config_entry, freezer)

    projector.values["displaymode"] = "darkroom"
    await async_tick(hass, freezer)

    assert hass.states.get(DISPLAY_MODE).state == "darkroom"
