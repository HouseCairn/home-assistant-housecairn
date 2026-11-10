"""Setup, the coordinator, the sensors and the diagnostics."""

from __future__ import annotations

from collections.abc import Callable
from datetime import timedelta
from typing import Any

import aiohttp
import pytest
from homeassistant.components.diagnostics import REDACTED
from homeassistant.config_entries import SOURCE_REAUTH, ConfigEntryState
from homeassistant.const import STATE_UNAVAILABLE
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import async_fire_time_changed
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker

from custom_components.housecairn.const import DOMAIN, UPDATE_INTERVAL
from custom_components.housecairn.diagnostics import async_get_config_entry_diagnostics

from .conftest import API, DAY, HOME_ID, PROBE, TOKEN, URL, load

OVERDUE = "sensor.main_house_overdue_tasks"
TODAY = "sensor.main_house_tasks_due_today"
NEXT = "sensor.main_house_next_due_date"
LOW = "sensor.main_house_stock_items_below_threshold"
OCCURRENCES = f"{API}/homes/{HOME_ID}/occurrences/"


@pytest.mark.usefixtures("mock_api")
async def test_sensors(
    hass: HomeAssistant, setup_entry: Callable[[], Any], aioclient_mock: AiohttpClientMocker
) -> None:
    entry = await setup_entry()

    assert entry.state is ConfigEntryState.LOADED
    overdue = hass.states.get(OVERDUE)
    assert overdue is not None
    assert overdue.state == "2"
    assert overdue.attributes["tasks"] == [
        {"task": "Replace the smoke detector battery", "due_on": "2026-11-06"},
        {"task": "Clean the gutters", "due_on": "2026-11-08"},
    ]
    assert overdue.attributes["complete"] is True
    today = hass.states.get(TODAY)
    assert today is not None
    assert today.state == "2"
    assert [row["task"] for row in today.attributes["tasks"]] == [
        "Change the ventilation filter",
        "Descale the kettle",
    ]
    assert today.attributes["day"] == DAY
    next_due = hass.states.get(NEXT)
    assert next_due is not None
    assert next_due.state == DAY
    assert next_due.attributes["task"] == "Change the ventilation filter"
    low = hass.states.get(LOW)
    assert low is not None
    assert low.state == "2"
    assert low.attributes["items"] == [
        {"name": "AA batteries", "quantity": 0.0, "threshold": 4.0, "unit": "piece"},
        {"name": "Ventilation filter G4", "quantity": 1.0, "threshold": 2.0, "unit": "piece"},
    ]
    # The probe of the write scope at setup, then three requests per update, all with
    # the token in the header only.
    assert aioclient_mock.call_count == 4
    assert [method for method, *_ in aioclient_mock.mock_calls].count("POST") == 1
    for _method, url, _data, headers in aioclient_mock.mock_calls:
        assert url.host == "housecairn.example.com"
        assert headers["Authorization"] == f"Bearer {TOKEN}"


@pytest.mark.usefixtures("mock_api")
async def test_one_device_per_home(
    hass: HomeAssistant,
    setup_entry: Callable[[], Any],
    device_registry: dr.DeviceRegistry,
    entity_registry: er.EntityRegistry,
) -> None:
    entry = await setup_entry()

    device = device_registry.async_get_device_by_identifier((DOMAIN, HOME_ID), entry.entry_id)
    assert device is not None
    assert device.name == "Main house"
    assert device.manufacturer == "Housecairn"
    assert device.configuration_url == URL
    entities = er.async_entries_for_config_entry(entity_registry, entry.entry_id)
    assert sorted(e.unique_id for e in entities) == sorted(
        f"{HOME_ID}_{key}"
        for key in (
            "overdue_tasks",
            "tasks_due_today",
            "next_due_date",
            "low_stock_items",
            "tasks",
        )
    )
    assert {e.device_id for e in entities} == {device.id}


