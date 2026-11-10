"""Reads one home of Housecairn at a fixed interval."""

from __future__ import annotations

import datetime
import logging
from dataclasses import dataclass

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryNotReady
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
from .const import CONF_HOME_ID, DOMAIN, TODO_HORIZON, UPDATE_INTERVAL

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
    # What the to-do list shows: overdue first, then by date (see TODO_HORIZON).
    todo: list[Occurrence]
    todo_complete: bool
    # Room names by id, for the description of a to-do item.
    rooms: dict[str, str]


class HouseCairnCoordinator(DataUpdateCoordinator[HouseCairnData]):
    """Three requests per update: the API has no summary endpoint (see docs/plan.md).

    The to-do list is made from the same two lists as the sensors. The rooms are read
    again only when a listed task is in a room that is not known yet.
    """

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
        # Whether the token can mark a task done; probed at setup (see async_probe_write).
        self.can_write = False
        self._rooms: dict[str, str] = {}

    async def async_probe_write(self) -> None:
        """Find out whether the token has the `write` scope; nothing is changed."""
        try:
            self.can_write = await self.client.probe_write_scope(self.home_id)
        except HouseCairnAuthError as exc:
            raise ConfigEntryAuthFailed(
                translation_domain=DOMAIN, translation_key="auth_failed"
            ) from exc
        except HouseCairnConnectionError as exc:
            raise ConfigEntryNotReady(
                translation_domain=DOMAIN, translation_key="cannot_connect"
            ) from exc

    async def _async_update_data(self) -> HouseCairnData:
        # "Today" in the time zone of Home Assistant. Housecairn decides "overdue" in
        # the time zone of the instance, which the API does not expose: when the two
        # differ, the day of the two sensors can differ for a few hours.
        day = dt_util.now().date()
        horizon = day + TODO_HORIZON
        try:
            overdue = await self.client.overdue(self.home_id)
            upcoming = await self.client.open_from(self.home_id, day, horizon)
            low = await self.client.low_stock(self.home_id)
            todo = _todo_rows(overdue.items, upcoming.items, day, horizon)
            await self._read_rooms(todo)
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
            todo=todo,
            todo_complete=overdue.complete and upcoming.complete,
            rooms=dict(self._rooms),
        )

    async def _read_rooms(self, rows: list[Occurrence]) -> None:
        """Read the rooms when a listed task is in one that is not known."""
        if all(row.room is None or row.room in self._rooms for row in rows):
            return
        rooms = await self.client.rooms(self.home_id)
        self._rooms = {room.id: room.name for room in rooms.items}


def _todo_rows(
    overdue: list[Occurrence],
    upcoming: list[Occurrence],
    day: datetime.date,
    horizon: datetime.date,
) -> list[Occurrence]:
    """Overdue rows, then the visible rows due up to `horizon`, by date, each once.

    Housecairn hides an occurrence until a few days before its date (the task decides);
    the list follows it, so a row whose `visible_from` is still ahead is left out. The
    two lists are cut by two clocks (the instance for `overdue`, Home Assistant for
    `upcoming`): a row may be in both, and is kept once.
    """
    rows: dict[str, Occurrence] = {row.id: row for row in overdue}
    for row in upcoming:
        if row.due_on is None or row.due_on > horizon:
            continue
        if row.visible_from is not None and row.visible_from > day:
            continue
        rows.setdefault(row.id, row)
    return sorted(rows.values(), key=lambda row: row.due_on or datetime.date.max)
