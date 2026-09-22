"""Diagnostics for the SMART Technologies integration."""

from ipaddress import IPv4Address
from typing import Any

from smart_serial import Source

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.core import HomeAssistant

from .coordinator import SmartTechnologiesConfigEntry

TO_REDACT = {
    "unique_id",
    "serial_number",
    "mac_address",
    "ip_address",
    "subnet_mask",
    "gateway",
    "primary_dns",
    "group_name",
    "projector_name",
    "location_info",
    "contact_info",
}


def _serialize(value: Any) -> Any:
    """Convert a library value into something JSON can represent."""
    if isinstance(value, Source):
        return value.value
    if isinstance(value, IPv4Address):
        return str(value)
    if isinstance(value, tuple | list):
        return [_serialize(item) for item in value]
    return value


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: SmartTechnologiesConfigEntry
) -> dict[str, Any]:
    """Return diagnostics for a config entry."""
    coordinator = entry.runtime_data
    data = coordinator.data
    return {
        "entry": async_redact_data(entry.as_dict(), TO_REDACT),
        "connected": coordinator.device.is_connected,
        "power_state": str(data.power_state),
        "polled_settings": coordinator.tracked_keys,
        "values": async_redact_data(
            {key: _serialize(value) for key, value in data.values.items()}, TO_REDACT
        ),
    }
