"""Sensors of a home: overdue tasks, tasks of the day, next due date, low stock."""

from __future__ import annotations

import datetime
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .api import Article, Occurrence
from .const import ATTRIBUTE_ROWS
from .coordinator import HouseCairnConfigEntry, HouseCairnCoordinator, HouseCairnData
from .entity import HouseCairnEntity

# Coordinator-based: updates are centralised, nothing to limit per entity.
PARALLEL_UPDATES = 0


def _tasks(rows: list[Occurrence]) -> list[dict[str, Any]]:
    return [
        {
            "task": row.task_title,
            "due_on": row.due_on.isoformat() if row.due_on else None,
        }
        for row in rows[:ATTRIBUTE_ROWS]
    ]


def _articles(rows: list[Article]) -> list[dict[str, Any]]:
    return [
        {
            "name": row.name,
            "quantity": float(row.quantity),
            "threshold": float(row.threshold) if row.threshold is not None else None,
            "unit": row.unit_label,
        }
        for row in rows[:ATTRIBUTE_ROWS]
    ]


@dataclass(frozen=True, kw_only=True)
class HouseCairnSensorDescription(SensorEntityDescription):
    """How a sensor reads the data of the coordinator."""

    value_fn: Callable[[HouseCairnData], int | datetime.date | None]
    attributes_fn: Callable[[HouseCairnData], dict[str, Any]]


SENSORS: tuple[HouseCairnSensorDescription, ...] = (
    HouseCairnSensorDescription(
        key="overdue_tasks",
        translation_key="overdue_tasks",
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda data: len(data.overdue),
        attributes_fn=lambda data: {
            "tasks": _tasks(data.overdue),
            "complete": data.overdue_complete,
        },
    ),
    HouseCairnSensorDescription(
        key="tasks_due_today",
        translation_key="tasks_due_today",
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda data: len(data.due_today),
        attributes_fn=lambda data: {
            "tasks": _tasks(data.due_today),
            "complete": data.due_today_complete,
            "day": data.day.isoformat(),
        },
    ),
    HouseCairnSensorDescription(
        key="next_due_date",
        translation_key="next_due_date",
        device_class=SensorDeviceClass.DATE,
        value_fn=lambda data: data.next_due.due_on if data.next_due else None,
        attributes_fn=lambda data: (
            {"task": data.next_due.task_title} if data.next_due else {"task": None}
        ),
    ),
    HouseCairnSensorDescription(
        key="low_stock_items",
        translation_key="low_stock_items",
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda data: len(data.low_stock),
        attributes_fn=lambda data: {
            "items": _articles(data.low_stock),
            "complete": data.low_stock_complete,
        },
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: HouseCairnConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """One set of sensors per home."""
    coordinator = entry.runtime_data
    async_add_entities(HouseCairnSensor(coordinator, description) for description in SENSORS)


class HouseCairnSensor(HouseCairnEntity, SensorEntity):
    """A sensor of a home; unavailable while the last update failed."""

    entity_description: HouseCairnSensorDescription

    def __init__(
        self, coordinator: HouseCairnCoordinator, description: HouseCairnSensorDescription
    ) -> None:
        super().__init__(coordinator)
        self.entity_description = description
        self._attr_unique_id = f"{coordinator.home_id}_{description.key}"

    @property
    def native_value(self) -> int | datetime.date | None:
        return self.entity_description.value_fn(self.coordinator.data)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return self.entity_description.attributes_fn(self.coordinator.data)
