"""The to-do list of a home: its open tasks, with "Done", and the tasks done lately.

One list per home. It shows the occurrences that are overdue, due today or due in the
next two weeks, with their date and, when there is one, their room; then the tasks
without a date; then, checked, the tasks marked done in the last seven days. Checking an
item marks the occurrence done in Housecairn, which creates the next one of a repeating
task; unchecking a done item takes that "Done" back. Both need a token with the `write`
scope, without which the list is read only.

Adding, renaming, re-dating and deleting are not offered: the API has no call that
does it on an occurrence (a task is deleted with all of its occurrences).
"""

from __future__ import annotations

import logging
from typing import NoReturn

# The submodules, not the package: it does not export these names for a type checker.
from homeassistant.components.todo.const import TodoItemStatus, TodoListEntityFeature
from homeassistant.components.todo.entity import TodoItem, TodoListEntity
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.util import dt as dt_util

from .api import (
    HouseCairnAuthError,
    HouseCairnConnectionError,
    HouseCairnError,
    HouseCairnHomeLockedError,
    HouseCairnNotFoundError,
    HouseCairnRejectedError,
    HouseCairnScopeError,
    Occurrence,
)
from .const import DOMAIN
from .coordinator import HouseCairnConfigEntry, HouseCairnCoordinator
from .entity import HouseCairnEntity

_LOGGER = logging.getLogger(__name__)

# Coordinator-based: updates are centralised, nothing to limit per entity.
PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant,
    entry: HouseCairnConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """One to-do list per home."""
    async_add_entities([HouseCairnTodoList(entry.runtime_data)])


