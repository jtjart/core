"""Config flow for the SMART Technologies integration."""

from typing import Any, override

import probatio
from smart_serial import (
    CommandError,
    ConnectionFailedError,
    ConnectionLostError,
    ConnectionNotEstablishedError,
    DeviceIdleError,
    SerialTimeoutError,
    SmartUX60,
)

from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.const import CONF_DEVICE
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.selector import SerialPortSelector

from .const import DOMAIN, ENTRY_TITLE, LOGGER

DATA_SCHEMA = probatio.Schema({probatio.Required(CONF_DEVICE): SerialPortSelector()})


class ProbeError(HomeAssistantError):
    """The projector could not be read; ``error`` is the form error to show."""

    def __init__(self, error: str) -> None:
        """Initialize the error."""
        super().__init__(error)
        self.error = error


async def _async_read_serial_number(port: str) -> str:
    """Connect to the projector on ``port`` and return its serial number."""
    try:
        async with SmartUX60.create(port) as projector:
            serial_number = (await projector.serial_number.get()).strip()
    except (
        ConnectionFailedError,
        ConnectionNotEstablishedError,
        ConnectionLostError,
    ) as err:
        raise ProbeError("cannot_connect") from err
    except SerialTimeoutError as err:
        raise ProbeError("no_response") from err
    except DeviceIdleError as err:
        raise ProbeError("device_idle") from err
    except CommandError as err:
        raise ProbeError("invalid_response") from err
    except Exception as err:
        LOGGER.exception("Unexpected exception")
        raise ProbeError("unknown") from err
    if not serial_number:
        raise ProbeError("invalid_response")
    return serial_number


class SmartTechnologiesConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for a SMART projector."""

    VERSION = 1

    @override
    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle the initial step."""
        errors: dict[str, str] = {}

        if user_input is not None:
            port = user_input[CONF_DEVICE]
            self._async_abort_entries_match({CONF_DEVICE: port})
            try:
                serial_number = await _async_read_serial_number(port)
            except ProbeError as err:
                errors["base"] = err.error
            else:
                await self.async_set_unique_id(serial_number)
                self._abort_if_unique_id_configured()
                return self.async_create_entry(
                    title=ENTRY_TITLE, data={CONF_DEVICE: port}
                )

        return self.async_show_form(
            step_id="user",
            data_schema=self.add_suggested_values_to_schema(DATA_SCHEMA, user_input),
            errors=errors,
        )

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Change the serial port, e.g. after moving the adapter."""
        entry = self._get_reconfigure_entry()
        errors: dict[str, str] = {}

        if user_input is not None:
            try:
                serial_number = await _async_read_serial_number(user_input[CONF_DEVICE])
            except ProbeError as err:
                errors["base"] = err.error
            else:
                await self.async_set_unique_id(serial_number)
                # Only the same projector may replace the configured one.
                self._abort_if_unique_id_mismatch(reason="wrong_device")
                return self.async_update_reload_and_abort(
                    entry, data_updates={CONF_DEVICE: user_input[CONF_DEVICE]}
                )

        return self.async_show_form(
            step_id="reconfigure",
            data_schema=self.add_suggested_values_to_schema(
                DATA_SCHEMA, user_input or entry.data
            ),
            errors=errors,
        )
