"""The to-do list of a home: the open tasks, and "Done"."""

from __future__ import annotations

from collections.abc import Callable
from datetime import timedelta
from typing import Any

import aiohttp
import pytest
from homeassistant.components.todo import DOMAIN as TODO_DOMAIN
from homeassistant.components.todo.const import TodoItemStatus, TodoListEntityFeature
from homeassistant.components.todo.entity import TodoItem
from homeassistant.config_entries import SOURCE_REAUTH
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError, ServiceNotSupported, ServiceValidationError
from pytest_homeassistant_custom_component.common import async_fire_time_changed
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker

from custom_components.housecairn.const import DOMAIN, UPDATE_INTERVAL
from custom_components.housecairn.diagnostics import async_get_config_entry_diagnostics

from .conftest import API, DAY, HOME_ID, PROBE, TOKEN, load

LIST = "todo.main_house_tasks"
BATTERY = "111e3ebd-05a5-4dd3-a4cc-dce5b2452c89"
FILTER = "5d0ba372-52c6-454b-a1f0-309de03d53a9"
KETTLE = "4a3d1a74-1249-4025-82c4-fbb4fd874ef9"
GARAGE = "b26ad6c9-4de9-4af3-bf18-04029e9b38e5"
OCCURRENCES = f"{API}/homes/{HOME_ID}/occurrences/"
COMPLETE_KETTLE = f"{OCCURRENCES}{KETTLE}/complete/"


async def _items(hass: HomeAssistant) -> list[dict[str, Any]]:
    response = await hass.services.async_call(
        "todo", "get_items", {"entity_id": LIST}, blocking=True, return_response=True
    )
    items: list[dict[str, Any]] = response[LIST]["items"]
    return items


async def _done(hass: HomeAssistant, uid: str) -> None:
    await hass.services.async_call(
        "todo",
        "update_item",
        {"entity_id": LIST, "item": uid, "status": "completed"},
        blocking=True,
    )


def _posts(aioclient_mock: AiohttpClientMocker) -> list[str]:
    return [
        url.path
        for method, url, _data, _headers in aioclient_mock.mock_calls
        if method.lower() == "post"
    ]


# ---------- the list ----------


@pytest.mark.usefixtures("mock_todo_api")
async def test_open_tasks_with_date_and_room(
    hass: HomeAssistant, setup_entry: Callable[[], Any], aioclient_mock: AiohttpClientMocker
) -> None:
    await setup_entry()

    items = await _items(hass)

    # Overdue first, then by date. The task hidden until the 16th and the one due past
    # two weeks are not listed; neither is the one without a date (none in this home).
    assert [(i["summary"], i["due"], i.get("description")) for i in items] == [
        ("Replace the smoke detector battery", "2026-11-06", "Kitchen"),
        ("Change the ventilation filter", "2026-11-09", None),
        ("Descale the kettle", "2026-11-09", "Kitchen"),
        ("Service the garage door", "2026-11-14", "Garage"),
    ]
    assert [i["uid"] for i in items] == [BATTERY, FILTER, KETTLE, GARAGE]
    assert {i["status"] for i in items} == {"needs_action"}
    state = hass.states.get(LIST)
    assert state is not None
    assert state.state == "4"
    assert state.attributes["complete"] is True
    assert state.attributes["supported_features"] == TodoListEntityFeature.UPDATE_TODO_ITEM
    # The probe, the three lists, and the rooms (once: every room is known after that).
    assert aioclient_mock.call_count == 5


def _room_reads(aioclient_mock: AiohttpClientMocker) -> int:
    return sum(1 for _m, url, _d, _h in aioclient_mock.mock_calls if url.path.endswith("/rooms/"))


@pytest.mark.usefixtures("mock_todo_api")
async def test_rooms_are_not_read_again_while_every_room_is_known(
    hass: HomeAssistant,
    setup_entry: Callable[[], Any],
    aioclient_mock: AiohttpClientMocker,
    freezer: Any,
) -> None:
    await setup_entry()
    assert _room_reads(aioclient_mock) == 1

    freezer.tick(UPDATE_INTERVAL + timedelta(seconds=1))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()

    assert _room_reads(aioclient_mock) == 1


