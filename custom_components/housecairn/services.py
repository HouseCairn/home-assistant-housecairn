"""The action of the integration: report a problem in Housecairn from an automation.

`housecairn.report` creates a report in a home (`POST /reports/`), as a person would from
the Report screen of Housecairn, under the person who owns the token. It needs a token
with the `write` scope. It never makes a duplicate: when a report of that person that is
not closed yet has the same title and the same place, nothing is created and the answer
says so. The answer (`response_variable`) carries the identifier of the report.
"""

from __future__ import annotations

import uuid
from typing import Any, NoReturn

import probatio as vol
from homeassistant.core import (
    HomeAssistant,
    ServiceCall,
    ServiceResponse,
    SupportsResponse,
    callback,
)
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import service

from .api import (
    HouseCairnAuthError,
    HouseCairnConnectionError,
    HouseCairnError,
    HouseCairnHomeLockedError,
    HouseCairnNotFoundError,
    HouseCairnRejectedError,
    HouseCairnScopeError,
    Report,
)
from .const import (
    ATTR_ARTICLE,
    ATTR_CONFIG_ENTRY_ID,
    ATTR_ITEM,
    ATTR_ROOM,
    ATTR_TITLE,
    DOMAIN,
    REPORT_TITLE_MAX,
    SERVICE_REPORT,
)
from .coordinator import HouseCairnConfigEntry, HouseCairnCoordinator

PLACE = "place"


def _identifier(value: Any) -> str:
    """A Housecairn identifier: a UUID, written as Housecairn writes it."""
    return str(uuid.UUID(str(value).strip()))


def _title(value: Any) -> str:
    """The title as Housecairn keeps it: runs of white space made one space."""
    title = " ".join(cv.string(value).split())
    if not title:
        raise vol.Invalid("the title is empty")
    return title


REPORT_SCHEMA = vol.Schema(
    {
        vol.Required(ATTR_CONFIG_ENTRY_ID): cv.string,
        vol.Required(ATTR_TITLE): vol.All(_title, vol.Length(max=REPORT_TITLE_MAX)),
        # At most one place, as in Housecairn.
        vol.Exclusive(ATTR_ROOM, PLACE): _identifier,
        vol.Exclusive(ATTR_ITEM, PLACE): _identifier,
        vol.Exclusive(ATTR_ARTICLE, PLACE): _identifier,
    }
)


@callback
def async_setup_services(hass: HomeAssistant) -> None:
    """Register the action once, for every home of the integration."""
    hass.services.async_register(
        DOMAIN,
        SERVICE_REPORT,
        _async_report,
        schema=REPORT_SCHEMA,
        supports_response=SupportsResponse.OPTIONAL,
    )


def _same(report: Report, title: str, place: dict[str, str | None]) -> bool:
    """The same problem: the same title (whatever the case) at the same place."""
    return (
        report.title.casefold() == title.casefold()
        and report.room == place[ATTR_ROOM]
        and report.item == place[ATTR_ITEM]
        and report.article == place[ATTR_ARTICLE]
    )


async def _async_report(call: ServiceCall) -> ServiceResponse:
    entry: HouseCairnConfigEntry = service.async_get_config_entry(
        call.hass, DOMAIN, call.data[ATTR_CONFIG_ENTRY_ID]
    )
    coordinator = entry.runtime_data
    if not coordinator.can_write:
        raise ServiceValidationError(
            translation_domain=DOMAIN,
            translation_key="report_needs_write",
            translation_placeholders={"home": entry.title},
        )
    title: str = call.data[ATTR_TITLE]
    place: dict[str, str | None] = {
        name: call.data.get(name) for name in (ATTR_ROOM, ATTR_ITEM, ATTR_ARTICLE)
    }
    async with coordinator.report_lock:
        try:
            waiting = await coordinator.client.waiting_reports(coordinator.home_id)
            existing = next((r for r in waiting if _same(r, title, place)), None)
            if existing is not None:
                return {"report_id": existing.id, "created": False, "status": existing.status}
            report = await coordinator.client.create_report(coordinator.home_id, title, **place)
        except HouseCairnError as exc:
            _raise(call.hass, coordinator, exc)
    return {"report_id": report.id, "created": True, "status": report.status}


def _raise(
    hass: HomeAssistant, coordinator: HouseCairnCoordinator, error: HouseCairnError
) -> NoReturn:
    """Turn a failed call into the error Home Assistant shows to the automation."""
    entry = coordinator.config_entry
    if isinstance(error, HouseCairnScopeError):
        coordinator.can_write = False
        raise ServiceValidationError(
            translation_domain=DOMAIN,
            translation_key="report_needs_write",
            translation_placeholders={"home": entry.title},
        ) from error
    if isinstance(error, HouseCairnRejectedError):
        raise ServiceValidationError(
            translation_domain=DOMAIN,
            translation_key="report_refused",
            translation_placeholders={"error": error.detail},
        ) from error
    if isinstance(error, HouseCairnAuthError | HouseCairnNotFoundError):
        entry.async_start_reauth(hass)
        raise HomeAssistantError(
            translation_domain=DOMAIN, translation_key="auth_failed"
        ) from error
    if isinstance(error, HouseCairnHomeLockedError):
        coordinator.provider_missing = True
        entry.async_start_reauth(hass)
        raise HomeAssistantError(
            translation_domain=DOMAIN, translation_key="sso_required"
        ) from error
    if isinstance(error, HouseCairnConnectionError):
        raise HomeAssistantError(
            translation_domain=DOMAIN, translation_key="cannot_connect"
        ) from error
    raise HomeAssistantError(
        translation_domain=DOMAIN,
        translation_key="unexpected_response",
        translation_placeholders={"error": str(error)},
    ) from error