class HouseCairnTodoList(HouseCairnEntity, TodoListEntity):
    """The open tasks of a home, and the tasks done in the last days."""

    _attr_translation_key = "tasks"

    def __init__(self, coordinator: HouseCairnCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.home_id}_tasks"

    @property
    def supported_features(self) -> TodoListEntityFeature:
        """Done and undone need the `write` scope: without it the list is read only."""
        if self.coordinator.can_write:
            return TodoListEntityFeature.UPDATE_TODO_ITEM
        return TodoListEntityFeature(0)

    @property
    def todo_items(self) -> list[TodoItem]:
        data = self.coordinator.data
        rooms = data.rooms
        open_items = [
            TodoItem(
                uid=row.id,
                summary=row.task_title,
                status=TodoItemStatus.NEEDS_ACTION,
                due=row.due_on,
                description=rooms.get(row.room) if row.room else None,
            )
            for row in data.todo
        ]
        done_items = [
            TodoItem(
                uid=row.id,
                summary=row.task_title,
                status=TodoItemStatus.COMPLETED,
                due=row.due_on,
                description=rooms.get(row.room) if row.room else None,
                completed=dt_util.start_of_local_day(row.completed_on)
                if row.completed_on
                else None,
            )
            for row in data.done
        ]
        return open_items + done_items

    @property
    def extra_state_attributes(self) -> dict[str, bool]:
        # `complete` is false when a list was too long to read in full.
        return {"complete": self.coordinator.data.todo_complete}

    async def async_update_todo_item(self, item: TodoItem) -> None:
        """Mark an open task done, or take back the "Done" of a task done lately.

        These are the only changes Housecairn allows from here.
        """
        data = self.coordinator.data
        open_row = _find(data.todo, item.uid)
        done_row = None if open_row is not None else _find(data.done, item.uid)
        current = open_row or done_row
        if current is None:
            # Done, undone or removed since the last update: the list is out of date.
            await self.coordinator.async_refresh()
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="occurrence_gone",
                translation_placeholders={"task": item.summary or ""},
            )
        wanted = TodoItemStatus.COMPLETED if open_row is not None else TodoItemStatus.NEEDS_ACTION
        if item.status != wanted or item.summary != current.task_title:
            raise ServiceValidationError(translation_domain=DOMAIN, translation_key="only_done")
        if open_row is not None:
            await self._complete(open_row)
        else:
            await self._undo(current)

    async def _complete(self, row: Occurrence) -> None:
        coordinator = self.coordinator
        try:
            await coordinator.client.complete(coordinator.home_id, row.id)
        except HouseCairnRejectedError as exc:
            await self._explain_rejection(row, exc)
        except HouseCairnError as exc:
            await self._fail(row, exc)
        # The next occurrence of a repeating task exists now: read it without waiting.
        await coordinator.async_refresh()

    async def _undo(self, row: Occurrence) -> None:
        coordinator = self.coordinator
        try:
            await coordinator.client.undo(coordinator.home_id, row.id)
        except HouseCairnRejectedError as exc:
            await self._explain_undo_rejection(row, exc)
        except HouseCairnError as exc:
            await self._fail(row, exc)
        # The task is open again, and the next occurrence of a repeating one is gone.
        await coordinator.async_refresh()

    async def _fail(self, row: Occurrence, error: HouseCairnError) -> NoReturn:
        """Turn a failed change into the error Home Assistant shows; 400s are not here."""
        coordinator = self.coordinator
        if isinstance(error, HouseCairnScopeError):
            # The probe at setup said yes, or was not made: the list is read only from now.
            coordinator.can_write = False
            self.async_write_ha_state()
            raise ServiceValidationError(
                translation_domain=DOMAIN, translation_key="write_scope_missing"
            ) from error
        if isinstance(error, HouseCairnAuthError):
            coordinator.config_entry.async_start_reauth(self.hass)
            raise HomeAssistantError(
                translation_domain=DOMAIN, translation_key="auth_failed"
            ) from error
        if isinstance(error, HouseCairnHomeLockedError):
            # A new token is needed, created while signed in through the provider.
            coordinator.provider_missing = True
            coordinator.config_entry.async_start_reauth(self.hass)
            raise HomeAssistantError(
                translation_domain=DOMAIN, translation_key="sso_required"
            ) from error
        if isinstance(error, HouseCairnNotFoundError):
            await coordinator.async_refresh()
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="occurrence_gone",
                translation_placeholders={"task": row.task_title},
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

    async def _explain_rejection(
        self, row: Occurrence, rejected: HouseCairnRejectedError
    ) -> NoReturn:
        """Say why Housecairn refused. Its message has no stable code, so look at the state.

        An occurrence refused with a 400 is almost always one that somebody closed
        meanwhile; reading it settles that without parsing a message.
        """
        coordinator = self.coordinator
        closed = False
        try:
            closed = (await coordinator.client.occurrence(coordinator.home_id, row.id)).is_closed
        except HouseCairnError:
            _LOGGER.debug("Could not read the occurrence after a refusal")
        _LOGGER.debug("Housecairn refused to complete an occurrence: %s", rejected.detail)
        await coordinator.async_refresh()
        raise ServiceValidationError(
            translation_domain=DOMAIN,
            translation_key="already_closed" if closed else "completion_refused",
            translation_placeholders={"task": row.task_title},
        ) from rejected

    async def _explain_undo_rejection(
        self, row: Occurrence, rejected: HouseCairnRejectedError
    ) -> NoReturn:
        """Say why Housecairn refused to take a "Done" back; it gives no stable code either.

        Either the task is open again already (somebody took it back in Housecairn), or
        the next occurrence of a repeating task was changed since (moved, noted, done),
        which Housecairn will not lose. Reading the occurrence tells the two apart.
        """
        coordinator = self.coordinator
        reopened = False
        try:
            reopened = not (
                await coordinator.client.occurrence(coordinator.home_id, row.id)
            ).is_closed
        except HouseCairnError:
            _LOGGER.debug("Could not read the occurrence after a refusal")
        _LOGGER.debug("Housecairn refused to take back a Done: %s", rejected.detail)
        await coordinator.async_refresh()
        raise ServiceValidationError(
            translation_domain=DOMAIN,
            translation_key="already_reopened" if reopened else "undo_refused",
            translation_placeholders={"task": row.task_title},
        ) from rejected


def _find(rows: list[Occurrence], uid: str | None) -> Occurrence | None:
    return next((row for row in rows if row.id == uid), None)
