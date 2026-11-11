"""The Housecairn integration: one config entry per home of a Housecairn instance.

Home Assistant calls Housecairn with a Housecairn API token. No Home Assistant
token is ever created, asked for or sent to Housecairn.
"""

from __future__ import annotations

from homeassistant.const import CONF_API_TOKEN, CONF_URL, CONF_VERIFY_SSL, Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.typing import ConfigType

from .api import HouseCairnClient
from .const import DOMAIN
from .coordinator import HouseCairnConfigEntry, HouseCairnCoordinator
from .services import async_setup_services

PLATFORMS: list[Platform] = [Platform.SENSOR, Platform.TODO]

# Set up from the UI only: nothing to read in configuration.yaml.
CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Register the actions, which name the home they act on (its config entry)."""
    async_setup_services(hass)
    return True


async def async_setup_entry(hass: HomeAssistant, entry: HouseCairnConfigEntry) -> bool:
    """Read the home once, find out what the token may do, then set up the entities."""
    session = async_get_clientsession(hass, verify_ssl=entry.data.get(CONF_VERIFY_SSL, True))
    client = HouseCairnClient(session, entry.data[CONF_URL], entry.data[CONF_API_TOKEN])
    coordinator = HouseCairnCoordinator(hass, entry, client)
    # Set before the first read: when it asks for a new token, the dialog reads why.
    entry.runtime_data = coordinator
    await coordinator.async_config_entry_first_refresh()
    await coordinator.async_probe_write()
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: HouseCairnConfigEntry) -> bool:
    """Unload the entities of the home."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
