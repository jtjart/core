"""Test the SMART Technologies text platform."""

from freezegun.api import FrozenDateTimeFactory
import pytest
from syrupy.assertion import SnapshotAssertion

from homeassistant.components.text import (
    ATTR_VALUE,
    DOMAIN as TEXT_DOMAIN,
    SERVICE_SET_VALUE,
)
from homeassistant.const import ATTR_ENTITY_ID, Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError
import homeassistant.helpers.entity_registry as er

from . import entity_id, setup_integration
from .conftest import EmulatedProjector

from tests.common import MockConfigEntry, snapshot_platform


async def _setup(
    hass: HomeAssistant, entry: MockConfigEntry, freezer: FrozenDateTimeFactory
) -> None:
    await setup_integration(hass, entry, freezer, [Platform.TEXT])


@pytest.mark.usefixtures("entity_registry_enabled_by_default")
async def test_texts(
    hass: HomeAssistant,
    freezer: FrozenDateTimeFactory,
    snapshot: SnapshotAssertion,
    entity_registry: er.EntityRegistry,
    mock_config_entry: MockConfigEntry,
) -> None:
    """Test the text entities."""
    await _setup(hass, mock_config_entry, freezer)
    await snapshot_platform(hass, entity_registry, snapshot, mock_config_entry.entry_id)


@pytest.mark.usefixtures("entity_registry_enabled_by_default")
@pytest.mark.parametrize(
    ("key", "setting", "value"),
    [
        ("group_name", "groupname", "Room 101"),
        ("projector_name", "projectorname", "Front"),
        ("location_info", "locationinfo", "Second floor"),
        ("contact_info", "contactinfo", "help@example.com"),
        ("ip_address", "ipaddr", "10.0.0.5"),
        ("subnet_mask", "subnetmask", "255.255.255.0"),
        ("gateway", "gateway", "10.0.0.1"),
        ("primary_dns", "primarydns", "9.9.9.9"),
    ],
)
async def test_set_value(
    hass: HomeAssistant,
    freezer: FrozenDateTimeFactory,
    mock_config_entry: MockConfigEntry,
    projector: EmulatedProjector,
    key: str,
    setting: str,
    value: str,
) -> None:
    """Test names and network addresses can be changed."""
    await _setup(hass, mock_config_entry, freezer)

    await hass.services.async_call(
        TEXT_DOMAIN,
        SERVICE_SET_VALUE,
        {ATTR_ENTITY_ID: entity_id("text", key), ATTR_VALUE: value},
        blocking=True,
    )

    assert projector.values[setting] == value
    assert hass.states.get(entity_id("text", key)).state == value


@pytest.mark.usefixtures("entity_registry_enabled_by_default")
async def test_limits(
    hass: HomeAssistant,
    freezer: FrozenDateTimeFactory,
    mock_config_entry: MockConfigEntry,
    projector: EmulatedProjector,
) -> None:
    """Test length limits from the library and the address pattern are enforced."""
    await _setup(hass, mock_config_entry, freezer)
    projector.commands.clear()

    for key, value in (("group_name", "x" * 13), ("ip_address", "not an address")):
        with pytest.raises(ValueError):
            await hass.services.async_call(
                TEXT_DOMAIN,
                SERVICE_SET_VALUE,
                {ATTR_ENTITY_ID: entity_id("text", key), ATTR_VALUE: value},
                blocking=True,
            )

    assert projector.commands == []


@pytest.mark.usefixtures("entity_registry_enabled_by_default")
async def test_address_that_looks_right_but_is_not(
    hass: HomeAssistant,
    freezer: FrozenDateTimeFactory,
    mock_config_entry: MockConfigEntry,
    projector: EmulatedProjector,
) -> None:
    """Test 999.1.1.1 passes the pattern but the library still refuses it."""
    await _setup(hass, mock_config_entry, freezer)
    projector.commands.clear()

    with pytest.raises(ServiceValidationError) as excinfo:
        await hass.services.async_call(
            TEXT_DOMAIN,
            SERVICE_SET_VALUE,
            {ATTR_ENTITY_ID: entity_id("text", "gateway"), ATTR_VALUE: "999.1.1.1"},
            blocking=True,
        )

    assert excinfo.value.translation_key == "invalid_value"
    assert projector.commands == []
