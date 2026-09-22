"""Test setup, polling and error handling of the SMART Technologies integration."""

from datetime import timedelta
import logging

from freezegun.api import FrozenDateTimeFactory
import pytest
from smart_serial import ConnectionFailedError, ConnectionLostError, SerialTimeoutError

from homeassistant.components.smart_technologies.const import (
    DOMAIN,
    ISSUE_THRESHOLD,
    SLOW_INTERVAL,
    UPDATE_INTERVAL,
)
from homeassistant.components.smart_technologies.coordinator import TrackedSetting
from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import STATE_OFF, STATE_ON, STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr, issue_registry as ir

from . import async_settle, async_tick, setup_integration
from .conftest import MOCK_SERIAL_NUMBER, EmulatedProjector

from tests.common import MockConfigEntry

MEDIA_PLAYER = "media_player.smart_ux60"


async def test_setup_and_unload(
    hass: HomeAssistant,
    freezer: FrozenDateTimeFactory,
    mock_config_entry: MockConfigEntry,
    projector: EmulatedProjector,
) -> None:
    """Test the entry loads, and unloading releases the serial port."""
    await setup_integration(hass, mock_config_entry, freezer)
    assert mock_config_entry.state is ConfigEntryState.LOADED
    assert hass.states.get(MEDIA_PLAYER).state == STATE_ON

    await hass.config_entries.async_unload(mock_config_entry.entry_id)

    assert mock_config_entry.state is ConfigEntryState.NOT_LOADED
    assert projector.connections == projector.disconnects == 1


async def test_setup_retries_when_the_port_cannot_be_opened(
    hass: HomeAssistant,
    freezer: FrozenDateTimeFactory,
    mock_config_entry: MockConfigEntry,
    projector: EmulatedProjector,
) -> None:
    """Test a missing serial port makes the setup retry."""
    projector.connect_error = ConnectionFailedError("/dev/ttyUSB0", "no such file")

    await setup_integration(hass, mock_config_entry, freezer)

    assert mock_config_entry.state is ConfigEntryState.SETUP_RETRY


async def test_setup_retries_when_the_projector_does_not_answer(
    hass: HomeAssistant,
    freezer: FrozenDateTimeFactory,
    mock_config_entry: MockConfigEntry,
    projector: EmulatedProjector,
) -> None:
    """Test a silent projector makes the setup retry and releases the port."""
    projector.offline = True

    await setup_integration(hass, mock_config_entry, freezer)

    assert mock_config_entry.state is ConfigEntryState.SETUP_RETRY
    assert projector.connections == projector.disconnects


async def test_device(
    hass: HomeAssistant,
    freezer: FrozenDateTimeFactory,
    device_registry: dr.DeviceRegistry,
    mock_config_entry: MockConfigEntry,
    projector: EmulatedProjector,
) -> None:
    """Test the device, and that firmware and MAC address follow the projector."""
    await setup_integration(hass, mock_config_entry, freezer)

    device = device_registry.async_get_device_by_identifier(
        (DOMAIN, MOCK_SERIAL_NUMBER), mock_config_entry.entry_id
    )
    assert device is not None
    assert device.manufacturer == "SMART Technologies"
    assert device.model == "UX60"
    assert device.name == "SMART UX60"
    assert device.serial_number == MOCK_SERIAL_NUMBER
    assert device.sw_version == "1.2.3"
    assert (dr.CONNECTION_NETWORK_MAC, "00:11:22:33:44:55") in device.connections

    projector.values["fwverddp"] = "9.9.9"
    await async_tick(hass, freezer, SLOW_INTERVAL.total_seconds())

    device = device_registry.async_get_device_by_identifier(
        (DOMAIN, MOCK_SERIAL_NUMBER), mock_config_entry.entry_id
    )
    assert device is not None
    assert device.sw_version == "9.9.9"