@pytest.mark.usefixtures("mock_todo_api")
async def test_a_room_that_appeared_is_read_at_the_next_update(
    hass: HomeAssistant,
    setup_entry: Callable[[], Any],
    aioclient_mock: AiohttpClientMocker,
    freezer: Any,
) -> None:
    """The kitchen is missing from the first answer, as a room created since would be."""
    rooms = load("rooms")["body"]
    without_kitchen = {**rooms, "results": [r for r in rooms["results"] if r["name"] != "Kitchen"]}
    aioclient_mock.clear_requests()
    aioclient_mock.get(f"{API}/homes/{HOME_ID}/rooms/", json=without_kitchen)

    # Registered after the lists of the fixture were cleared: put them back.
    await _relist(aioclient_mock)
    await setup_entry()
    assert {i["summary"]: i.get("description") for i in await _items(hass)}[
        "Descale the kettle"
    ] is None

    aioclient_mock.clear_requests()
    await _relist(aioclient_mock)
    aioclient_mock.get(f"{API}/homes/{HOME_ID}/rooms/", json=rooms)
    freezer.tick(UPDATE_INTERVAL + timedelta(seconds=1))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()

    assert {i["summary"]: i.get("description") for i in await _items(hass)}[
        "Descale the kettle"
    ] == "Kitchen"


async def _relist(aioclient_mock: AiohttpClientMocker) -> None:
    """The lists and the probe of mock_todo_api, plain."""
    for params, name in (
        ({"overdue": "true"}, "todo_overdue"),
        ({"status": "open", "due_after": DAY, "include_hidden": "true"}, "todo_upcoming"),
    ):
        aioclient_mock.get(OCCURRENCES, params=params, json=load(name)["body"])
    aioclient_mock.get(f"{API}/homes/{HOME_ID}/articles/", json=load("articles_low")["body"])
    aioclient_mock.post(f"{API}{PROBE}", status=404, json=load("write_probe_not_found")["body"])


@pytest.mark.usefixtures("mock_todo_api")
async def test_state_is_unavailable_while_housecairn_fails(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    setup_entry: Callable[[], Any],
    freezer: Any,
) -> None:
    await setup_entry()
    aioclient_mock.clear_requests()
    aioclient_mock.get(OCCURRENCES, exc=aiohttp.ClientConnectionError())

    freezer.tick(UPDATE_INTERVAL + timedelta(seconds=1))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()

    state = hass.states.get(LIST)
    assert state is not None
    assert state.state == "unavailable"


# ---------- "Done" ----------


@pytest.mark.usefixtures("mock_todo_api", "no_token_in_logs")
async def test_done_completes_the_occurrence_and_refreshes_at_once(
    hass: HomeAssistant,
    setup_entry: Callable[[], Any],
    aioclient_mock: AiohttpClientMocker,
    complete: Callable[..., None],
) -> None:
    complete(KETTLE, "complete_ok")
    await setup_entry()
    before = aioclient_mock.call_count

    await _done(hass, KETTLE)

    posts = [
        c
        for c in aioclient_mock.mock_calls
        if c[0].lower() == "post" and c[1].path.endswith("complete/")
    ]
    assert [call[1].path for call in posts] == [
        f"/api/v1/homes/{HOME_ID}/occurrences/{KETTLE}/complete/"
    ]
    assert posts[0][3]["Authorization"] == f"Bearer {TOKEN}"
    # No five-minute wait: the lists were read again right after the POST (3 requests;
    # the rooms are known), and the kettle is gone from the list. Its next occurrence
    # is in three months, past the two weeks of the list.
    assert aioclient_mock.call_count == before + 1 + 3
    assert [i["uid"] for i in await _items(hass)] == [BATTERY, FILTER, GARAGE]
    state = hass.states.get(LIST)
    assert state is not None
    assert state.state == "3"


