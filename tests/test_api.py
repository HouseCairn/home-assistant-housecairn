"""The client of the API: an address with a path, the write probe, refusals."""

from __future__ import annotations

import datetime

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker

from custom_components.housecairn.api import (
    HouseCairnClient,
    HouseCairnRejectedError,
    HouseCairnResponseError,
    normalize_url,
)

from .conftest import HOME_ID, TOKEN, load

PREFIXED = "https://example.com/housecairn/"
BASE = "https://example.com/housecairn/api/v1"
OCCURRENCES = f"{BASE}/homes/{HOME_ID}/occurrences/"
OCCURRENCE = "4a3d1a74-1249-4025-82c4-fbb4fd874ef9"


def _client(hass: HomeAssistant, url: str = PREFIXED) -> HouseCairnClient:
    return HouseCairnClient(async_get_clientsession(hass), url, TOKEN)


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("https://example.com", "https://example.com"),
        ("https://example.com/", "https://example.com"),
        (" https://example.com/housecairn/ ", "https://example.com/housecairn"),
        ("http://192.0.2.10:8000/a/b//", "http://192.0.2.10:8000/a/b"),
    ],
)
def test_the_path_of_the_address_is_kept(url: str, expected: str) -> None:
    assert normalize_url(url) == expected


async def test_every_request_keeps_the_path_of_the_address(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """Behind a prefix, the lists, their next page, the probe and "Done" all keep it."""
    overdue = load("todo_overdue")["body"]
    first, *_ = overdue["results"]
    # The server writes its own idea of the host in `next`: only the cursor is used.
    page1 = {**overdue, "next": "http://testserver/api/v1/x/?cursor=abc", "results": [first]}
    aioclient_mock.get(OCCURRENCES, params={"overdue": "true", "cursor": "abc"}, json=overdue)
    aioclient_mock.get(OCCURRENCES, params={"overdue": "true"}, json=page1)
    aioclient_mock.get(f"{BASE}/homes/{HOME_ID}/rooms/", json=load("rooms")["body"])
    aioclient_mock.get(f"{OCCURRENCES}{OCCURRENCE}/", json=load("occurrence_done")["body"])
    aioclient_mock.post(f"{OCCURRENCES}{OCCURRENCE}/complete/", json=load("complete_ok")["body"])
    aioclient_mock.post(
        f"{OCCURRENCES}00000000-0000-0000-0000-000000000000/undo/",
        status=404,
        json=load("write_probe_not_found")["body"],
    )
    client = _client(hass)

    rows = await client.overdue(HOME_ID)
    await client.rooms(HOME_ID)
    occurrence = await client.occurrence(HOME_ID, OCCURRENCE)
    await client.complete(HOME_ID, OCCURRENCE)
    can_write = await client.has_write_scope(HOME_ID)

    assert len(rows.items) == 2
    assert rows.complete is True
    assert occurrence.is_closed is True
    assert can_write is True
    assert aioclient_mock.call_count == 6
    for _method, url, _data, headers in aioclient_mock.mock_calls:
        assert url.host == "example.com"
        assert url.path.startswith("/housecairn/api/v1/")
        assert headers["Authorization"] == f"Bearer {TOKEN}"


async def test_the_write_probe_says_no_without_the_scope(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    undo = f"{OCCURRENCES}00000000-0000-0000-0000-000000000000/undo/"
    data = load("write_probe_forbidden")
    aioclient_mock.post(undo, status=data["status"], json=data["body"])

    assert await _client(hass).has_write_scope(HOME_ID) is False


async def test_the_write_probe_never_changes_anything_even_if_accepted(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """A server that accepted the probe would be one this client does not understand."""
    aioclient_mock.post(
        f"{OCCURRENCES}00000000-0000-0000-0000-000000000000/undo/",
        json=load("occurrence_done")["body"],
    )

    with pytest.raises(HouseCairnResponseError):
        await _client(hass).has_write_scope(HOME_ID)


async def test_a_refusal_carries_the_message_for_the_logs(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    data = load("complete_closed")
    aioclient_mock.post(
        f"{OCCURRENCES}{OCCURRENCE}/complete/", status=data["status"], json=data["body"]
    )

    with pytest.raises(HouseCairnRejectedError) as raised:
        await _client(hass).complete(HOME_ID, OCCURRENCE)

    assert raised.value.detail == "This occurrence is already closed."
    assert TOKEN not in str(raised.value)


async def test_occurrences_up_to_a_day_are_read_whole_pages_at_a_time(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    upcoming = load("todo_upcoming")["body"]
    aioclient_mock.get(OCCURRENCES, json=upcoming)
    day = datetime.date(2026, 11, 9)

    rows = await _client(hass).open_from(HOME_ID, day, day + datetime.timedelta(days=14))

    assert [row.task_title for row in rows.items][-1] == "Clean the gutters"
    assert rows.complete is True
    # A hidden row carries the date from which it shows.
    hidden = next(row for row in rows.items if row.task_title == "Bleed the radiators")
    assert hidden.visible_from == datetime.date(2026, 11, 16)