async def test_nothing_due(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker, setup_entry: Callable[[], Any]
) -> None:
    empty = {"next": None, "previous": None, "results": []}
    aioclient_mock.get(OCCURRENCES, json=empty)
    aioclient_mock.get(f"{API}/homes/{HOME_ID}/articles/", json=empty)

    await setup_entry()

    assert hass.states.get(OVERDUE).state == "0"  # type: ignore[union-attr]
    assert hass.states.get(TODAY).state == "0"  # type: ignore[union-attr]
    assert hass.states.get(NEXT).state == "unknown"  # type: ignore[union-attr]
    assert hass.states.get(LOW).state == "0"  # type: ignore[union-attr]


@pytest.mark.usefixtures("no_token_in_logs")
async def test_api_error_makes_entities_unavailable_until_it_recovers(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    answer: Callable[..., None],
    setup_entry: Callable[[], Any],
    freezer: Any,
) -> None:
    answer(f"/homes/{HOME_ID}/occurrences/", "occurrences_overdue", {"overdue": "true"})
    answer(
        f"/homes/{HOME_ID}/occurrences/",
        "occurrences_open_from_today",
        {"status": "open", "due_after": DAY},
    )
    answer(f"/homes/{HOME_ID}/articles/", "articles_low", {"low": "true"})
    entry = await setup_entry()
    assert hass.states.get(OVERDUE).state == "2"  # type: ignore[union-attr]

    aioclient_mock.clear_requests()
    aioclient_mock.get(OCCURRENCES, exc=aiohttp.ClientConnectionError())
    freezer.tick(UPDATE_INTERVAL + timedelta(seconds=1))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()

    for entity_id in (OVERDUE, TODAY, NEXT, LOW):
        assert hass.states.get(entity_id).state == STATE_UNAVAILABLE  # type: ignore[union-attr]
    assert entry.state is ConfigEntryState.LOADED

    aioclient_mock.clear_requests()
    answer(f"/homes/{HOME_ID}/occurrences/", "occurrences_overdue", {"overdue": "true"})
    answer(
        f"/homes/{HOME_ID}/occurrences/",
        "occurrences_open_from_today",
        {"status": "open", "due_after": DAY},
    )
    answer(f"/homes/{HOME_ID}/articles/", "articles_low", {"low": "true"})
    freezer.tick(UPDATE_INTERVAL + timedelta(seconds=1))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()

    assert hass.states.get(OVERDUE).state == "2"  # type: ignore[union-attr]


@pytest.mark.parametrize(
    ("exc", "status", "state"),
    [
        (aiohttp.ClientConnectionError(), None, ConfigEntryState.SETUP_RETRY),
        (TimeoutError(), None, ConfigEntryState.SETUP_RETRY),
        (None, 500, ConfigEntryState.SETUP_RETRY),
    ],
)
async def test_setup_retries_when_housecairn_fails(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    setup_entry: Callable[[], Any],
    exc: Exception | None,
    status: int | None,
    state: ConfigEntryState,
) -> None:
    if exc is not None:
        aioclient_mock.get(OCCURRENCES, exc=exc)
    else:
        aioclient_mock.get(OCCURRENCES, status=status, text="error")

    entry = await setup_entry()

    assert entry.state is state


@pytest.mark.usefixtures("no_token_in_logs")
@pytest.mark.parametrize("name", ["homes_invalid_token", "homes_events_token", "home_other"])
async def test_refused_token_starts_reauth(
    hass: HomeAssistant, answer: Callable[..., None], setup_entry: Callable[[], Any], name: str
) -> None:
    answer(f"/homes/{HOME_ID}/occurrences/", name)

    entry = await setup_entry()

    assert entry.state is ConfigEntryState.SETUP_ERROR
    flows = hass.config_entries.flow.async_progress()
    assert [(f["handler"], f["context"]["source"]) for f in flows] == [(DOMAIN, SOURCE_REAUTH)]
    assert flows[0]["context"]["entry_id"] == entry.entry_id