@pytest.mark.usefixtures("mock_todo_api")
@pytest.mark.parametrize("write_token", [False])
async def test_without_the_write_scope_the_list_is_read_only(
    hass: HomeAssistant, setup_entry: Callable[[], Any], aioclient_mock: AiohttpClientMocker
) -> None:
    entry = await setup_entry()

    state = hass.states.get(LIST)
    assert state is not None
    assert state.state == "4"
    assert state.attributes["supported_features"] == 0
    assert entry.runtime_data.can_write is False
    with pytest.raises(ServiceNotSupported):
        await _done(hass, KETTLE)
    assert _posts(aioclient_mock) == [
        f"/api/v1/homes/{HOME_ID}/occurrences/00000000-0000-0000-0000-000000000000/undo/"
    ]
    diagnostics = await async_get_config_entry_diagnostics(hass, entry)
    assert diagnostics["can_write"] is False


@pytest.mark.usefixtures("mock_todo_api", "no_token_in_logs")
async def test_scope_lost_since_setup_makes_the_list_read_only(
    hass: HomeAssistant, setup_entry: Callable[[], Any], complete: Callable[..., None]
) -> None:
    complete(KETTLE, "complete_forbidden")
    await setup_entry()

    with pytest.raises(ServiceValidationError) as raised:
        await _done(hass, KETTLE)

    assert raised.value.translation_key == "write_scope_missing"
    state = hass.states.get(LIST)
    assert state is not None
    assert state.attributes["supported_features"] == 0
    assert state.state == "4"


@pytest.mark.usefixtures("mock_todo_api", "no_token_in_logs")
async def test_closed_by_somebody_else_says_so_and_refreshes(
    hass: HomeAssistant,
    setup_entry: Callable[[], Any],
    answer: Callable[..., None],
    aioclient_mock: AiohttpClientMocker,
    complete: Callable[..., None],
) -> None:
    """The API refuses with a 400 and a message, no code: the occurrence tells why."""
    complete(KETTLE, "complete_closed", done=True)
    answer(f"/homes/{HOME_ID}/occurrences/{KETTLE}/", "occurrence_done")
    await setup_entry()

    with pytest.raises(ServiceValidationError) as raised:
        await _done(hass, KETTLE)

    assert raised.value.translation_key == "already_closed"
    assert raised.value.translation_placeholders == {"task": "Descale the kettle"}
    assert [i["uid"] for i in await _items(hass)] == [BATTERY, FILTER, GARAGE]
    assert any(
        url.path.endswith(f"/occurrences/{KETTLE}/")
        for _m, url, _d, _h in aioclient_mock.mock_calls
    )


@pytest.mark.usefixtures("mock_todo_api", "no_token_in_logs")
async def test_refused_for_another_reason_is_not_called_closed(
    hass: HomeAssistant,
    setup_entry: Callable[[], Any],
    aioclient_mock: AiohttpClientMocker,
    complete: Callable[..., None],
) -> None:
    open_row = next(row for row in load("todo_upcoming")["body"]["results"] if row["id"] == KETTLE)
    aioclient_mock.get(f"{OCCURRENCES}{KETTLE}/", json=open_row)
    complete(KETTLE, "complete_closed", done=False)
    await setup_entry()

    with pytest.raises(ServiceValidationError) as raised:
        await _done(hass, KETTLE)

    assert raised.value.translation_key == "completion_refused"
    assert len(await _items(hass)) == 4


@pytest.mark.usefixtures("mock_todo_api", "no_token_in_logs")
async def test_refused_and_unreadable_afterwards_is_not_called_closed(
    hass: HomeAssistant,
    setup_entry: Callable[[], Any],
    aioclient_mock: AiohttpClientMocker,
    complete: Callable[..., None],
) -> None:
    """When the occurrence cannot be read to tell why, the refusal stays unexplained."""
    aioclient_mock.get(f"{OCCURRENCES}{KETTLE}/", status=500)
    complete(KETTLE, "complete_closed", done=False)
    await setup_entry()

    with pytest.raises(ServiceValidationError) as raised:
        await _done(hass, KETTLE)

    assert raised.value.translation_key == "completion_refused"
    assert len(await _items(hass)) == 4


@pytest.mark.usefixtures("mock_todo_api", "no_token_in_logs")
async def test_removed_in_housecairn_says_so(
    hass: HomeAssistant, setup_entry: Callable[[], Any], complete: Callable[..., None]
) -> None:
    complete(KETTLE, "complete_unknown", done=True)
    await setup_entry()

    with pytest.raises(ServiceValidationError) as raised:
        await _done(hass, KETTLE)

    assert raised.value.translation_key == "occurrence_gone"
    assert [i["uid"] for i in await _items(hass)] == [BATTERY, FILTER, GARAGE]


