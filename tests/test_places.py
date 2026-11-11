"""housecairn.report from the entity that saw the problem: room by area, item by device.

The rooms come from a captured answer (rooms.json: Kitchen, Garage, Hallway). The other
lists of rooms and items are written here, shaped as the `Room` and `Item` schemas of
tests/fixtures/openapi.yaml, because each test needs its own names.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import Any

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.helpers import area_registry as ar
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.test_util.aiohttp import (
    AiohttpClientMocker,
    AiohttpClientMockResponse,
)

from custom_components.housecairn.const import DOMAIN
from custom_components.housecairn.diagnostics import async_get_config_entry_diagnostics
from custom_components.housecairn.places import normalize, store_key

from .conftest import API, HOME_ID, load

ROOMS = f"{API}/homes/{HOME_ID}/rooms/"
ITEMS = f"{API}/homes/{HOME_ID}/items/"
REPORTS = f"{API}/homes/{HOME_ID}/reports/"
# The rooms of rooms.json.
KITCHEN = "e941c67e-27f5-480d-8f76-08a7e6f5ae1b"
GARAGE = "d5572653-0f6a-453b-803f-99a421d6d6a7"
HALLWAY = "978c6a38-de2c-4c8e-8eff-ee38d0536a82"
BOILER_ITEM = "6a0f8a7e-2c43-4f0e-9a51-7c1b0e2d4f11"
OTHER_BOILER = "7b1f9b8f-3d54-4a1f-8b62-8d2c1f3e5a22"
CREATED_ITEM = "8c2a0c90-4e65-4b20-9c73-9e3d2a4f6b33"
GONE_ITEM = "9d3b1da1-5f76-4c31-8d84-af4e3b5a7c44"
TITLE = "Boiler fault"
ENTITY = "binary_sensor.boiler_fault"


def _page(rows: list[dict[str, Any]]) -> dict[str, Any]:
    return {"next": None, "previous": None, "results": rows}


def _room(room_id: str, name: str) -> dict[str, Any]:
    return {"id": room_id, "name": name, "kind": "other", "position": 0, "item_count": 0}


def _item(item_id: str, name: str, room: str = KITCHEN) -> dict[str, Any]:
    return {
        "id": item_id,
        "room": room,
        "name": name,
        "kind": "equipment",
        "brand": "",
        "model": "",
        "created_at": "2026-11-09T10:00:00Z",
        "updated_at": "2026-11-09T10:00:00Z",
    }


def _calls(aioclient_mock: AiohttpClientMocker, method: str, path: str) -> list[Any]:
    return [
        data
        for m, url, data, _h in aioclient_mock.mock_calls
        if m.lower() == method and str(url).split("?")[0] == path
    ]


@pytest.fixture
def api(aioclient_mock: AiohttpClientMocker, mock_api: None) -> Callable[..., None]:
    """Register the rooms, the items of a room, and the reports (none waiting)."""

    def register(
        *,
        rooms: list[dict[str, Any]] | None = None,
        items: dict[str, list[dict[str, Any]]] | None = None,
    ) -> None:
        if rooms is None:
            aioclient_mock.get(ROOMS, json=load("rooms")["body"])
        else:
            aioclient_mock.get(ROOMS, json=_page(rooms))
        for room, rows in (items or {}).items():
            aioclient_mock.get(ITEMS, params={"room": room}, json=_page(rows))
        for status in ("open", "task"):
            aioclient_mock.get(REPORTS, params={"status": status, "mine": "true"}, json=_page([]))
        data = load("report_created")
        aioclient_mock.post(REPORTS, status=data["status"], json=data["body"])

    return register


@pytest.fixture
def created(aioclient_mock: AiohttpClientMocker) -> list[Any]:
    """POST /items/ answers 201 with the item it was sent, as CREATED_ITEM."""
    bodies: list[Any] = []

    async def create(method: str, url: Any, data: Any) -> AiohttpClientMockResponse:
        bodies.append(data)
        await asyncio.sleep(0)
        row = {**_item(CREATED_ITEM, data["name"], data["room"]), **data}
        return AiohttpClientMockResponse(method, url, status=201, json=row)

    aioclient_mock.post(ITEMS, side_effect=create)
    return bodies


@pytest.fixture
def other_entry(hass: HomeAssistant) -> MockConfigEntry:
    """The integration that owns the boiler, as any device of Home Assistant."""
    entry = MockConfigEntry(domain="boiler_maker")
    entry.add_to_hass(hass)
    return entry


@pytest.fixture
def boiler(
    hass: HomeAssistant, other_entry: MockConfigEntry
) -> Callable[..., tuple[str, str | None]]:
    """A fault sensor, on a boiler device unless `device` is false; returns their ids."""

    def make(
        *,
        entity_area: str | None = None,
        device_area: str | None = None,
        device: bool = True,
        name: str = "Boiler",
        manufacturer: str | None = "Acme Heating",
        model: str | None = "Condens 5000",
    ) -> tuple[str, str | None]:
        areas = ar.async_get(hass)
        devices = dr.async_get(hass)
        entities = er.async_get(hass)
        device_id = None
        if device:
            made = devices.async_get_or_create(
                config_entry_id=other_entry.entry_id,
                identifiers={("boiler_maker", "boiler-1")},
                name=name,
                manufacturer=manufacturer,
                model=model,
            )
            if device_area:
                area = areas.async_get_or_create(device_area)
                devices.async_update_device(made.id, area_id=area.id)
            device_id = made.id
        entity = entities.async_get_or_create(
            "binary_sensor",
            "boiler_maker",
            "boiler-1-fault",
            suggested_object_id="boiler_fault",
            config_entry=other_entry,
            device_id=device_id,
            # A name of its own: Home Assistant refuses an area to an entity without one.
            has_entity_name=True,
            original_name="Fault",
        )
        if entity_area:
            area = areas.async_get_or_create(entity_area)
            entities.async_update_entity(entity.entity_id, area_id=area.id)
        assert entity.entity_id == ENTITY
        return entity.entity_id, device_id

    return make


async def _report(hass: HomeAssistant, entry_id: str, **fields: Any) -> Any:
    return await hass.services.async_call(
        DOMAIN,
        "report",
        {"config_entry_id": entry_id, "title": TITLE, **fields},
        blocking=True,
        return_response=True,
    )


def _matches(response: dict[str, Any]) -> tuple[str, str]:
    return response["room_match"], response["item_match"]


@pytest.mark.parametrize(
    ("given", "wanted"),
    [
        ("Chaudière", "chaudiere"),
        ("  Salle   de BAINS ", "salle de bains"),
        ("Entrée", "ENTREE"),
    ],
)
def test_names_compare_without_case_accents_or_extra_spaces(given: str, wanted: str) -> None:
    assert normalize(given) == normalize(wanted)


def test_other_names_stay_apart() -> None:
    assert normalize("Kitchen") != normalize("Kitchen 2")


@pytest.mark.usefixtures("no_token_in_logs")
async def test_the_area_of_the_entity_gives_the_room_before_its_device(
    hass: HomeAssistant,
    setup_entry: Callable[[], Any],
    aioclient_mock: AiohttpClientMocker,
    api: Callable[..., None],
    boiler: Callable[..., Any],
) -> None:
    api(items={KITCHEN: [], GARAGE: []})
    boiler(entity_area="Kitchen", device_area="Garage")
    entry = await setup_entry()

    response = await _report(hass, entry.entry_id, entity_id=ENTITY)

    assert _matches(response) == ("matched", "none")
    assert response["created"] is True
    assert _calls(aioclient_mock, "post", REPORTS) == [{"title": TITLE, "room": KITCHEN}]


@pytest.mark.usefixtures("no_token_in_logs")
async def test_without_an_area_of_its_own_the_entity_takes_the_area_of_its_device(
    hass: HomeAssistant,
    setup_entry: Callable[[], Any],
    aioclient_mock: AiohttpClientMocker,
    api: Callable[..., None],
    boiler: Callable[..., Any],
) -> None:
    api(items={GARAGE: []})
    boiler(device_area="Garage")
    entry = await setup_entry()

    response = await _report(hass, entry.entry_id, entity_id=ENTITY)

    assert _matches(response) == ("matched", "none")
    assert _calls(aioclient_mock, "post", REPORTS) == [{"title": TITLE, "room": GARAGE}]


@pytest.mark.usefixtures("no_token_in_logs")
async def test_the_area_given_forces_the_room(
    hass: HomeAssistant,
    setup_entry: Callable[[], Any],
    aioclient_mock: AiohttpClientMocker,
    api: Callable[..., None],
    boiler: Callable[..., Any],
) -> None:
    api(items={HALLWAY: []})
    boiler(entity_area="Kitchen", device_area="Garage")
    hallway = ar.async_get(hass).async_get_or_create("Hallway")
    entry = await setup_entry()

    response = await _report(hass, entry.entry_id, entity_id=ENTITY, area_id=hallway.id)

    assert _matches(response) == ("matched", "none")
    assert _calls(aioclient_mock, "post", REPORTS) == [{"title": TITLE, "room": HALLWAY}]


@pytest.mark.usefixtures("no_token_in_logs")
async def test_an_area_with_accents_matches_the_room_without(
    hass: HomeAssistant,
    setup_entry: Callable[[], Any],
    aioclient_mock: AiohttpClientMocker,
    api: Callable[..., None],
    boiler: Callable[..., Any],
) -> None:
    api(rooms=[_room(KITCHEN, "Cuisine"), _room(HALLWAY, "entree")], items={HALLWAY: []})
    boiler(entity_area="Entrée")
    entry = await setup_entry()

    response = await _report(hass, entry.entry_id, entity_id=ENTITY)

    assert _matches(response) == ("matched", "none")
    assert _calls(aioclient_mock, "post", REPORTS) == [{"title": TITLE, "room": HALLWAY}]


@pytest.mark.usefixtures("no_token_in_logs")
@pytest.mark.parametrize(
    ("rooms", "room_match"),
    [
        # No room of that name: none is ever created.
        ([_room(GARAGE, "Garage")], "none"),
        # Two rooms of that name: none is chosen.
        ([_room(KITCHEN, "Kitchen"), _room(GARAGE, "kitchen ")], "ambiguous"),
    ],
)
async def test_no_room_or_several_means_a_report_without_place(
    hass: HomeAssistant,
    setup_entry: Callable[[], Any],
    aioclient_mock: AiohttpClientMocker,
    api: Callable[..., None],
    boiler: Callable[..., Any],
    created: list[Any],
    rooms: list[dict[str, Any]],
    room_match: str,
) -> None:
    api(rooms=rooms)
    boiler(entity_area="Kitchen")
    entry = await setup_entry()

    response = await _report(hass, entry.entry_id, entity_id=ENTITY, create_item=True)

    assert _matches(response) == (room_match, "none")
    assert _calls(aioclient_mock, "post", REPORTS) == [{"title": TITLE}]
    assert _calls(aioclient_mock, "post", ROOMS) == []
    assert created == []
    assert _calls(aioclient_mock, "get", ITEMS) == []


@pytest.mark.usefixtures("no_token_in_logs")
async def test_an_entity_without_area_or_device_gives_no_place(
    hass: HomeAssistant,
    setup_entry: Callable[[], Any],
    aioclient_mock: AiohttpClientMocker,
    api: Callable[..., None],
    boiler: Callable[..., Any],
) -> None:
    api()
    boiler(device=False)
    entry = await setup_entry()

    response = await _report(hass, entry.entry_id, entity_id=ENTITY, create_item=True)

    assert _matches(response) == ("none", "none")
    assert _calls(aioclient_mock, "post", REPORTS) == [{"title": TITLE}]


@pytest.mark.usefixtures("no_token_in_logs")
async def test_an_entity_without_device_gives_the_room_only(
    hass: HomeAssistant,
    setup_entry: Callable[[], Any],
    aioclient_mock: AiohttpClientMocker,
    api: Callable[..., None],
    boiler: Callable[..., Any],
    created: list[Any],
) -> None:
    api()
    boiler(device=False, entity_area="Kitchen")
    entry = await setup_entry()

    response = await _report(hass, entry.entry_id, entity_id=ENTITY, create_item=True)

    assert _matches(response) == ("matched", "none")
    assert _calls(aioclient_mock, "post", REPORTS) == [{"title": TITLE, "room": KITCHEN}]
    assert _calls(aioclient_mock, "get", ITEMS) == []
    assert created == []


@pytest.mark.usefixtures("no_token_in_logs")
async def test_the_item_of_the_room_with_the_name_of_the_device_is_used(
    hass: HomeAssistant,
    setup_entry: Callable[[], Any],
    aioclient_mock: AiohttpClientMocker,
    api: Callable[..., None],
    boiler: Callable[..., Any],
    created: list[Any],
) -> None:
    api(
        rooms=[_room(KITCHEN, "Cuisine")],
        items={
            KITCHEN: [_item(OTHER_BOILER, "Chaudiere d'appoint"), _item(BOILER_ITEM, "chaudiere")]
        },
    )
    boiler(entity_area="Cuisine", name="Chaudière")
    entry = await setup_entry()

    response = await _report(hass, entry.entry_id, entity_id=ENTITY, create_item=True)

    assert _matches(response) == ("matched", "matched")
    assert _calls(aioclient_mock, "post", REPORTS) == [{"title": TITLE, "item": BOILER_ITEM}]
    assert created == []


@pytest.mark.usefixtures("no_token_in_logs")
async def test_the_name_given_by_the_user_wins_over_the_name_of_the_device(
    hass: HomeAssistant,
    setup_entry: Callable[[], Any],
    aioclient_mock: AiohttpClientMocker,
    api: Callable[..., None],
    boiler: Callable[..., Any],
) -> None:
    api(items={KITCHEN: [_item(BOILER_ITEM, "Kitchen boiler")]})
    _entity, device_id = boiler(entity_area="Kitchen", name="ACME-B5000")
    dr.async_get(hass).async_update_device(device_id, name_by_user="Kitchen boiler")
    entry = await setup_entry()

    response = await _report(hass, entry.entry_id, entity_id=ENTITY)

    assert _matches(response) == ("matched", "matched")
    assert _calls(aioclient_mock, "post", REPORTS) == [{"title": TITLE, "item": BOILER_ITEM}]


@pytest.mark.usefixtures("no_token_in_logs")
async def test_a_missing_device_is_added_to_the_room_and_remembered(
    hass: HomeAssistant,
    hass_storage: dict[str, Any],
    setup_entry: Callable[[], Any],
    aioclient_mock: AiohttpClientMocker,
    api: Callable[..., None],
    boiler: Callable[..., Any],
    created: list[Any],
) -> None:
    api(items={KITCHEN: [_item(OTHER_BOILER, "Water heater")]})
    _entity, device_id = boiler(entity_area="Kitchen", manufacturer="A" * 130)
    entry = await setup_entry()

    response = await _report(hass, entry.entry_id, entity_id=ENTITY, create_item=True)

    assert _matches(response) == ("matched", "created")
    assert created == [
        {
            "room": KITCHEN,
            "name": "Boiler",
            "kind": "equipment",
            # Cut to the longest brand Housecairn accepts.
            "brand": "A" * 120,
            "model": "Condens 5000",
        }
    ]
    assert _calls(aioclient_mock, "post", REPORTS) == [{"title": TITLE, "item": CREATED_ITEM}]
    stored = hass_storage[store_key(entry.entry_id)]["data"]
    assert stored == {"devices": {device_id: CREATED_ITEM}}


@pytest.mark.usefixtures("no_token_in_logs")
async def test_a_device_without_maker_or_model_is_added_with_its_name_only(
    hass: HomeAssistant,
    setup_entry: Callable[[], Any],
    api: Callable[..., None],
    boiler: Callable[..., Any],
    created: list[Any],
) -> None:
    api(items={KITCHEN: []})
    boiler(entity_area="Kitchen", manufacturer=None, model=None)
    entry = await setup_entry()

    await _report(hass, entry.entry_id, entity_id=ENTITY, create_item=True)

    assert created == [{"room": KITCHEN, "name": "Boiler", "kind": "equipment"}]


@pytest.mark.usefixtures("no_token_in_logs")
async def test_nothing_is_added_unless_asked(
    hass: HomeAssistant,
    setup_entry: Callable[[], Any],
    aioclient_mock: AiohttpClientMocker,
    api: Callable[..., None],
    boiler: Callable[..., Any],
    created: list[Any],
) -> None:
    """`create_item` is false by default in the action (true in the blueprints)."""
    api(items={KITCHEN: []})
    boiler(entity_area="Kitchen")
    entry = await setup_entry()

    default = await _report(hass, entry.entry_id, entity_id=ENTITY)
    refused = await _report(hass, entry.entry_id, entity_id=ENTITY, create_item=False)

    assert _matches(default) == _matches(refused) == ("matched", "none")
    assert created == []
    assert _calls(aioclient_mock, "post", REPORTS)[0] == {"title": TITLE, "room": KITCHEN}


@pytest.mark.usefixtures("no_token_in_logs")
async def test_two_items_with_the_name_of_the_device_means_none(
    hass: HomeAssistant,
    setup_entry: Callable[[], Any],
    aioclient_mock: AiohttpClientMocker,
    api: Callable[..., None],
    boiler: Callable[..., Any],
    created: list[Any],
) -> None:
    api(items={KITCHEN: [_item(BOILER_ITEM, "Boiler"), _item(OTHER_BOILER, "boiler")]})
    boiler(entity_area="Kitchen")
    entry = await setup_entry()

    response = await _report(hass, entry.entry_id, entity_id=ENTITY, create_item=True)

    assert _matches(response) == ("matched", "ambiguous")
    assert created == []
    assert _calls(aioclient_mock, "post", REPORTS) == [{"title": TITLE, "room": KITCHEN}]


def _seed(hass_storage: dict[str, Any], entry_id: str, links: dict[str, str]) -> None:
    key = store_key(entry_id)
    hass_storage[key] = {"version": 1, "minor_version": 1, "key": key, "data": {"devices": links}}


@pytest.mark.usefixtures("no_token_in_logs")
async def test_a_remembered_item_is_used_even_after_a_rename(
    hass: HomeAssistant,
    hass_storage: dict[str, Any],
    mock_entry: MockConfigEntry,
    setup_entry: Callable[[], Any],
    aioclient_mock: AiohttpClientMocker,
    api: Callable[..., None],
    boiler: Callable[..., Any],
    created: list[Any],
) -> None:
    """Renamed in Home Assistant and in Housecairn: the link still holds."""
    api(items={KITCHEN: [_item(OTHER_BOILER, "Boiler")]})
    aioclient_mock.get(f"{ITEMS}{BOILER_ITEM}/", json=_item(BOILER_ITEM, "Main heater"))
    _entity, device_id = boiler(entity_area="Kitchen", name="Boiler")
    _seed(hass_storage, mock_entry.entry_id, {device_id: BOILER_ITEM})
    entry = await setup_entry()

    response = await _report(hass, entry.entry_id, entity_id=ENTITY, create_item=True)

    assert _matches(response) == ("matched", "linked")
    assert _calls(aioclient_mock, "post", REPORTS) == [{"title": TITLE, "item": BOILER_ITEM}]
    assert _calls(aioclient_mock, "get", ITEMS) == []
    assert created == []


@pytest.mark.usefixtures("no_token_in_logs")
async def test_a_remembered_item_deleted_in_housecairn_is_forgotten(
    hass: HomeAssistant,
    hass_storage: dict[str, Any],
    mock_entry: MockConfigEntry,
    setup_entry: Callable[[], Any],
    aioclient_mock: AiohttpClientMocker,
    api: Callable[..., None],
    boiler: Callable[..., Any],
) -> None:
    api(items={KITCHEN: [_item(BOILER_ITEM, "Boiler")]})
    aioclient_mock.get(
        f"{ITEMS}{GONE_ITEM}/", status=404, json={"detail": "No Item matches the given query."}
    )
    _entity, device_id = boiler(entity_area="Kitchen")
    _seed(hass_storage, mock_entry.entry_id, {device_id: GONE_ITEM})
    entry = await setup_entry()

    response = await _report(hass, entry.entry_id, entity_id=ENTITY)

    # The link is dropped, then the item of the room with the device's name is found.
    assert _matches(response) == ("matched", "matched")
    assert _calls(aioclient_mock, "post", REPORTS) == [{"title": TITLE, "item": BOILER_ITEM}]
    assert hass_storage[store_key(entry.entry_id)]["data"] == {"devices": {device_id: BOILER_ITEM}}
    # A 404 on an item is not a refused token.
    assert hass.config_entries.flow.async_progress() == []


@pytest.mark.usefixtures("no_token_in_logs")
async def test_identifiers_given_come_before_the_entity(
    hass: HomeAssistant,
    setup_entry: Callable[[], Any],
    aioclient_mock: AiohttpClientMocker,
    api: Callable[..., None],
    boiler: Callable[..., Any],
    created: list[Any],
) -> None:
    api()
    boiler(entity_area="Kitchen")
    entry = await setup_entry()

    response = await _report(hass, entry.entry_id, entity_id=ENTITY, room=HALLWAY, create_item=True)

    assert _matches(response) == ("none", "none")
    assert _calls(aioclient_mock, "post", REPORTS) == [{"title": TITLE, "room": HALLWAY}]
    assert _calls(aioclient_mock, "get", ROOMS) == []
    assert created == []


@pytest.mark.usefixtures("no_token_in_logs")
async def test_two_reports_at_once_from_one_device_add_one_item(
    hass: HomeAssistant,
    setup_entry: Callable[[], Any],
    aioclient_mock: AiohttpClientMocker,
    mock_api: None,
    boiler: Callable[..., Any],
) -> None:
    """Two automations firing together: the second finds the item the first added."""
    state = {"item": False, "report": False}

    async def items(method: str, url: Any, _data: Any) -> Any:
        await asyncio.sleep(0)
        rows = [_item(CREATED_ITEM, "Boiler")] if state["item"] else []
        return AiohttpClientMockResponse(method, url, json=_page(rows))

    async def create_item(method: str, url: Any, data: Any) -> Any:
        await asyncio.sleep(0)
        state["item"] = True
        return AiohttpClientMockResponse(
            method, url, status=201, json=_item(CREATED_ITEM, "Boiler")
        )

    async def reports(method: str, url: Any, _data: Any) -> Any:
        await asyncio.sleep(0)
        if dict(url.query)["status"] != "open" or not state["report"]:
            return AiohttpClientMockResponse(method, url, json=_page([]))
        # Once made, the waiting report is the one of this device.
        body = load("reports_open_after")["body"]
        row = {**body["results"][0], "title": TITLE, "item": CREATED_ITEM, "room": None}
        return AiohttpClientMockResponse(method, url, json=_page([row]))

    async def create_report(method: str, url: Any, _data: Any) -> Any:
        state["report"] = True
        data = load("report_created")
        return AiohttpClientMockResponse(method, url, status=data["status"], json=data["body"])

    aioclient_mock.get(ROOMS, json=load("rooms")["body"])
    aioclient_mock.get(f"{ITEMS}{CREATED_ITEM}/", json=_item(CREATED_ITEM, "Boiler"))
    aioclient_mock.get(ITEMS, side_effect=items)
    aioclient_mock.post(ITEMS, side_effect=create_item)
    aioclient_mock.get(REPORTS, side_effect=reports)
    aioclient_mock.post(REPORTS, side_effect=create_report)
    boiler(entity_area="Kitchen")
    entry = await setup_entry()

    first, second = await asyncio.gather(
        _report(hass, entry.entry_id, entity_id=ENTITY, create_item=True),
        _report(hass, entry.entry_id, entity_id=ENTITY, create_item=True),
    )

    assert sorted([first["item_match"], second["item_match"]]) == ["created", "linked"]
    assert len(_calls(aioclient_mock, "post", ITEMS)) == 1
    assert len(_calls(aioclient_mock, "post", REPORTS)) == 1
    assert first["report_id"] == second["report_id"]


@pytest.mark.usefixtures("no_token_in_logs")
async def test_a_viewer_who_cannot_add_items_still_reports_in_the_room(
    hass: HomeAssistant,
    setup_entry: Callable[[], Any],
    aioclient_mock: AiohttpClientMocker,
    api: Callable[..., None],
    boiler: Callable[..., Any],
) -> None:
    api(items={KITCHEN: []})
    aioclient_mock.post(
        ITEMS, status=403, json={"detail": "You do not have permission to perform this action."}
    )
    boiler(entity_area="Kitchen")
    entry = await setup_entry()

    response = await _report(hass, entry.entry_id, entity_id=ENTITY, create_item=True)

    assert _matches(response) == ("matched", "none")
    assert _calls(aioclient_mock, "post", REPORTS) == [{"title": TITLE, "room": KITCHEN}]


@pytest.mark.usefixtures("no_token_in_logs")
async def test_the_rooms_are_read_once_a_minute_at_most(
    hass: HomeAssistant,
    setup_entry: Callable[[], Any],
    aioclient_mock: AiohttpClientMocker,
    api: Callable[..., None],
    boiler: Callable[..., Any],
    freezer: Any,
) -> None:
    api(items={KITCHEN: []})
    boiler(entity_area="Kitchen")
    entry = await setup_entry()

    await _report(hass, entry.entry_id, entity_id=ENTITY)
    await _report(hass, entry.entry_id, entity_id=ENTITY)
    assert len(_calls(aioclient_mock, "get", ROOMS)) == 1

    freezer.tick(61)
    await _report(hass, entry.entry_id, entity_id=ENTITY)
    assert len(_calls(aioclient_mock, "get", ROOMS)) == 2


@pytest.mark.usefixtures("no_token_in_logs")
async def test_diagnostics_count_the_links_and_name_nothing(
    hass: HomeAssistant,
    setup_entry: Callable[[], Any],
    api: Callable[..., None],
    boiler: Callable[..., Any],
    created: list[Any],
) -> None:
    api(items={KITCHEN: []})
    _entity, device_id = boiler(entity_area="Kitchen")
    entry = await setup_entry()
    await _report(hass, entry.entry_id, entity_id=ENTITY, create_item=True)

    diagnostics = await async_get_config_entry_diagnostics(hass, entry)

    assert diagnostics["item_links"] == 1
    text = str(diagnostics)
    for secret in ("Boiler", "Kitchen", "Acme", device_id, CREATED_ITEM, KITCHEN):
        assert secret not in text


async def test_removing_the_home_forgets_its_links(
    hass: HomeAssistant,
    hass_storage: dict[str, Any],
    mock_entry: MockConfigEntry,
    setup_entry: Callable[[], Any],
    mock_api: None,
) -> None:
    _seed(hass_storage, mock_entry.entry_id, {"device": BOILER_ITEM})
    entry = await setup_entry()

    assert await hass.config_entries.async_remove(entry.entry_id)
    await hass.async_block_till_done()

    assert store_key(entry.entry_id) not in hass_storage
