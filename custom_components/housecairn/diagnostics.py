"""Diagnostics: counts and dates only; the token, the address and names are redacted."""

from __future__ import annotations

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.const import CONF_API_TOKEN, CONF_URL
from homeassistant.core import HomeAssistant

from .coordinator import HouseCairnConfigEntry

# Diagnostics are pasted into public issues: no secret, no address of the instance.
TO_REDACT = {CONF_API_TOKEN, CONF_URL}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: HouseCairnConfigEntry
) -> dict[str, Any]:
    """What helps to understand a problem, without the content of the home."""
    coordinator = entry.runtime_data
    data = coordinator.data
    return {
        "entry": {
            "title": "**REDACTED**",
            "data": async_redact_data(dict(entry.data), TO_REDACT),
        },
        "last_update_success": coordinator.last_update_success,
        "can_write": coordinator.can_write,
        "update_interval_seconds": (
            coordinator.update_interval.total_seconds() if coordinator.update_interval else None
        ),
        "data": None
        if data is None
        else {
            "day": data.day.isoformat(),
            "overdue": len(data.overdue),
            "overdue_complete": data.overdue_complete,
            "due_today": len(data.due_today),
            "due_today_complete": data.due_today_complete,
            "next_due_on": (
                data.next_due.due_on.isoformat() if data.next_due and data.next_due.due_on else None
            ),
            "low_stock": len(data.low_stock),
            "low_stock_complete": data.low_stock_complete,
            "todo": len(data.todo),
            "todo_complete": data.todo_complete,
        },
    }