async def test_locked_home_is_retried_not_reauthenticated(
    hass: HomeAssistant, answer: Callable[..., None], setup_entry: Callable[[], Any]
) -> None:
    answer(f"/homes/{HOME_ID}/occurrences/", "occurrences_locked")

    entry = await setup_entry()

    assert entry.state is ConfigEntryState.SETUP_RETRY
    assert hass.config_entries.flow.async_progress() == []


async def test_long_lists_follow_the_cursor_on_the_configured_host_only(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    answer: Callable[..., None],
    setup_entry: Callable[[], Any],
) -> None:
    """The `next` link names the host the server saw; only its cursor is reused."""
    overdue = load("occurrences_overdue")["body"]
    first, second = overdue["results"]
    page1 = {
        **overdue,
        "next": "http://elsewhere.example/?cursor=abc&overdue=true",
        "results": [first],
    }
    page2 = {**overdue, "results": [second]}
    aioclient_mock.get(OCCURRENCES, params={"overdue": "true", "cursor": "abc"}, json=page2)
    aioclient_mock.get(OCCURRENCES, params={"overdue": "true"}, json=page1)
    # The list from today: its first page ends after today, so no second page is read.
    upcoming = load("occurrences_open_from_today_page1")["body"]
    # A row past the two weeks of the to-do list: the page ends there, so no more is read.
    later = load("todo_upcoming")["body"]["results"][-1]
    aioclient_mock.get(
        OCCURRENCES,
        params={"status": "open", "due_after": DAY},
        json={**upcoming, "results": [*upcoming["results"], later]},
    )
    answer(f"/homes/{HOME_ID}/articles/", "articles_low", {"low": "true"})

    await setup_entry()

    assert hass.states.get(OVERDUE).state == "2"  # type: ignore[union-attr]
    assert hass.states.get(TODAY).state == "1"  # type: ignore[union-attr]
    hosts = {url.host for _m, url, _d, _h in aioclient_mock.mock_calls}
    assert hosts == {"housecairn.example.com"}
    # The probe, two pages of overdue tasks, one of upcoming ones, the stock.
    assert aioclient_mock.call_count == 5


async def test_tasks_of_the_day_read_the_next_page_while_it_is_still_today(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    answer: Callable[..., None],
    setup_entry: Callable[[], Any],
) -> None:
    answer(f"/homes/{HOME_ID}/occurrences/", "occurrences_overdue", {"overdue": "true"})
    page1 = load("occurrences_open_from_today_page1")["body"]
    rest = load("occurrences_open_from_today")["body"]
    aioclient_mock.get(
        OCCURRENCES,
        params={"status": "open", "due_after": DAY, "cursor": "bz0x"},
        json={**rest, "results": rest["results"][1:]},
    )
    aioclient_mock.get(OCCURRENCES, params={"status": "open", "due_after": DAY}, json=page1)
    answer(f"/homes/{HOME_ID}/articles/", "articles_low", {"low": "true"})

    await setup_entry()

    assert hass.states.get(TODAY).state == "2"  # type: ignore[union-attr]
    assert hass.states.get(TODAY).attributes["complete"] is True  # type: ignore[union-attr]


@pytest.mark.usefixtures("mock_api")
async def test_unload(hass: HomeAssistant, setup_entry: Callable[[], Any]) -> None:
    entry = await setup_entry()

    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()

    assert entry.state is ConfigEntryState.NOT_LOADED


@pytest.mark.usefixtures("mock_api")
async def test_diagnostics_redact_the_token_and_the_content(
    hass: HomeAssistant, setup_entry: Callable[[], Any]
) -> None:
    entry = await setup_entry()

    diagnostics = await async_get_config_entry_diagnostics(hass, entry)

    assert diagnostics["entry"]["data"]["api_token"] == REDACTED
    assert diagnostics["entry"]["data"]["url"] == REDACTED
    assert diagnostics["entry"]["data"]["home_id"] == HOME_ID
    assert diagnostics["data"] == {
        "day": DAY,
        "overdue": 2,
        "overdue_complete": True,
        "due_today": 2,
        "due_today_complete": True,
        "next_due_on": DAY,
        "low_stock": 2,
        "low_stock_complete": True,
        "todo": 5,
        "todo_complete": True,
    }
    assert diagnostics["can_write"] is True
    text = str(diagnostics)
    for secret in (TOKEN, "example.com", "Main house", "gutters", "batteries"):
        assert secret not in text