@pytest.mark.usefixtures("mock_todo_api", "no_token_in_logs")
async def test_an_item_that_left_the_list_since_the_last_update(
    hass: HomeAssistant, setup_entry: Callable[[], Any]
) -> None:
    await setup_entry()
    entity: Any = hass.data[TODO_DOMAIN].get_entity(LIST)
    stale = TodoItem(uid="no-longer-listed", summary="Gone", status=TodoItemStatus.COMPLETED)

    with pytest.raises(ServiceValidationError) as raised:
        await entity.async_update_todo_item(stale)

    assert raised.value.translation_key == "occurrence_gone"


@pytest.mark.usefixtures("mock_todo_api", "no_token_in_logs")
@pytest.mark.parametrize(
    ("exc", "status", "key"),
    [
        (aiohttp.ClientConnectionError(), None, "cannot_connect"),
        (TimeoutError(), None, "cannot_connect"),
        (None, 500, "unexpected_response"),
    ],
)
async def test_api_errors_are_reported_and_leave_the_list_alone(
    hass: HomeAssistant,
    setup_entry: Callable[[], Any],
    aioclient_mock: AiohttpClientMocker,
    exc: Exception | None,
    status: int | None,
    key: str,
) -> None:
    if exc is not None:
        aioclient_mock.post(COMPLETE_KETTLE, exc=exc)
    else:
        aioclient_mock.post(COMPLETE_KETTLE, status=status, text="Server Error")
    await setup_entry()

    with pytest.raises(HomeAssistantError) as raised:
        await _done(hass, KETTLE)

    assert raised.value.translation_key == key
    assert TOKEN not in str(raised.value)
    assert len(await _items(hass)) == 4


@pytest.mark.usefixtures("mock_todo_api", "no_token_in_logs")
async def test_a_refused_token_starts_reauthentication(
    hass: HomeAssistant, setup_entry: Callable[[], Any], complete: Callable[..., None]
) -> None:
    complete(KETTLE, "complete_invalid_token", done=False)
    entry = await setup_entry()

    with pytest.raises(HomeAssistantError) as raised:
        await _done(hass, KETTLE)

    assert raised.value.translation_key == "auth_failed"
    flows = hass.config_entries.flow.async_progress()
    assert [(f["handler"], f["context"]["source"]) for f in flows] == [(DOMAIN, SOURCE_REAUTH)]
    assert flows[0]["context"]["entry_id"] == entry.entry_id


@pytest.mark.usefixtures("mock_todo_api")
@pytest.mark.parametrize(
    "fields",
    [
        {"status": "needs_action"},
        {"rename": "Another title", "status": "completed"},
    ],
)
async def test_only_done_is_offered(
    hass: HomeAssistant,
    setup_entry: Callable[[], Any],
    aioclient_mock: AiohttpClientMocker,
    fields: dict[str, str],
) -> None:
    await setup_entry()

    with pytest.raises(ServiceValidationError) as raised:
        await hass.services.async_call(
            "todo", "update_item", {"entity_id": LIST, "item": KETTLE, **fields}, blocking=True
        )

    assert raised.value.translation_key == "only_done"
    assert _posts(aioclient_mock) == [
        f"/api/v1/homes/{HOME_ID}/occurrences/00000000-0000-0000-0000-000000000000/undo/"
    ]


# ---------- the content stays out of the diagnostics ----------


@pytest.mark.usefixtures("mock_todo_api")
async def test_diagnostics_have_counts_but_neither_tasks_nor_rooms(
    hass: HomeAssistant, setup_entry: Callable[[], Any]
) -> None:
    entry = await setup_entry()

    diagnostics = await async_get_config_entry_diagnostics(hass, entry)

    assert diagnostics["data"]["todo"] == 4
    assert diagnostics["data"]["todo_complete"] is True
    text = str(diagnostics)
    for content in (TOKEN, "Kitchen", "Garage", "kettle", "battery", "garage door"):
        assert content not in text
