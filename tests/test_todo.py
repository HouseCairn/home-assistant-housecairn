"""The to-do list of a home: the open tasks, "Done", and the tasks done lately."""

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

from .conftest import API, DAY, DONE_SINCE, HOME_ID, PROBE, TOKEN, UNDATED, load

LIST = "todo.main_house_tasks"
BATTERY = "4d2e93a8-677c-4d1f-995c-cc9837448191"
FILTER = "d0a31b9b-1333-4f2c-a0d7-abc22f19ca17"
KETTLE = "a16c2a47-608f-47a4-9884-1c125d1c136a"
GARAGE = "3a29355e-6942-4b0d-a347-b68bf33529e3"
# Without a date: the open occurrences of two tasks.
STAIR = "a003ed19-ce80-4a78-994e-855e10221245"
LADDER = "17cd54bf-aad7-460f-bcc7-f3ee4d2ae808"
# Done lately: the oven two days ago, the water softener (a repeating task) yesterday.
OVEN = "770c56eb-8c0b-4652-88aa-8d6add45775b"
SOFTENER = "ed5c3cea-3fc6-405f-afd0-60eea233f10d"
OPEN = [BATTERY, FILTER, KETTLE, GARAGE, STAIR, LADDER]
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


async def _open(hass: HomeAssistant) -> list[str]:
    return [i["uid"] for i in await _items(hass) if i["status"] == "needs_action"]


async def _checked(hass: HomeAssistant) -> list[str]:
    return [i["uid"] for i in await _items(hass) if i["status"] == "completed"]


