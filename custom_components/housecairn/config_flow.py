"""Config flow: the address of Housecairn and a Housecairn API token, then a home.

The Housecairn app of Home Assistant announces its internal address to the
Supervisor (discovery, service `housecairn`): the flow then asks for the token only.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import Any

import probatio as vol
from homeassistant.config_entries import (
    SOURCE_HASSIO,
    ConfigEntryState,
    ConfigFlow,
    ConfigFlowResult,
)
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
from homeassistant.helpers.service_info.hassio import HassioServiceInfo

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
from .coordinator import HouseCairnCoordinator

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
READ_ONLY_SCHEMA = vol.Schema({})
# A token and nothing else, for reauthentication and for the discovered app: the app
# gives its address, plain HTTP on the internal network of the Supervisor, where there
# is no certificate to verify.
TOKEN_SCHEMA = REAUTH_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_API_TOKEN): TextSelector(
            TextSelectorConfig(type=TextSelectorType.PASSWORD)
        ),
    }
)


def _discovered_url(config: Mapping[str, Any]) -> str:
    """The internal address announced by the app: `http://<host>:<port>`.

    The app sends `{"host": <its host name on the Supervisor's network>, "port": 8000}`;
    Home Assistant Core adds `addon`, the name of the app. Raises ValueError otherwise.
    """
    host = config.get("host")
    port = config.get("port")
    if not isinstance(host, str) or not host or any(c in host for c in "/:@?#[] "):
        raise ValueError("no host name in the announcement")
    if isinstance(port, str) and port.isdigit():
        port = int(port)
    if isinstance(port, bool) or not isinstance(port, int) or not 0 < port < 65536:
        raise ValueError("no port in the announcement")
    return normalize_url(f"http://{host}:{port}")


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
        self._home: Home | None = None
        self._new_token = ""
        self._app_name = ""

    def _client(self, url: str, token: str, verify_ssl: bool) -> HouseCairnClient:
        session = async_get_clientsession(self.hass, verify_ssl=verify_ssl)
        return HouseCairnClient(session, url, token)

    async def _async_check(self, data: dict[str, Any]) -> str | None:
        """List the homes of the token at the address; the form error if that fails.

        On success the input is kept, and the open homes go to the next step.
        """
        try:
            homes = await self._client(
                data[CONF_URL], data[CONF_API_TOKEN], data[CONF_VERIFY_SSL]
            ).homes()
        except HouseCairnError as exc:
            error = _error_key(exc)
            if error == "unknown":
                _LOGGER.warning("Unexpected answer from Housecairn: %s", exc)
            return error
        open_homes = [home for home in homes if not home.locked]
        if not homes:
            return "no_homes"
        if not open_homes:
            return "home_locked"
        self._input = data
        self._homes = {home.id: home for home in open_homes}
        return None

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Ask for the address and the token, and check them with a real call."""
        errors: dict[str, str] = {}
        if user_input is not None:
            try:
                url = normalize_url(user_input[CONF_URL])
            except ValueError:
                errors[CONF_URL] = "invalid_url"
            else:
                error = await self._async_check({**user_input, CONF_URL: url})
                if error is None:
                    return await self.async_step_home()
                errors["base"] = error
        return self.async_show_form(
            step_id="user",
            data_schema=self.add_suggested_values_to_schema(
                USER_SCHEMA, {CONF_URL: (user_input or {}).get(CONF_URL, "")}
            ),
            description_placeholders={"example_url": "https://housecairn.example.com"},
            errors=errors,
        )

    async def async_step_hassio(self, discovery_info: HassioServiceInfo) -> ConfigFlowResult:
        """The Housecairn app announced its internal address through the Supervisor.

        An entry made from an earlier announcement follows the app to its new address;
        an entry made by hand is never changed. The same address is never offered twice.
        """
        try:
            url = _discovered_url(discovery_info.config)
        except ValueError:
            _LOGGER.warning("Ignored an announcement of the Housecairn app without an address")
            return self.async_abort(reason="invalid_discovery_info")
        # The unique ID of an entry is its home, and one token may open several homes of
        # the same app: every entry made by discovery follows the app, which is what
        # `_abort_if_unique_id_configured(updates=...)` would do for a single entry.
        discovered = [
            entry
            for entry in self._async_current_entries(include_ignore=False)
            if entry.source == SOURCE_HASSIO
        ]
        for entry in discovered:
            if self.hass.config_entries.async_update_entry(
                entry, data={**entry.data, CONF_URL: url}
            ) and entry.state in (ConfigEntryState.LOADED, ConfigEntryState.SETUP_RETRY):
                self.hass.config_entries.async_schedule_reload(entry.entry_id)
        if discovered:
            return self.async_abort(reason="already_configured")
        # Until the token names the home, the flow is known by the address: a second
        # announcement of it joins this flow, and "Ignore" is remembered for it.
        await self.async_set_unique_id(url)
        self._abort_if_unique_id_configured()
        # An entry made by hand for this very address: nothing to add, nothing changed.
        self._async_abort_entries_match({CONF_URL: url})
        self._input = {CONF_URL: url, CONF_VERIFY_SSL: True}
        self._app_name = discovery_info.name or "Housecairn"
        self.context["title_placeholders"] = {"name": self._app_name}
        return await self.async_step_hassio_confirm()

    async def async_step_hassio_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Ask for the token only: the address comes from the app."""
        errors: dict[str, str] = {}
        if user_input is not None:
            error = await self._async_check(
                {**self._input, CONF_API_TOKEN: user_input[CONF_API_TOKEN]}
            )
            if error is None:
                return await self.async_step_home()
            errors["base"] = error
        return self.async_show_form(
            step_id="hassio_confirm",
            data_schema=TOKEN_SCHEMA,
            description_placeholders={"addon": self._app_name},
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
            self._home = home
            client = self._client(
                self._input[CONF_URL], self._input[CONF_API_TOKEN], self._input[CONF_VERIFY_SSL]
            )
            try:
                can_write = await client.probe_write_scope(home.id)
            except HouseCairnError as exc:
                _LOGGER.warning("Could not tell what the token may do: %s", exc)
                return self.async_abort(reason="probe_failed")
            if not can_write:
                return await self.async_step_read_only()
            return self._create_entry()
        if not available:
            return self.async_abort(reason="already_configured")
        options = [SelectOptionDict(value=home.id, label=home.name) for home in available.values()]
        return self.async_show_form(
            step_id="home",
            data_schema=vol.Schema(
                {vol.Required(CONF_HOME_ID): SelectSelector(SelectSelectorConfig(options=options))}
            ),
        )

    def _create_entry(self) -> ConfigFlowResult:
        if self._home is None:
            return self.async_abort(reason="probe_failed")
        return self.async_create_entry(
            title=self._home.name, data={**self._input, CONF_HOME_ID: self._home.id}
        )

    async def async_step_read_only(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Say that the token cannot mark tasks done; the lists are then read only."""
        if user_input is not None:
            return self._create_entry()
        return self.async_show_form(
            step_id="read_only",
            data_schema=READ_ONLY_SCHEMA,
            description_placeholders={"home": self._home.name if self._home else ""},
        )

    async def async_step_reauth(self, entry_data: Mapping[str, Any]) -> ConfigFlowResult:
        """The token was refused: expired, revoked, no longer bound to the home, or
        without the sign-in provider the home now requires.

        The coordinator of the entry noted the last case (a 403 `sso_required`), so that
        the dialog says why a new token is needed.
        """
        coordinator = getattr(self._get_reauth_entry(), "runtime_data", None)
        if isinstance(coordinator, HouseCairnCoordinator) and coordinator.provider_missing:
            return await self.async_step_reauth_sso()
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_sso(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """The home requires a sign-in provider that the saved token does not carry."""
        return await self._reauth_form("reauth_sso", user_input)

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Ask for a new token, and check it opens the same home."""
        return await self._reauth_form("reauth_confirm", user_input)

    async def _reauth_form(
        self, step_id: str, user_input: dict[str, Any] | None
    ) -> ConfigFlowResult:
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
                can_write = await client.probe_write_scope(entry.data[CONF_HOME_ID])
            except HouseCairnError as exc:
                errors["base"] = _error_key(exc)
                if errors["base"] == "unknown":
                    _LOGGER.warning("Unexpected answer from Housecairn: %s", exc)
            else:
                self._new_token = user_input[CONF_API_TOKEN]
                if not can_write:
                    return await self.async_step_reauth_read_only()
                return self._finish_reauth()
        return self.async_show_form(
            step_id=step_id,
            data_schema=REAUTH_SCHEMA,
            description_placeholders={"home": entry.title},
            errors=errors,
        )

    def _finish_reauth(self) -> ConfigFlowResult:
        return self.async_update_reload_and_abort(
            self._get_reauth_entry(), data_updates={CONF_API_TOKEN: self._new_token}
        )

    async def async_step_reauth_read_only(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """The new token works but cannot mark tasks done: say so, then save it."""
        if user_input is not None:
            return self._finish_reauth()
        return self.async_show_form(
            step_id="reauth_read_only",
            data_schema=READ_ONLY_SCHEMA,
            description_placeholders={"home": self._get_reauth_entry().title},
        )
