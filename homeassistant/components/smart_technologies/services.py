"""Actions of the SMART Technologies integration."""

import probatio

from homeassistant.components.media_player import DOMAIN as MEDIA_PLAYER_DOMAIN
from homeassistant.core import HomeAssistant, SupportsResponse, callback
from homeassistant.helpers import config_validation as cv, service
from homeassistant.helpers.typing import VolDictType

from .const import DOMAIN

SERVICE_GET_VALUE = "get_value"
SERVICE_SET_VALUE = "set_value"
SERVICE_ADJUST_VALUE = "adjust_value"

ATTR_KEY = "key"
ATTR_VALUE = "value"
ATTR_DELTA = "delta"
ATTR_SOURCE = "source"

# Keys in the SMART command reference are lower-case alphanumerics.
_KEY = probatio.All(cv.string, probatio.Match(r"^[A-Za-z0-9_]+$"))

GET_VALUE_SCHEMA: VolDictType = {probatio.Required(ATTR_KEY): _KEY}
SET_VALUE_SCHEMA: VolDictType = {
    probatio.Required(ATTR_KEY): _KEY,
    probatio.Required(ATTR_VALUE): cv.string,
    probatio.Optional(ATTR_SOURCE): cv.string,
}
ADJUST_VALUE_SCHEMA: VolDictType = {
    probatio.Required(ATTR_KEY): _KEY,
    probatio.Required(ATTR_DELTA): probatio.All(
        probatio.Coerce(int), probatio.Range(min=-100, max=100)
    ),
    probatio.Optional(ATTR_SOURCE): cv.string,
}


@callback
def async_setup_services(hass: HomeAssistant) -> None:
    """Register the entity actions."""
    service.async_register_platform_entity_service(
        hass,
        DOMAIN,
        SERVICE_GET_VALUE,
        entity_domain=MEDIA_PLAYER_DOMAIN,
        schema=GET_VALUE_SCHEMA,
        func="async_service_get_value",
        supports_response=SupportsResponse.ONLY,
    )
    service.async_register_platform_entity_service(
        hass,
        DOMAIN,
        SERVICE_SET_VALUE,
        entity_domain=MEDIA_PLAYER_DOMAIN,
        schema=SET_VALUE_SCHEMA,
        func="async_service_set_value",
        supports_response=SupportsResponse.OPTIONAL,
    )
    service.async_register_platform_entity_service(
        hass,
        DOMAIN,
        SERVICE_ADJUST_VALUE,
        entity_domain=MEDIA_PLAYER_DOMAIN,
        schema=ADJUST_VALUE_SCHEMA,
        func="async_service_adjust_value",
        supports_response=SupportsResponse.OPTIONAL,
    )
