"""The Housecairn integration: one config entry per home of a Housecairn instance.

Home Assistant calls Housecairn with a Housecairn API token. No Home Assistant
token is ever created, asked for or sent to Housecairn.
"""

from __future__ import annotations

from homeassistant.const import CONF_API_TOKEN, CONF_URL, CONF_VERIFY_SSL, Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import HouseCairnClient
from .coordinator import HouseCairnConfigEntry, HouseCairnCoordinator

PLATFORMS: list[Platform] = [Platform.SENSOR]


async def async_setup_entry(hass: HomeAssistant, entry: HouseCairnConfigEntry) -> bool:
    """Read the home once, then set up its sensors."""
    session = async_get_clientsession(hass, verify_ssl=entry.data.get(CONF_VERIFY_SSL, True))
    client = HouseCairnClient(session, entry.data[CONF_URL], entry.data[CONF_API_TOKEN])
    coordinator = HouseCairnCoordinator(hass, entry, client)
    await coordinator.async_config_entry_first_refresh()
    entry.runtime_data = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: HouseCairnConfigEntry) -> bool:
    """Unload the sensors of the home."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