async def _undo(hass: HomeAssistant, uid: str) -> None:
    await hass.services.async_call(
        "todo",
        "update_item",
        {"entity_id": LIST, "item": uid, "status": "needs_action"},
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

    # Overdue first, then by date, then the tasks without a date, then (checked) the
    # tasks done in the last seven days, the latest first. The task hidden until the
    # 16th, the one due past two weeks and the one done twelve days ago are not listed.
    assert [(i["summary"], i["status"], i.get("due"), i.get("description")) for i in items] == [
        ("Replace the smoke detector battery", "needs_action", "2026-11-06", "Kitchen"),
        ("Change the ventilation filter", "needs_action", "2026-11-09", None),
        ("Descale the kettle", "needs_action", "2026-11-09", "Kitchen"),
        ("Service the garage door", "needs_action", "2026-11-14", "Garage"),
        ("Fix the creaky stair", "needs_action", None, None),
        ("Buy a ladder", "needs_action", None, "Garage"),
        ("Check the water softener", "completed", "2026-11-08", None),
        ("Clean the oven", "completed", "2026-11-05", "Kitchen"),
    ]
    assert [i["uid"] for i in items] == [*OPEN, SOFTENER, OVEN]
    state = hass.states.get(LIST)
    assert state is not None
    # The state of a to-do list counts what is left to do.
    assert state.state == "6"
    assert state.attributes["complete"] is True
    assert state.attributes["supported_features"] == TodoListEntityFeature.UPDATE_TODO_ITEM
    # The probe, the five lists, and the rooms (once: every room is known after that).
    assert aioclient_mock.call_count == 7


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


def _done_page(*rows: dict[str, Any]) -> dict[str, Any]:
    return {"next": None, "previous": None, "results": list(rows)}


@pytest.mark.usefixtures("mock_todo_api")
async def test_a_row_in_both_lists_is_listed_once(
    hass: HomeAssistant, setup_entry: Callable[[], Any], aioclient_mock: AiohttpClientMocker
) -> None:
    """A list read a moment after another may hold a row that just changed: shown once."""
    overdue = load("todo_overdue")["body"]["results"][0]
    just_done = {**overdue, "status": "done", "completed_on": DAY}
    done = load("todo_done")["body"]
    aioclient_mock.clear_requests()
    aioclient_mock.get(OCCURRENCES, params=DONE_SINCE, json=_done_page(just_done, *done["results"]))
    aioclient_mock.get(f"{API}/homes/{HOME_ID}/rooms/", json=load("rooms")["body"])
    await _relist(aioclient_mock)

    await setup_entry()

    uids = [i["uid"] for i in await _items(hass)]
    assert uids == [*OPEN, SOFTENER, OVEN]
    assert uids.count(overdue["id"]) == 1


@pytest.mark.usefixtures("mock_todo_api")
async def test_a_room_known_only_by_a_done_task_is_read(
    hass: HomeAssistant,
    setup_entry: Callable[[], Any],
    aioclient_mock: AiohttpClientMocker,
    freezer: Any,
) -> None:
    """Every open task is in a known room; the one task done lately is in a new room."""
    rooms = load("rooms")["body"]
    hallway = next(r for r in rooms["results"] if r["name"] == "Hallway")
    without_hallway = {**rooms, "results": [r for r in rooms["results"] if r is not hallway]}
    aioclient_mock.clear_requests()
    aioclient_mock.get(f"{API}/homes/{HOME_ID}/rooms/", json=without_hallway)
    await _relist(aioclient_mock)
    await setup_entry()
    assert _room_reads(aioclient_mock) == 1

    done = load("todo_done")["body"]
    in_hallway = [
        {**row, "room": hallway["id"]} if row["id"] == OVEN else row for row in done["results"]
    ]
    aioclient_mock.clear_requests()
    aioclient_mock.get(OCCURRENCES, params=DONE_SINCE, json=_done_page(*in_hallway))
    aioclient_mock.get(f"{API}/homes/{HOME_ID}/rooms/", json=rooms)
    await _relist(aioclient_mock)
    freezer.tick(UPDATE_INTERVAL + timedelta(seconds=1))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()

    assert _room_reads(aioclient_mock) == 1
    assert {i["summary"]: i.get("description") for i in await _items(hass)}[
        "Clean the oven"
    ] == "Hallway"


async def _relist(aioclient_mock: AiohttpClientMocker) -> None:
    """The lists and the probe of mock_todo_api, plain."""
    for params, name in (
        ({"overdue": "true"}, "todo_overdue"),
        ({"status": "open", "due_after": DAY, "include_hidden": "true"}, "todo_upcoming"),
        (DONE_SINCE, "todo_done"),
    ):
        aioclient_mock.get(OCCURRENCES, params=params, json=load(name)["body"])
    aioclient_mock.get(
        f"{API}/homes/{HOME_ID}/tasks/", params=UNDATED, json=load("todo_undated")["body"]
    )
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
    # No five-minute wait: the lists were read again right after the POST (5 requests;
    # the rooms are known), and the kettle is checked now, first of the tasks done
    # lately. Its next occurrence is in three months, past the two weeks of the list.
    assert aioclient_mock.call_count == before + 1 + 5
    assert await _open(hass) == [BATTERY, FILTER, GARAGE, STAIR, LADDER]
    assert await _checked(hass) == [KETTLE, SOFTENER, OVEN]
    state = hass.states.get(LIST)
    assert state is not None
    assert state.state == "5"


@pytest.mark.usefixtures("mock_todo_api")
@pytest.mark.parametrize("write_token", [False])
async def test_without_the_write_scope_the_list_is_read_only(
    hass: HomeAssistant, setup_entry: Callable[[], Any], aioclient_mock: AiohttpClientMocker
) -> None:
    entry = await setup_entry()

    state = hass.states.get(LIST)
    assert state is not None
    assert state.state == "6"
    assert state.attributes["supported_features"] == 0
    assert entry.runtime_data.can_write is False
    # The tasks done lately are shown, checked, and cannot be unchecked either.
    assert await _checked(hass) == [SOFTENER, OVEN]
    with pytest.raises(ServiceNotSupported):
        await _done(hass, KETTLE)
    with pytest.raises(ServiceNotSupported):
        await _undo(hass, OVEN)
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
    assert state.state == "6"


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
    assert await _open(hass) == [BATTERY, FILTER, GARAGE, STAIR, LADDER]
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
    assert await _open(hass) == OPEN


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
    assert await _open(hass) == OPEN


@pytest.mark.usefixtures("mock_todo_api", "no_token_in_logs")
async def test_removed_in_housecairn_says_so(
    hass: HomeAssistant, setup_entry: Callable[[], Any], complete: Callable[..., None]
) -> None:
    complete(KETTLE, "complete_unknown", done=True)
    await setup_entry()

    with pytest.raises(ServiceValidationError) as raised:
        await _done(hass, KETTLE)

    assert raised.value.translation_key == "occurrence_gone"
    assert await _open(hass) == [BATTERY, FILTER, GARAGE, STAIR, LADDER]


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
    assert await _open(hass) == OPEN


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


# ---------- tasks without a date, and the tasks done lately ----------


@pytest.mark.usefixtures("mock_todo_api")
async def test_each_list_is_one_filtered_request(
    hass: HomeAssistant, setup_entry: Callable[[], Any], aioclient_mock: AiohttpClientMocker
) -> None:
    """The tasks without a date come from `due=none`, the done ones from `closed_after`."""
    await setup_entry()

    queries = [(url.path, dict(url.query)) for method, url, _d, _h in aioclient_mock.mock_calls]
    assert (
        f"/api/v1/homes/{HOME_ID}/tasks/",
        {"due": "none", "page_size": "200"},
    ) in queries
    assert (
        f"/api/v1/homes/{HOME_ID}/occurrences/",
        {
            "status": "done",
            "closed_after": "2026-11-03",
            "ordering": "recent",
            "page_size": "200",
        },
    ) in queries
    # No other read of the task list: nothing reads it whole.
    assert sum(1 for path, _q in queries if path.endswith("/tasks/")) == 1


@pytest.mark.usefixtures("mock_todo_api", "no_token_in_logs")
async def test_done_on_a_task_without_a_date_completes_its_open_occurrence(
    hass: HomeAssistant,
    setup_entry: Callable[[], Any],
    aioclient_mock: AiohttpClientMocker,
    complete: Callable[..., None],
) -> None:
    complete(LADDER, "complete_ok")
    await setup_entry()

    await _done(hass, LADDER)

    assert f"/api/v1/homes/{HOME_ID}/occurrences/{LADDER}/complete/" in _posts(aioclient_mock)


@pytest.mark.usefixtures("mock_todo_api", "no_token_in_logs")
async def test_unchecking_takes_the_done_back_and_refreshes_at_once(
    hass: HomeAssistant,
    setup_entry: Callable[[], Any],
    aioclient_mock: AiohttpClientMocker,
    undo: Callable[..., None],
) -> None:
    undo(OVEN, "undo_ok")
    await setup_entry()
    assert OVEN in await _checked(hass)
    before = aioclient_mock.call_count

    await _undo(hass, OVEN)

    undos = [
        c
        for c in aioclient_mock.mock_calls
        if c[0].lower() == "post" and c[1].path.endswith(f"{OVEN}/undo/")
    ]
    assert len(undos) == 1
    assert undos[0][3]["Authorization"] == f"Bearer {TOKEN}"
    # Read again at once: the oven is open again, overdue, first of the list.
    assert aioclient_mock.call_count == before + 1 + 5
    assert (await _open(hass))[:2] == [OVEN, BATTERY]
    assert OVEN not in await _checked(hass)


@pytest.mark.usefixtures("mock_todo_api", "no_token_in_logs")
async def test_undo_refused_because_the_next_occurrence_changed_says_so(
    hass: HomeAssistant,
    setup_entry: Callable[[], Any],
    answer: Callable[..., None],
    aioclient_mock: AiohttpClientMocker,
    undo: Callable[..., None],
) -> None:
    """400 with a message and no code: the occurrence, still done, tells why."""
    undo(SOFTENER, "undo_next_changed")
    answer(f"/homes/{HOME_ID}/occurrences/{SOFTENER}/", "occurrence_still_done")
    await setup_entry()
    before = aioclient_mock.call_count

    with pytest.raises(ServiceValidationError) as raised:
        await _undo(hass, SOFTENER)

    assert raised.value.translation_key == "undo_refused"
    assert raised.value.translation_placeholders == {"task": "Check the water softener"}
    # The undo, the read of the occurrence, then the lists again.
    assert aioclient_mock.call_count == before + 2 + 5
    assert SOFTENER in await _checked(hass)


@pytest.mark.usefixtures("mock_todo_api", "no_token_in_logs")
async def test_undo_of_a_task_already_open_again_says_so(
    hass: HomeAssistant,
    setup_entry: Callable[[], Any],
    answer: Callable[..., None],
    undo: Callable[..., None],
) -> None:
    undo(OVEN, "undo_not_closed")
    answer(f"/homes/{HOME_ID}/occurrences/{OVEN}/", "occurrence_open")
    await setup_entry()

    with pytest.raises(ServiceValidationError) as raised:
        await _undo(hass, OVEN)

    assert raised.value.translation_key == "already_reopened"


@pytest.mark.usefixtures("mock_todo_api", "no_token_in_logs")
async def test_undo_refused_and_unreadable_is_not_called_reopened(
    hass: HomeAssistant,
    setup_entry: Callable[[], Any],
    aioclient_mock: AiohttpClientMocker,
    undo: Callable[..., None],
) -> None:
    aioclient_mock.get(f"{OCCURRENCES}{OVEN}/", status=500)
    undo(OVEN, "undo_not_closed")
    await setup_entry()

    with pytest.raises(ServiceValidationError) as raised:
        await _undo(hass, OVEN)

    assert raised.value.translation_key == "undo_refused"


@pytest.mark.usefixtures("mock_todo_api", "no_token_in_logs")
async def test_undo_without_the_write_scope_makes_the_list_read_only(
    hass: HomeAssistant, setup_entry: Callable[[], Any], undo: Callable[..., None]
) -> None:
    undo(OVEN, "undo_forbidden")
    await setup_entry()

    with pytest.raises(ServiceValidationError) as raised:
        await _undo(hass, OVEN)

    assert raised.value.translation_key == "write_scope_missing"
    state = hass.states.get(LIST)
    assert state is not None
    assert state.attributes["supported_features"] == 0


@pytest.mark.usefixtures("mock_todo_api", "no_token_in_logs")
async def test_undo_of_a_removed_task_says_so(
    hass: HomeAssistant, setup_entry: Callable[[], Any], undo: Callable[..., None]
) -> None:
    undo(OVEN, "undo_unknown")
    await setup_entry()

    with pytest.raises(ServiceValidationError) as raised:
        await _undo(hass, OVEN)

    assert raised.value.translation_key == "occurrence_gone"


@pytest.mark.usefixtures("mock_todo_api")
async def test_a_done_task_can_only_be_unchecked(
    hass: HomeAssistant, setup_entry: Callable[[], Any], aioclient_mock: AiohttpClientMocker
) -> None:
    await setup_entry()

    with pytest.raises(ServiceValidationError) as raised:
        await hass.services.async_call(
            "todo",
            "update_item",
            {"entity_id": LIST, "item": OVEN, "rename": "Another title"},
            blocking=True,
        )

    assert raised.value.translation_key == "only_done"
    assert not any(path.endswith(f"{OVEN}/undo/") for path in _posts(aioclient_mock))


# ---------- a home whose sign-in provider the token does not carry ----------


@pytest.mark.usefixtures("mock_todo_api", "no_token_in_logs")
@pytest.mark.parametrize("name", ["occurrences_locked", "sso_provider_changed"])
async def test_done_on_a_home_the_token_cannot_open_asks_for_a_new_token(
    hass: HomeAssistant, setup_entry: Callable[[], Any], complete: Callable[..., None], name: str
) -> None:
    complete(KETTLE, name, done=False)
    entry = await setup_entry()

    with pytest.raises(HomeAssistantError) as raised:
        await _done(hass, KETTLE)

    assert raised.value.translation_key == "sso_required"
    await hass.async_block_till_done()
    flows = hass.config_entries.flow.async_progress()
    assert [(f["context"]["source"], f["step_id"]) for f in flows] == [
        (SOURCE_REAUTH, "reauth_sso")
    ]
    assert flows[0]["context"]["entry_id"] == entry.entry_id


# ---------- the content stays out of the diagnostics ----------


@pytest.mark.usefixtures("mock_todo_api")
async def test_diagnostics_have_counts_but_neither_tasks_nor_rooms(
    hass: HomeAssistant, setup_entry: Callable[[], Any]
) -> None:
    entry = await setup_entry()

    diagnostics = await async_get_config_entry_diagnostics(hass, entry)

    assert diagnostics["data"]["todo"] == 6
    assert diagnostics["data"]["done"] == 2
    assert diagnostics["data"]["todo_complete"] is True
    text = str(diagnostics)
    for content in (
        TOKEN,
        "Kitchen",
        "Garage",
        "kettle",
        "battery",
        "garage door",
        "ladder",
        "oven",
    ):
        assert content not in text
