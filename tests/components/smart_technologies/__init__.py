"""Tests for the SMART Technologies integration."""

from datetime import timedelta
import json
from pathlib import Path
from unittest.mock import patch

from freezegun.api import FrozenDateTimeFactory

from homeassistant.components.smart_technologies.const import DOMAIN
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.util import slugify

from tests.common import MockConfigEntry, async_fire_time_changed


async def async_settle(hass: HomeAssistant, freezer: FrozenDateTimeFactory) -> None:
    """Let the coordinator read the settings that entities asked for.

    Entities ask for their settings as they are added; the coordinator waits a
    moment so the requests of all entities become a single refresh.
    """
    freezer.tick(timedelta(seconds=2))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()


async def setup_integration(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    freezer: FrozenDateTimeFactory,
    platforms: list[Platform] | None = None,
) -> None:
    """Set up the integration (optionally only some platforms) and read the settings."""
    config_entry.add_to_hass(hass)

    if platforms is None:
        await hass.config_entries.async_setup(config_entry.entry_id)
    else:
        with patch("homeassistant.components.smart_technologies.PLATFORMS", platforms):
            await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()
    await async_settle(hass, freezer)


async def async_tick(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory, seconds: float = 30
) -> None:
    """Advance time and let the coordinator run its scheduled update."""
    freezer.tick(timedelta(seconds=seconds))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()


def entity_id(platform: str, key: str) -> str:
    """Return the entity id of an entity, derived from its translated name."""
    strings = json.loads(
        (
            Path(__file__).parents[3]
            / "homeassistant/components"
            / DOMAIN
            / "strings.json"
        ).read_text()
    )
    name = strings["entity"][platform][key]["name"]
    return f"{platform}.smart_ux60_{slugify(name)}"