@pytest.mark.parametrize("mac", ["", "n/a", "abc"])
async def test_unusable_mac_address_is_not_a_connection(
    hass: HomeAssistant,
    freezer: FrozenDateTimeFactory,
    device_registry: dr.DeviceRegistry,
    mock_config_entry: MockConfigEntry,
    projector: EmulatedProjector,
    mac: str,
) -> None:
    """Test a blank or malformed MAC address does not become a bogus connection."""
    projector.values["macaddr"] = mac

    await setup_integration(hass, mock_config_entry, freezer)

    device = device_registry.async_get_device_by_identifier(
        (DOMAIN, MOCK_SERIAL_NUMBER), mock_config_entry.entry_id
    )
    assert device is not None
    assert not device.connections


async def test_only_needed_settings_are_polled(
    hass: HomeAssistant,
    freezer: FrozenDateTimeFactory,
    mock_config_entry: MockConfigEntry,
    projector: EmulatedProjector,
) -> None:
    """Test settings nobody uses are never requested from the slow serial line."""
    await setup_integration(hass, mock_config_entry, freezer)

    assert "get brightness" in projector.commands  # enabled entity
    assert "get input" in projector.commands  # media player
    assert "get red" not in projector.commands  # disabled by default
    assert "get serialnum" not in projector.commands
    assert set(mock_config_entry.runtime_data.tracked_keys) >= {
        "brightness",
        "input_source",
        "volume",
    }
    assert "red" not in mock_config_entry.runtime_data.tracked_keys


async def test_live_settings_are_polled_more_often_than_configuration(
    hass: HomeAssistant,
    freezer: FrozenDateTimeFactory,
    mock_config_entry: MockConfigEntry,
    projector: EmulatedProjector,
) -> None:
    """Test the polling tiers."""
    await setup_integration(hass, mock_config_entry, freezer)

    projector.commands.clear()
    await async_tick(hass, freezer, UPDATE_INTERVAL.total_seconds())
    assert "get powerstate" in projector.commands
    assert {"get input", "get volume", "get mute"} <= set(projector.commands)
    assert "get brightness" not in projector.commands

    projector.commands.clear()
    projector.values["brightness"] = "70"
    await async_tick(hass, freezer, SLOW_INTERVAL.total_seconds())
    assert "get brightness" in projector.commands
    assert hass.states.get("number.smart_ux60_brightness").state == "70"


@pytest.mark.usefixtures("entity_registry_enabled_by_default")
async def test_standby_is_polled_cheaply_and_entities_follow(
    hass: HomeAssistant,
    freezer: FrozenDateTimeFactory,
    mock_config_entry: MockConfigEntry,
    projector: EmulatedProjector,
) -> None:
    """Test only the power state is polled in standby, and availability follows it."""
    await setup_integration(hass, mock_config_entry, freezer)
    assert hass.states.get("number.smart_ux60_brightness").state == "50"

    projector.power = "Idle"
    projector.commands.clear()
    await async_tick(hass, freezer)

    assert projector.commands == ["get powerstate"]
    assert hass.states.get(MEDIA_PLAYER).state == STATE_OFF
    # Controls cannot be used while the projector is off...
    assert hass.states.get("number.smart_ux60_brightness").state == STATE_UNAVAILABLE
    assert hass.states.get("sensor.smart_ux60_power_state").state == "idle"
    # ...but static information keeps its last known value.
    assert (
        hass.states.get("sensor.smart_ux60_serial_number").state == MOCK_SERIAL_NUMBER
    )
    assert hass.states.get("sensor.smart_ux60_lamp_hours").state == "1234"


async def test_settings_are_reread_after_the_projector_comes_back(
    hass: HomeAssistant,
    freezer: FrozenDateTimeFactory,
    mock_config_entry: MockConfigEntry,
    projector: EmulatedProjector,
) -> None:
    """Test changes made with the remote while the projector was off are picked up."""
    await setup_integration(hass, mock_config_entry, freezer)
    projector.power = "Idle"
    await async_tick(hass, freezer)

    projector.values["brightness"] = "33"
    projector.power = "On"
    await async_tick(hass, freezer)

    assert hass.states.get("number.smart_ux60_brightness").state == "33"


