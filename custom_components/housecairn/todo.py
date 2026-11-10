"""The to-do list of a home: its open tasks, with "Done".

One list per home. It shows the occurrences that are overdue, due today or due in the
next two weeks, with their date and, when there is one, their room. Checking an item
marks the occurrence done in Housecairn, which creates the next one of a repeating
task; it needs a token with the `write` scope, without which the list is read only.

Adding, renaming, re-dating and deleting are not offered: the API has no call that
does it on an occurrence (a task is created without a date and deleted with all of its
occurrences), and a task created from here would not show in a list of dated tasks.
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
    """The open tasks of a home."""

    _attr_translation_key = "tasks"

    def __init__(self, coordinator: HouseCairnCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.home_id}_tasks"

    @property
    def supported_features(self) -> TodoListEntityFeature:
        """Marking done needs the `write` scope: without it the list is read only."""
        if self.coordinator.can_write:
            return TodoListEntityFeature.UPDATE_TODO_ITEM
        return TodoListEntityFeature(0)

    @property
    def todo_items(self) -> list[TodoItem]:
        rooms = self.coordinator.data.rooms
        return [
            TodoItem(
                uid=row.id,
                summary=row.task_title,
                status=TodoItemStatus.NEEDS_ACTION,
                due=row.due_on,
                description=rooms.get(row.room) if row.room else None,
            )
            for row in self.coordinator.data.todo
        ]

    @property
    def extra_state_attributes(self) -> dict[str, bool]:
        # `complete` is false when a list was too long to read in full.
        return {"complete": self.coordinator.data.todo_complete}

    async def async_update_todo_item(self, item: TodoItem) -> None:
        """Mark the occurrence done; the only change Housecairn allows from here."""
        current = self._current(item.uid)
        if current is None:
            # Done or removed since the last update: the list is out of date.
            await self.coordinator.async_refresh()
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="occurrence_gone",
                translation_placeholders={"task": item.summary or ""},
            )
        if item.status != TodoItemStatus.COMPLETED or item.summary != current.task_title:
            raise ServiceValidationError(translation_domain=DOMAIN, translation_key="only_done")
        await self._complete(current)

    def _current(self, uid: str | None) -> Occurrence | None:
        return next((row for row in self.coordinator.data.todo if row.id == uid), None)

    async def _complete(self, row: Occurrence) -> None:
        coordinator = self.coordinator
        placeholders = {"task": row.task_title}
        try:
            await coordinator.client.complete(coordinator.home_id, row.id)
        except HouseCairnScopeError as exc:
            # The probe at setup said yes, or was not made: the list is read only from now.
            coordinator.can_write = False
            self.async_write_ha_state()
            raise ServiceValidationError(
                translation_domain=DOMAIN, translation_key="write_scope_missing"
            ) from exc
        except HouseCairnAuthError as exc:
            coordinator.config_entry.async_start_reauth(self.hass)
            raise HomeAssistantError(
                translation_domain=DOMAIN, translation_key="auth_failed"
            ) from exc
        except HouseCairnNotFoundError as exc:
            await coordinator.async_refresh()
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="occurrence_gone",
                translation_placeholders=placeholders,
            ) from exc
        except HouseCairnRejectedError as exc:
            await self._explain_rejection(row, exc)
        except HouseCairnConnectionError as exc:
            raise HomeAssistantError(
                translation_domain=DOMAIN, translation_key="cannot_connect"
            ) from exc
        except HouseCairnHomeLockedError as exc:
            raise HomeAssistantError(
                translation_domain=DOMAIN, translation_key="home_locked"
            ) from exc
        except HouseCairnError as exc:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="unexpected_response",
                translation_placeholders={"error": str(exc)},
            ) from exc
        # The next occurrence of a repeating task exists now: read it without waiting.
        await coordinator.async_refresh()

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
