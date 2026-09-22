"""Test the SMART Technologies diagnostics."""

from freezegun.api import FrozenDateTimeFactory
import pytest
from syrupy.assertion import SnapshotAssertion
from syrupy.filters import props

from homeassistant.core import HomeAssistant

from . import setup_integration

from tests.common import MockConfigEntry
from tests.components.diagnostics import get_diagnostics_for_config_entry
from tests.typing import ClientSessionGenerator


@pytest.mark.usefixtures("entity_registry_enabled_by_default")
async def test_diagnostics(
    hass: HomeAssistant,
    hass_client: ClientSessionGenerator,
    freezer: FrozenDateTimeFactory,
    snapshot: SnapshotAssertion,
    mock_config_entry: MockConfigEntry,
) -> None:
    """Test the diagnostics, with everything private redacted."""
    await setup_integration(hass, mock_config_entry, freezer)

    diagnostics = await get_diagnostics_for_config_entry(
        hass, hass_client, mock_config_entry
    )

    assert diagnostics == snapshot(
        exclude=props("entry_id", "created_at", "modified_at")
    )
    private = ("S123456789", "00:11:22:33:44:55", "192.168.1.10")
    assert not any(value in str(diagnostics) for value in private)