@pytest.mark.usefixtures("entity_registry_enabled_by_default")
async def test_unsupported_setting_is_unknown_not_an_error(
    hass: HomeAssistant,
    freezer: FrozenDateTimeFactory,
    mock_config_entry: MockConfigEntry,
    projector: EmulatedProjector,
) -> None:
    """Test a VGA-only setting is unknown on HDMI and appears on VGA."""
    await setup_integration(hass, mock_config_entry, freezer)
    assert mock_config_entry.state is ConfigEntryState.LOADED
    assert hass.states.get("number.smart_ux60_frequency").state == STATE_UNKNOWN

    projector.values["input"] = "vga1"
    await async_tick(hass, freezer, SLOW_INTERVAL.total_seconds())

    assert hass.states.get("number.smart_ux60_frequency").state != STATE_UNKNOWN


@pytest.mark.usefixtures("entity_registry_enabled_by_default")
async def test_projector_going_to_standby_mid_poll(
    hass: HomeAssistant,
    freezer: FrozenDateTimeFactory,
    mock_config_entry: MockConfigEntry,
    projector: EmulatedProjector,
) -> None:
    """Test a projector that sleeps while being read is not an error.

    The update stops asking, so it neither hammers a projector that no longer
    answers nor forgets what it already knew.
    """
    await setup_integration(hass, mock_config_entry, freezer)
    lamp_hours = "sensor.smart_ux60_lamp_hours"
    assert hass.states.get(lamp_hours).state == "1234"

    projector.commands.clear()
    projector.idle_after = 3  # the power state, two settings, then standby
    await async_tick(hass, freezer, SLOW_INTERVAL.total_seconds())

    assert mock_config_entry.runtime_data.last_update_success
    # Three commands were answered; the next was rejected, the power state was
    # asked once more to see why, and the update stopped there.
    assert projector.commands.count("get powerstate") == 2
    assert len(projector.commands) == 5
    assert hass.states.get(lamp_hours).state == "1234"

    await async_tick(hass, freezer)
    assert hass.states.get(MEDIA_PLAYER).state == STATE_OFF


