"""Guards that keep the integration, its translations and the library in step."""

import json
from pathlib import Path
import re

from freezegun.api import FrozenDateTimeFactory
import pytest
from smart_serial import SmartUX60
from smart_serial.devices.settings import BoundSetting

from homeassistant.components.smart_technologies import (
    binary_sensor,
    button,
    media_player,
    number,
    select,
    sensor,
    switch,
    text,
)
from homeassistant.components.smart_technologies.const import DOMAIN, enum_option
from homeassistant.core import HomeAssistant

from . import setup_integration
from .conftest import EmulatedProjector, EmulatedTransport

from tests.common import MockConfigEntry

INTEGRATION = Path(__file__).parents[3] / "homeassistant/components" / DOMAIN
STRINGS = json.loads((INTEGRATION / "strings.json").read_text())
ICONS = json.loads((INTEGRATION / "icons.json").read_text())

DESCRIPTIONS = {
    "binary_sensor": binary_sensor.BINARY_SENSORS,
    "button": button.BUTTONS,
    "number": number.NUMBERS,
    "select": (*select.SELECTS, *select.USB_SOURCES),
    "sensor": sensor.SENSORS,
    "switch": switch.SWITCHES,
    "text": text.TEXTS,
}
# Settings the media player entity covers itself.
MEDIA_PLAYER_KEYS = {
    media_player.KEY_INPUT,
    media_player.KEY_VIDEO_INPUTS,
    media_player.KEY_VOLUME,
    media_player.KEY_MUTE,
}


def _entity_keys() -> set[str]:
    """Return the setting keys that some entity covers."""
    keys = set(MEDIA_PLAYER_KEYS)
    for platform, descriptions in DESCRIPTIONS.items():
        if platform != "button":  # buttons run commands; they are not settings
            keys |= {description.key for description in descriptions}
    return keys


def test_every_setting_of_the_library_has_an_entity() -> None:
    """Test nothing the library can do is left out, and nothing points at a missing setting.

    When the library gains a setting, this test fails until an entity is added.
    """
    library = set(SmartUX60.settings())

    assert library - _entity_keys() == set(), "settings without an entity"
    assert _entity_keys() - library == set(), "entities for settings that do not exist"


def test_every_library_command_has_a_button_or_action() -> None:
    """Test the commands that are not settings are exposed too."""
    assert {description.key for description in button.BUTTONS} == {
        "power_off_now",
        "power_off_low_power",
        "reset_lamp_hours",
        "restore_defaults",
    }


@pytest.mark.usefixtures("entity_registry_enabled_by_default")
async def test_entities_read_the_setting_they_are_named_after(
    hass: HomeAssistant,
    freezer: FrozenDateTimeFactory,
    mock_config_entry: MockConfigEntry,
    projector: EmulatedProjector,
) -> None:
    """Test no accessor points at the wrong attribute of the library."""
    await setup_integration(hass, mock_config_entry, freezer)
    coordinator = mock_config_entry.runtime_data
    device = SmartUX60(EmulatedTransport(projector, "x"))
    library = SmartUX60.settings()

    assert set(coordinator.tracked_keys) == set(library) - {"power_state"}
    for key in coordinator.tracked_keys:
        accessor = coordinator._tracked[key][0].accessor
        assert accessor(device).spec is library[key], key


def test_writable_entities_use_writable_settings() -> None:
    """Test entities that write are wired to settings that can be written."""
    device = SmartUX60(EmulatedTransport(EmulatedProjector(), "x"))
    for description in (
        *number.NUMBERS,
        *switch.SWITCHES,
        *select.SELECTS,
        *select.USB_SOURCES,
        *text.TEXTS,
    ):
        assert isinstance(description.setting(device), BoundSetting), description.key


def test_number_limits_are_the_libraries() -> None:
    """Test the limits shown in Home Assistant cannot drift from the projector's."""
    library = SmartUX60.settings()
    for description in number.NUMBERS:
        bounds = library[description.key].bounds
        assert description.native_min_value == bounds.start
        assert description.native_max_value == bounds.stop - 1


def test_text_limits_are_the_libraries() -> None:
    """Test the text length limits are the library's."""
    library = SmartUX60.settings()
    for description in text.TEXTS:
        if (limit := getattr(library[description.key], "max_length", None)) is not None:
            assert description.native_max == limit


@pytest.mark.parametrize(
    "description",
    select.SELECTS,
    ids=lambda description: description.key,
)
def test_select_options_map_back_to_enum_members(
    description: select.SmartSelectDescription,
) -> None:
    """Test every option is unique and converts back to its enum member."""
    assert description.options is not None
    assert len(set(description.options)) == len(description.options)
    for option in description.options:
        member = description.enum[option.upper()]
        assert enum_option(member) == option
    assert set(description.options) == {enum_option(m) for m in description.enum}
    # The library setting accepts exactly this enum.
    assert SmartUX60.settings()[description.key].enum is description.enum


# ------------------------------------------------------------------------ translations


@pytest.mark.parametrize("platform", DESCRIPTIONS)
def test_every_entity_is_translated(platform: str) -> None:
    """Test every entity has a name, and no name is left over."""
    used = {description.translation_key for description in DESCRIPTIONS[platform]}
    assert used == set(STRINGS["entity"][platform])


@pytest.mark.parametrize("platform", ["select", "sensor"])
def test_every_option_is_translated(platform: str) -> None:
    """Test every state of an enum entity is translated."""
    for description in DESCRIPTIONS[platform]:
        options = getattr(description, "options", None)
        if options:
            translated = STRINGS["entity"][platform][description.translation_key][
                "state"
            ]
            assert set(options) == set(translated), description.key


@pytest.mark.parametrize("platform", DESCRIPTIONS)
def test_every_entity_has_an_icon_unless_its_device_class_provides_one(
    platform: str,
) -> None:
    """Test entities show a meaningful icon."""
    for description in DESCRIPTIONS[platform]:
        if description.device_class is None or description.key == "power_state":
            assert description.translation_key in ICONS["entity"][platform], (
                description.key
            )


def test_every_error_the_code_can_raise_is_translated() -> None:
    """Test each translation key used for an exception exists."""
    used: set[str] = set()
    for path in INTEGRATION.glob("*.py"):
        used |= set(
            re.findall(
                r'translation_domain=DOMAIN,\s*translation_key="(\w+)"',
                path.read_text(),
            )
        )
    assert used <= set(STRINGS["exceptions"])
    assert "cannot_connect" in used
    assert set(STRINGS["exceptions"]) <= used


def test_only_documented_enum_members_are_translated() -> None:
    """Test states that no longer exist in the library do not linger in the strings."""
    known = {enum_option(member) for member in SmartUX60.display_mode.enum}
    assert set(STRINGS["entity"]["select"]["display_mode"]["state"]) == known
