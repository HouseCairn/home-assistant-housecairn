"""Reads one home of Housecairn at a fixed interval."""

from __future__ import annotations

import datetime
import logging
from dataclasses import dataclass

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .api import (
    Article,
    HouseCairnAuthError,
    HouseCairnClient,
    HouseCairnConnectionError,
    HouseCairnError,
    HouseCairnHomeLockedError,
    HouseCairnNotFoundError,
    HouseCairnScopeError,
    Occurrence,
)
from .const import CONF_HOME_ID, DOMAIN, UPDATE_INTERVAL

_LOGGER = logging.getLogger(__name__)

type HouseCairnConfigEntry = ConfigEntry[HouseCairnCoordinator]


@dataclass(frozen=True, slots=True)
class HouseCairnData:
    """What one update read."""

    day: datetime.date
    overdue: list[Occurrence]
    overdue_complete: bool
    due_today: list[Occurrence]
    due_today_complete: bool
    next_due: Occurrence | None
    low_stock: list[Article]
    low_stock_complete: bool


class HouseCairnCoordinator(DataUpdateCoordinator[HouseCairnData]):
    """Three requests per update: the API has no summary endpoint (see docs/plan.md)."""

    config_entry: HouseCairnConfigEntry

    def __init__(
        self, hass: HomeAssistant, entry: HouseCairnConfigEntry, client: HouseCairnClient
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=DOMAIN,
            update_interval=UPDATE_INTERVAL,
        )
        self.client = client
        self.home_id: str = entry.data[CONF_HOME_ID]

    async def _async_update_data(self) -> HouseCairnData:
        # "Today" in the time zone of Home Assistant. Housecairn decides "overdue" in
        # the time zone of the instance, which the API does not expose: when the two
        # differ, the day of the two sensors can differ for a few hours.
        day = dt_util.now().date()
        try:
            overdue = await self.client.overdue(self.home_id)
            upcoming = await self.client.open_from(self.home_id, day)
            low = await self.client.low_stock(self.home_id)
        except (HouseCairnAuthError, HouseCairnScopeError, HouseCairnNotFoundError) as exc:
            # A revoked or expired token, or one no longer bound to this home: only a
            # new token helps.
            raise ConfigEntryAuthFailed(
                translation_domain=DOMAIN, translation_key="auth_failed"
            ) from exc
        except HouseCairnHomeLockedError as exc:
            raise UpdateFailed(translation_domain=DOMAIN, translation_key="home_locked") from exc
        except HouseCairnConnectionError as exc:
            raise UpdateFailed(translation_domain=DOMAIN, translation_key="cannot_connect") from exc
        except HouseCairnError as exc:
            raise UpdateFailed(
                translation_domain=DOMAIN,
                translation_key="unexpected_response",
                translation_placeholders={"error": str(exc)},
            ) from exc

        today = [row for row in upcoming.items if row.due_on == day]
        return HouseCairnData(
            day=day,
            overdue=overdue.items,
            overdue_complete=overdue.complete,
            due_today=today,
            due_today_complete=upcoming.complete or len(today) < len(upcoming.items),
            next_due=upcoming.items[0] if upcoming.items else None,
            low_stock=low.items,
            low_stock_complete=low.complete,
        )