async def test_unavailable_is_logged_once_and_recovery_once(
    hass: HomeAssistant,
    freezer: FrozenDateTimeFactory,
    mock_config_entry: MockConfigEntry,
    projector: EmulatedProjector,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Test a lost projector does not flood the log."""
    await setup_integration(hass, mock_config_entry, freezer)
    caplog.set_level(logging.INFO)
    caplog.clear()

    projector.offline = True
    for _ in range(3):
        await async_tick(hass, freezer)
    assert hass.states.get(MEDIA_PLAYER).state == STATE_UNAVAILABLE
    assert hass.states.get("number.smart_ux60_brightness").state == STATE_UNAVAILABLE
    errors = [r for r in caplog.records if r.levelno >= logging.ERROR]
    assert len(errors) == 1

    caplog.clear()
    projector.offline = False
    await async_tick(hass, freezer)
    assert hass.states.get(MEDIA_PLAYER).state == STATE_ON
    assert sum("recovered" in record.getMessage() for record in caplog.records) == 1


async def test_reconnects_after_the_connection_is_lost(
    hass: HomeAssistant,
    freezer: FrozenDateTimeFactory,
    mock_config_entry: MockConfigEntry,
    projector: EmulatedProjector,
) -> None:
    """Test the serial port is reopened after it dropped (e.g. adapter replugged)."""
    await setup_integration(hass, mock_config_entry, freezer)
    assert projector.connections == 1

    projector.faults.append(ConnectionLostError("/dev/ttyUSB0"))
    await async_tick(hass, freezer)
    assert hass.states.get(MEDIA_PLAYER).state == STATE_UNAVAILABLE

    await async_tick(hass, freezer)
    assert hass.states.get(MEDIA_PLAYER).state == STATE_ON
    assert projector.connections == 2


async def test_repair_issue_when_the_projector_stays_unreachable(
    hass: HomeAssistant,
    freezer: FrozenDateTimeFactory,
    issue_registry: ir.IssueRegistry,
    mock_config_entry: MockConfigEntry,
    projector: EmulatedProjector,
) -> None:
    """Test a persistent problem raises an issue, which clears itself on recovery."""
    await setup_integration(hass, mock_config_entry, freezer)
    issue_id = f"cannot_communicate_{mock_config_entry.entry_id}"

    projector.offline = True
    for _ in range(ISSUE_THRESHOLD - 1):
        await async_tick(hass, freezer)
    assert issue_registry.async_get_issue(DOMAIN, issue_id) is None

    await async_tick(hass, freezer)
    issue = issue_registry.async_get_issue(DOMAIN, issue_id)
    assert issue is not None
    assert issue.translation_key == "cannot_communicate"
    assert issue.translation_placeholders == {
        "title": "SMART UX60",
        "port": "/dev/ttyUSB0",
    }
    assert not issue.is_fixable

    projector.offline = False
    await async_tick(hass, freezer)
    assert issue_registry.async_get_issue(DOMAIN, issue_id) is None


async def test_repair_issue_is_removed_when_the_entry_is_unloaded(
    hass: HomeAssistant,
    freezer: FrozenDateTimeFactory,
    issue_registry: ir.IssueRegistry,
    mock_config_entry: MockConfigEntry,
    projector: EmulatedProjector,
) -> None:
    """Test unloading does not leave a stale issue behind."""
    await setup_integration(hass, mock_config_entry, freezer)
    projector.offline = True
    for _ in range(ISSUE_THRESHOLD):
        await async_tick(hass, freezer)
    assert issue_registry.issues

    await hass.config_entries.async_unload(mock_config_entry.entry_id)

    assert not issue_registry.issues


async def test_tracking_is_reference_counted(
    hass: HomeAssistant,
    freezer: FrozenDateTimeFactory,
    mock_config_entry: MockConfigEntry,
) -> None:
    """Test a setting stays polled until the last entity using it goes away."""
    await setup_integration(hass, mock_config_entry, freezer)
    coordinator = mock_config_entry.runtime_data

    def setting(interval: timedelta) -> TrackedSetting:
        return TrackedSetting(
            key="tint_test", accessor=lambda device: device.tint, interval=interval
        )

    first = coordinator.async_track_setting(setting(SLOW_INTERVAL))
    second = coordinator.async_track_setting(setting(UPDATE_INTERVAL))
    assert "tint_test" in coordinator.tracked_keys
    # The most demanding interval wins.
    assert coordinator._tracked["tint_test"][0].interval == UPDATE_INTERVAL

    first()
    assert "tint_test" in coordinator.tracked_keys
    second()
    assert "tint_test" not in coordinator.tracked_keys


async def test_values_arrive_with_the_refresh_after_setup(
    hass: HomeAssistant,
    freezer: FrozenDateTimeFactory,
    mock_config_entry: MockConfigEntry,
) -> None:
    """Test entities register what they need, and one refresh then fetches it all."""
    mock_config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    # Entities exist, but nothing they need has been read yet.
    assert hass.states.get("number.smart_ux60_brightness").state == STATE_UNKNOWN

    await async_settle(hass, freezer)

    assert hass.states.get("number.smart_ux60_brightness").state == "50"


async def test_read_timeout_is_an_update_failure(
    hass: HomeAssistant,
    freezer: FrozenDateTimeFactory,
    mock_config_entry: MockConfigEntry,
    projector: EmulatedProjector,
) -> None:
    """Test a timeout in the middle of an update marks the update as failed."""
    await setup_integration(hass, mock_config_entry, freezer)

    projector.faults.extend([SerialTimeoutError("/dev/ttyUSB0", "get powerstate")] * 3)
    await async_tick(hass, freezer)

    assert not mock_config_entry.runtime_data.last_update_success
