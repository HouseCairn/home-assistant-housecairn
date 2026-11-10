"""Config flow: the address of Housecairn and a Housecairn API token, then a home."""

from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import Any

import probatio as vol
from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.const import CONF_API_TOKEN, CONF_URL, CONF_VERIFY_SSL
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.selector import (
    SelectOptionDict,
    SelectSelector,
    SelectSelectorConfig,
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
)

from .api import (
    Home,
    HouseCairnAuthError,
    HouseCairnClient,
    HouseCairnConnectionError,
    HouseCairnError,
    HouseCairnHomeLockedError,
    HouseCairnNotFoundError,
    HouseCairnScopeError,
    HouseCairnTlsError,
    normalize_url,
)
from .const import CONF_HOME_ID, DOMAIN

_LOGGER = logging.getLogger(__name__)

USER_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_URL): TextSelector(TextSelectorConfig(type=TextSelectorType.URL)),
        vol.Required(CONF_API_TOKEN): TextSelector(
            TextSelectorConfig(type=TextSelectorType.PASSWORD)
        ),
        vol.Required(CONF_VERIFY_SSL, default=True): bool,
    }
)
REAUTH_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_API_TOKEN): TextSelector(
            TextSelectorConfig(type=TextSelectorType.PASSWORD)
        ),
    }
)


def _error_key(exc: HouseCairnError) -> str:
    """The translation key of the form error for a failed call."""
    if isinstance(exc, HouseCairnTlsError):
        return "ssl_error"
    if isinstance(exc, HouseCairnConnectionError):
        return "cannot_connect"
    if isinstance(exc, HouseCairnAuthError):
        return "invalid_auth"
    if isinstance(exc, HouseCairnScopeError):
        return "insufficient_scope"
    if isinstance(exc, HouseCairnHomeLockedError):
        return "home_locked"
    if isinstance(exc, HouseCairnNotFoundError):
        return "wrong_home"
    return "unknown"


class HouseCairnConfigFlow(ConfigFlow, domain=DOMAIN):
    """One entry per home: its unique ID is the UUID of the home."""

    VERSION = 1

    def __init__(self) -> None:
        self._input: dict[str, Any] = {}
        self._homes: dict[str, Home] = {}

    def _client(self, url: str, token: str, verify_ssl: bool) -> HouseCairnClient:
        session = async_get_clientsession(self.hass, verify_ssl=verify_ssl)
        return HouseCairnClient(session, url, token)

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Ask for the address and the token, and check them with a real call."""
        errors: dict[str, str] = {}
        if user_input is not None:
            try:
                url = normalize_url(user_input[CONF_URL])
            except ValueError:
                errors[CONF_URL] = "invalid_url"
            else:
                try:
                    homes = await self._client(
                        url, user_input[CONF_API_TOKEN], user_input[CONF_VERIFY_SSL]
                    ).homes()
                except HouseCairnError as exc:
                    errors["base"] = _error_key(exc)
                    if errors["base"] == "unknown":
                        _LOGGER.warning("Unexpected answer from Housecairn: %s", exc)
                else:
                    open_homes = [home for home in homes if not home.locked]
                    if not homes:
                        errors["base"] = "no_homes"
                    elif not open_homes:
                        errors["base"] = "home_locked"
                    else:
                        self._input = {**user_input, CONF_URL: url}
                        self._homes = {home.id: home for home in open_homes}
                        return await self.async_step_home()
        return self.async_show_form(
            step_id="user",
            data_schema=self.add_suggested_values_to_schema(
                USER_SCHEMA, {CONF_URL: (user_input or {}).get(CONF_URL, "")}
            ),
            description_placeholders={"example_url": "https://housecairn.example.com"},
            errors=errors,
        )

    async def async_step_home(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Pick the home when the token is bound to several; skip the step otherwise."""
        configured = self._async_current_ids(include_ignore=False)
        available = {id_: home for id_, home in self._homes.items() if id_ not in configured}
        if user_input is None and len(self._homes) == 1:
            user_input = {CONF_HOME_ID: next(iter(self._homes))}
        if user_input is not None:
            home = self._homes[user_input[CONF_HOME_ID]]
            await self.async_set_unique_id(home.id)
            self._abort_if_unique_id_configured()
            return self.async_create_entry(
                title=home.name, data={**self._input, CONF_HOME_ID: home.id}
            )
        if not available:
            return self.async_abort(reason="already_configured")
        options = [SelectOptionDict(value=home.id, label=home.name) for home in available.values()]
        return self.async_show_form(
            step_id="home",
            data_schema=vol.Schema(
                {vol.Required(CONF_HOME_ID): SelectSelector(SelectSelectorConfig(options=options))}
            ),
        )

    async def async_step_reauth(self, entry_data: Mapping[str, Any]) -> ConfigFlowResult:
        """The token was refused: expired, revoked, or no longer bound to the home."""
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Ask for a new token, and check it opens the same home."""
        entry = self._get_reauth_entry()
        errors: dict[str, str] = {}
        if user_input is not None:
            client = self._client(
                entry.data[CONF_URL],
                user_input[CONF_API_TOKEN],
                entry.data.get(CONF_VERIFY_SSL, True),
            )
            try:
                home = await client.home(entry.data[CONF_HOME_ID])
                if home.locked:
                    raise HouseCairnHomeLockedError("locked")
                # GET /homes/{id}/ needs `read`; so does every call of the integration.
            except HouseCairnError as exc:
                errors["base"] = _error_key(exc)
                if errors["base"] == "unknown":
                    _LOGGER.warning("Unexpected answer from Housecairn: %s", exc)
            else:
                return self.async_update_reload_and_abort(
                    entry, data_updates={CONF_API_TOKEN: user_input[CONF_API_TOKEN]}
                )
        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=REAUTH_SCHEMA,
            description_placeholders={"home": entry.title},
            errors=errors,
        )
