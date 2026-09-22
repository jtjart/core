"""Test the SMART Technologies config flow."""

import pytest
from smart_serial import (
    ConnectionFailedError,
    ConnectionLostError,
    UnexpectedResponseError,
)

from homeassistant.components.smart_technologies.const import DOMAIN
from homeassistant.config_entries import SOURCE_USER
from homeassistant.const import CONF_DEVICE
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType

from .conftest import MOCK_PORT, MOCK_SERIAL_NUMBER, EmulatedProjector

from tests.common import MockConfigEntry


async def _start_user_flow(hass: HomeAssistant) -> str:
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "user"
    assert result["errors"] == {}
    return result["flow_id"]


@pytest.mark.usefixtures("mock_setup_entry")
async def test_user_flow(hass: HomeAssistant, projector: EmulatedProjector) -> None:
    """Test the flow creates an entry, identified by the projector's serial number."""
    flow_id = await _start_user_flow(hass)

    result = await hass.config_entries.flow.async_configure(
        flow_id, {CONF_DEVICE: MOCK_PORT}
    )

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "SMART UX60"
    assert result["data"] == {CONF_DEVICE: MOCK_PORT}
    assert result["result"].unique_id == MOCK_SERIAL_NUMBER
    # The port is not left open by the flow.
    assert projector.connections == projector.disconnects == 1


@pytest.mark.parametrize(
    ("setup", "error"),
    [
        (
            lambda p: setattr(p, "connect_error", ConnectionFailedError("x", "boom")),
            "cannot_connect",
        ),
        (lambda p: p.faults.append(ConnectionLostError("x")), "cannot_connect"),
        (lambda p: setattr(p, "offline", True), "no_response"),
        (lambda p: setattr(p, "power", "Idle"), "device_idle"),
        (
            lambda p: p.faults.append(UnexpectedResponseError("get", "?")),
            "invalid_response",
        ),
        (lambda p: p.values.update(serialnum=""), "invalid_response"),
        (lambda p: p.faults.append(RuntimeError("boom")), "unknown"),
    ],
    ids=[
        "port_cannot_be_opened",
        "connection_lost",
        "no_answer",
        "standby",
        "unexpected_reply",
        "empty_serial_number",
        "unexpected_error",
    ],
)
@pytest.mark.usefixtures("mock_setup_entry")
async def test_user_flow_errors_and_recovery(
    hass: HomeAssistant, projector: EmulatedProjector, setup, error: str
) -> None:
    """Test each failure is reported and the flow can be completed afterwards."""
    setup(projector)
    flow_id = await _start_user_flow(hass)

    result = await hass.config_entries.flow.async_configure(
        flow_id, {CONF_DEVICE: MOCK_PORT}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": error}

    projector.connect_error = None
    projector.faults.clear()
    projector.offline = False
    projector.power = "On"
    projector.values["serialnum"] = MOCK_SERIAL_NUMBER
    result = await hass.config_entries.flow.async_configure(
        flow_id, {CONF_DEVICE: MOCK_PORT}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY


@pytest.mark.usefixtures("mock_setup_entry")
async def test_user_flow_port_already_configured(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry
) -> None:
    """Test the same port cannot be configured twice."""
    mock_config_entry.add_to_hass(hass)
    flow_id = await _start_user_flow(hass)

    result = await hass.config_entries.flow.async_configure(
        flow_id, {CONF_DEVICE: MOCK_PORT}
    )

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"


@pytest.mark.usefixtures("mock_setup_entry")
async def test_user_flow_projector_already_configured(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry
) -> None:
    """Test the same projector cannot be configured twice, whichever port it is on."""
    mock_config_entry.add_to_hass(hass)
    flow_id = await _start_user_flow(hass)

    result = await hass.config_entries.flow.async_configure(
        flow_id, {CONF_DEVICE: "/dev/ttyUSB7"}
    )

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"


@pytest.mark.usefixtures("mock_setup_entry")
async def test_reconfigure(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry
) -> None:
    """Test the serial port can be changed."""
    mock_config_entry.add_to_hass(hass)

    result = await mock_config_entry.start_reconfigure_flow(hass)
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "reconfigure"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_DEVICE: "/dev/ttyUSB1"}
    )

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reconfigure_successful"
    assert mock_config_entry.data == {CONF_DEVICE: "/dev/ttyUSB1"}


@pytest.mark.usefixtures("mock_setup_entry")
async def test_reconfigure_other_projector(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    projector: EmulatedProjector,
) -> None:
    """Test the port cannot be pointed at a different projector."""
    mock_config_entry.add_to_hass(hass)
    projector.values["serialnum"] = "SOMEONE-ELSE"

    result = await mock_config_entry.start_reconfigure_flow(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_DEVICE: "/dev/ttyUSB1"}
    )

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "wrong_device"
    assert mock_config_entry.data == {CONF_DEVICE: MOCK_PORT}


@pytest.mark.usefixtures("mock_setup_entry")
async def test_reconfigure_error_and_recovery(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    projector: EmulatedProjector,
) -> None:
    """Test a failed reconfiguration can be retried."""
    mock_config_entry.add_to_hass(hass)
    projector.offline = True

    result = await mock_config_entry.start_reconfigure_flow(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_DEVICE: "/dev/ttyUSB1"}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "no_response"}

    projector.offline = False
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_DEVICE: "/dev/ttyUSB1"}
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reconfigure_successful"