@pytest.mark.usefixtures("mock_api", "no_token_in_logs")
async def test_setup_retries_when_the_write_probe_cannot_be_answered(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker, setup_entry: Callable[[], Any]
) -> None:
    aioclient_mock.clear_requests()
    aioclient_mock.post(f"{API}{PROBE}", exc=aiohttp.ClientConnectionError())
    # The reads of the first refresh succeed; only the probe fails.
    for name, params in (
        ("occurrences_overdue", {"overdue": "true"}),
        ("occurrences_open_from_today", {"status": "open", "due_after": DAY}),
    ):
        aioclient_mock.get(OCCURRENCES, params=params, json=load(name)["body"])
    aioclient_mock.get(f"{API}/homes/{HOME_ID}/articles/", json=load("articles_low")["body"])

    entry = await setup_entry()

    assert entry.state is ConfigEntryState.SETUP_RETRY


@pytest.mark.parametrize("status", [400, 405, 500, 200])
@pytest.mark.usefixtures("mock_api", "no_token_in_logs")
async def test_an_unexpected_write_probe_never_blocks_the_reads(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    setup_entry: Callable[[], Any],
    caplog: pytest.LogCaptureFixture,
    status: int,
) -> None:
    """A probe answer the API does not promise leaves the list read only, not the entry down."""
    aioclient_mock.clear_requests()
    aioclient_mock.post(f"{API}{PROBE}", status=status, json=load("occurrence_done")["body"])
    for name, params in (
        ("occurrences_overdue", {"overdue": "true"}),
        ("occurrences_open_from_today", {"status": "open", "due_after": DAY}),
    ):
        aioclient_mock.get(OCCURRENCES, params=params, json=load(name)["body"])
    aioclient_mock.get(f"{API}/homes/{HOME_ID}/articles/", json=load("articles_low")["body"])
    aioclient_mock.get(f"{API}/homes/{HOME_ID}/rooms/", json=load("rooms")["body"])

    entry = await setup_entry()

    assert entry.state is ConfigEntryState.LOADED
    assert entry.runtime_data.can_write is False
    assert entry.runtime_data.data.todo
    todo = hass.states.get("todo.main_house_tasks")
    assert todo is not None
    assert todo.state != STATE_UNAVAILABLE
    assert todo.attributes["supported_features"] == 0
    for sensor in hass.states.async_all("sensor"):
        assert sensor.state != STATE_UNAVAILABLE
    assert any(
        record.levelname == "WARNING" and "probe of the write scope" in record.getMessage()
        for record in caplog.records
    )
    assert "example.com" not in caplog.text


@pytest.mark.usefixtures("mock_api", "no_token_in_logs")
async def test_setup_starts_reauth_when_the_write_probe_is_refused(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker, setup_entry: Callable[[], Any]
) -> None:
    aioclient_mock.clear_requests()
    aioclient_mock.post(
        f"{API}{PROBE}", status=401, json={"detail": "Invalid, expired or revoked token."}
    )
    for name, params in (
        ("occurrences_overdue", {"overdue": "true"}),
        ("occurrences_open_from_today", {"status": "open", "due_after": DAY}),
    ):
        aioclient_mock.get(OCCURRENCES, params=params, json=load(name)["body"])
    aioclient_mock.get(f"{API}/homes/{HOME_ID}/articles/", json=load("articles_low")["body"])

    entry = await setup_entry()

    assert entry.state is ConfigEntryState.SETUP_ERROR
    flows = hass.config_entries.flow.async_progress()
    assert [(f["handler"], f["context"]["source"]) for f in flows] == [(DOMAIN, SOURCE_REAUTH)]
