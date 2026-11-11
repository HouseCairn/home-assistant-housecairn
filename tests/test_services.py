"""The action housecairn.report: report a problem in a home from an automation."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import Any

import aiohttp
import probatio as vol
import pytest
from homeassistant.config_entries import SOURCE_REAUTH
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.setup import async_setup_component
from pytest_homeassistant_custom_component.test_util.aiohttp import (
    AiohttpClientMocker,
    AiohttpClientMockResponse,
)

from custom_components.housecairn.const import DOMAIN

from .conftest import API, HOME_ID, TOKEN, load

REPORTS = f"{API}/homes/{HOME_ID}/reports/"
# Captured in the same scenario as the reports: an item of the hallway.
DETECTOR = "4f51cf6f-8837-452c-b04e-3f81344cd9df"
HALLWAY = "978c6a38-de2c-4c8e-8eff-ee38d0536a82"
REPORTED = "Smoke detector battery low"
# An article of the home (any identifier would do: it is only sent as the place).
SPARE_BATTERY = "2a9c0edf-e533-4d21-b185-0913b8654f08"


def _reports(aioclient_mock: AiohttpClientMocker, open_name: str, task_name: str) -> None:
    """The reports of the caller that are not closed: open ones, and made into a task."""
    for status, name in (("open", open_name), ("task", task_name)):
        aioclient_mock.get(
            REPORTS, params={"status": status, "mine": "true"}, json=load(name)["body"]
        )


def _created(aioclient_mock: AiohttpClientMocker, name: str = "report_created") -> None:
    data = load(name)
    aioclient_mock.post(REPORTS, status=data["status"], json=data["body"])


async def _report(hass: HomeAssistant, entry_id: str, **fields: Any) -> Any:
    return await hass.services.async_call(
        DOMAIN,
        "report",
        {"config_entry_id": entry_id, **fields},
        blocking=True,
        return_response=True,
    )


def _post_bodies(aioclient_mock: AiohttpClientMocker) -> list[Any]:
    return [
        data
        for method, url, data, _h in aioclient_mock.mock_calls
        if method.lower() == "post" and url.path.endswith("/reports/")
    ]


@pytest.mark.usefixtures("mock_api", "no_token_in_logs")
async def test_a_report_is_created_and_its_identifier_returned(
    hass: HomeAssistant, setup_entry: Callable[[], Any], aioclient_mock: AiohttpClientMocker
) -> None:
    _reports(aioclient_mock, "reports_open_before", "reports_task_none")
    _created(aioclient_mock)
    entry = await setup_entry()

    response = await _report(hass, entry.entry_id, title=f"  {REPORTED} ", item=DETECTOR)

    created = load("report_created")["body"]
    assert response == {"report_id": created["id"], "created": True, "status": "open"}
    # The title is sent as Housecairn keeps it, with the one place given.
    assert _post_bodies(aioclient_mock) == [{"title": REPORTED, "item": DETECTOR}]
    for method, url, _data, headers in aioclient_mock.mock_calls:
        if url.path.endswith("/reports/"):
            assert headers["Authorization"] == f"Bearer {TOKEN}"
            assert method.lower() in ("get", "post")


@pytest.mark.usefixtures("mock_api", "no_token_in_logs")
async def test_the_same_report_still_open_is_not_made_twice(
    hass: HomeAssistant, setup_entry: Callable[[], Any], aioclient_mock: AiohttpClientMocker
) -> None:
    _reports(aioclient_mock, "reports_open_after", "reports_task_none")
    _created(aioclient_mock)
    entry = await setup_entry()

    response = await _report(hass, entry.entry_id, title=REPORTED.upper(), item=DETECTOR)

    existing = load("report_created")["body"]
    assert response == {"report_id": existing["id"], "created": False, "status": "open"}
    assert _post_bodies(aioclient_mock) == []


@pytest.mark.usefixtures("mock_api", "no_token_in_logs")
async def test_white_space_inside_the_title_does_not_make_another_report(
    hass: HomeAssistant, setup_entry: Callable[[], Any], aioclient_mock: AiohttpClientMocker
) -> None:
    """Housecairn folds runs of white space: the title sent must equal the one it returns."""
    _reports(aioclient_mock, "reports_open_after", "reports_task_none")
    _created(aioclient_mock)
    entry = await setup_entry()

    response = await _report(
        hass, entry.entry_id, title="Smoke  detector \t battery   low", item=DETECTOR
    )

    existing = load("reports_open_after")["body"]["results"][0]
    assert response == {"report_id": existing["id"], "created": False, "status": "open"}
    assert _post_bodies(aioclient_mock) == []


@pytest.mark.usefixtures("mock_api", "no_token_in_logs")
async def test_a_report_made_into_a_task_is_not_made_again(
    hass: HomeAssistant, setup_entry: Callable[[], Any], aioclient_mock: AiohttpClientMocker
) -> None:
    """Made into a task is not closed: the problem is still being dealt with."""
    _reports(aioclient_mock, "reports_task_none", "reports_task_one")
    _created(aioclient_mock)
    entry = await setup_entry()
    task = load("reports_task_one")["body"]["results"][0]

    response = await _report(hass, entry.entry_id, title=task["title"])

    assert response == {"report_id": task["id"], "created": False, "status": "task"}
    assert _post_bodies(aioclient_mock) == []


@pytest.mark.usefixtures("mock_api", "no_token_in_logs")
@pytest.mark.parametrize(
    "fields",
    [
        # Another place, or none, is another problem.
        {"title": REPORTED},
        {"title": REPORTED, "room": HALLWAY},
        # Only the room differs from a report without a place.
        {"title": "Front door lock is stiff", "room": HALLWAY},
        # Another title at the same place too.
        {"title": "Smoke detector beeps", "item": DETECTOR},
        # Only the article differs from a report without a place.
        {"title": "Front door lock is stiff", "article": SPARE_BATTERY},
    ],
)
async def test_another_title_or_place_is_another_report(
    hass: HomeAssistant,
    setup_entry: Callable[[], Any],
    aioclient_mock: AiohttpClientMocker,
    fields: dict[str, str],
) -> None:
    _reports(aioclient_mock, "reports_open_after", "reports_task_none")
    _created(aioclient_mock)
    entry = await setup_entry()

    response = await _report(hass, entry.entry_id, **fields)

    assert response["created"] is True
    assert _post_bodies(aioclient_mock) == [fields]


@pytest.mark.usefixtures("mock_api", "no_token_in_logs")
async def test_two_reports_at_once_make_one(
    hass: HomeAssistant, setup_entry: Callable[[], Any], aioclient_mock: AiohttpClientMocker
) -> None:
    """Two automations firing together: the second finds the report of the first."""
    state = {"created": False}

    async def reports(method: str, url: Any, _data: Any) -> Any:
        # Let the other call run meanwhile, as a real request would.
        await asyncio.sleep(0)
        status = dict(url.query)["status"]
        name = "reports_task_none"
        if status == "open":
            name = "reports_open_after" if state["created"] else "reports_open_before"
        return AiohttpClientMockResponse(method, url, json=load(name)["body"])

    async def create(method: str, url: Any, _data: Any) -> Any:
        state["created"] = True
        data = load("report_created")
        return AiohttpClientMockResponse(method, url, status=data["status"], json=data["body"])

    aioclient_mock.get(REPORTS, side_effect=reports)
    aioclient_mock.post(REPORTS, side_effect=create)
    entry = await setup_entry()

    first, second = await asyncio.gather(
        _report(hass, entry.entry_id, title=REPORTED, item=DETECTOR),
        _report(hass, entry.entry_id, title=REPORTED, item=DETECTOR),
    )

    assert sorted([first["created"], second["created"]]) == [False, True]
    assert first["report_id"] == second["report_id"]
    assert len(_post_bodies(aioclient_mock)) == 1


@pytest.mark.usefixtures("mock_api", "no_token_in_logs")
@pytest.mark.parametrize("write_token", [False])
async def test_a_token_without_write_is_refused_clearly_and_nothing_is_sent(
    hass: HomeAssistant, setup_entry: Callable[[], Any], aioclient_mock: AiohttpClientMocker
) -> None:
    entry = await setup_entry()
    before = aioclient_mock.call_count

    with pytest.raises(ServiceValidationError) as raised:
        await _report(hass, entry.entry_id, title=REPORTED)

    assert raised.value.translation_key == "report_needs_write"
    assert raised.value.translation_placeholders == {"home": "Main house"}
    assert aioclient_mock.call_count == before


@pytest.mark.usefixtures("mock_api", "no_token_in_logs")
async def test_write_lost_since_setup_is_refused_clearly(
    hass: HomeAssistant, setup_entry: Callable[[], Any], aioclient_mock: AiohttpClientMocker
) -> None:
    _reports(aioclient_mock, "reports_open_before", "reports_task_none")
    _created(aioclient_mock, "report_forbidden")
    entry = await setup_entry()

    with pytest.raises(ServiceValidationError) as raised:
        await _report(hass, entry.entry_id, title=REPORTED)

    assert raised.value.translation_key == "report_needs_write"
    assert entry.runtime_data.can_write is False


@pytest.mark.usefixtures("mock_api", "no_token_in_logs")
@pytest.mark.parametrize(
    ("name", "shown"),
    [
        ("report_unknown_place", "room: Invalid pk"),
        ("report_too_many", "You already have 20 reports waiting"),
    ],
)
async def test_a_refused_report_says_why(
    hass: HomeAssistant,
    setup_entry: Callable[[], Any],
    aioclient_mock: AiohttpClientMocker,
    name: str,
    shown: str,
) -> None:
    _reports(aioclient_mock, "reports_open_before", "reports_task_none")
    _created(aioclient_mock, name)
    entry = await setup_entry()

    with pytest.raises(ServiceValidationError) as raised:
        await _report(hass, entry.entry_id, title="One more", room=HALLWAY)

    assert raised.value.translation_key == "report_refused"
    assert shown in raised.value.translation_placeholders["error"]  # type: ignore[index]


@pytest.mark.usefixtures("mock_api")
@pytest.mark.parametrize(
    "fields",
    [
        {"title": "x" * 201},
        {"title": "   "},
        {"title": REPORTED, "room": HALLWAY, "item": DETECTOR},
        {"title": REPORTED, "room": "not-an-identifier"},
        {},
    ],
)
async def test_invalid_fields_are_refused_before_any_request(
    hass: HomeAssistant,
    setup_entry: Callable[[], Any],
    aioclient_mock: AiohttpClientMocker,
    fields: dict[str, str],
) -> None:
    """At most 200 characters and one place, as in Housecairn (report_two_places.json)."""
    entry = await setup_entry()
    before = aioclient_mock.call_count

    with pytest.raises(vol.Invalid):
        await _report(hass, entry.entry_id, **fields)

    assert aioclient_mock.call_count == before


@pytest.mark.usefixtures("mock_api", "no_token_in_logs")
async def test_200_characters_are_accepted(
    hass: HomeAssistant, setup_entry: Callable[[], Any], aioclient_mock: AiohttpClientMocker
) -> None:
    _reports(aioclient_mock, "reports_open_before", "reports_task_none")
    _created(aioclient_mock)
    entry = await setup_entry()

    await _report(hass, entry.entry_id, title="x" * 200)

    assert _post_bodies(aioclient_mock) == [{"title": "x" * 200}]


@pytest.mark.usefixtures("mock_api", "no_token_in_logs")
@pytest.mark.parametrize("name", ["occurrences_locked", "sso_provider_changed"])
async def test_a_home_the_token_cannot_open_asks_for_a_new_token(
    hass: HomeAssistant,
    setup_entry: Callable[[], Any],
    aioclient_mock: AiohttpClientMocker,
    name: str,
) -> None:
    data = load(name)
    aioclient_mock.get(REPORTS, status=data["status"], json=data["body"])
    entry = await setup_entry()

    with pytest.raises(HomeAssistantError) as raised:
        await _report(hass, entry.entry_id, title=REPORTED)

    assert raised.value.translation_key == "sso_required"
    await hass.async_block_till_done()
    flows = hass.config_entries.flow.async_progress()
    assert [(f["context"]["source"], f["step_id"]) for f in flows] == [
        (SOURCE_REAUTH, "reauth_sso")
    ]


@pytest.mark.usefixtures("mock_api", "no_token_in_logs")
async def test_a_refused_token_asks_for_a_new_one(
    hass: HomeAssistant, setup_entry: Callable[[], Any], aioclient_mock: AiohttpClientMocker
) -> None:
    aioclient_mock.get(REPORTS, status=401, json={"detail": "Invalid, expired or revoked token."})
    entry = await setup_entry()

    with pytest.raises(HomeAssistantError) as raised:
        await _report(hass, entry.entry_id, title=REPORTED)

    assert raised.value.translation_key == "auth_failed"
    await hass.async_block_till_done()
    flows = hass.config_entries.flow.async_progress()
    assert [(f["context"]["source"], f["step_id"]) for f in flows] == [
        (SOURCE_REAUTH, "reauth_confirm")
    ]


@pytest.mark.usefixtures("mock_api", "no_token_in_logs")
async def test_housecairn_unreachable(
    hass: HomeAssistant, setup_entry: Callable[[], Any], aioclient_mock: AiohttpClientMocker
) -> None:
    aioclient_mock.get(REPORTS, exc=aiohttp.ClientConnectionError())
    entry = await setup_entry()

    with pytest.raises(HomeAssistantError) as raised:
        await _report(hass, entry.entry_id, title=REPORTED)

    assert raised.value.translation_key == "cannot_connect"


@pytest.mark.usefixtures("mock_api")
async def test_an_entry_that_is_not_loaded_is_refused(
    hass: HomeAssistant, setup_entry: Callable[[], Any]
) -> None:
    entry = await setup_entry()
    await hass.config_entries.async_unload(entry.entry_id)

    with pytest.raises(ServiceValidationError) as raised:
        await _report(hass, entry.entry_id, title=REPORTED)

    assert raised.value.translation_key == "service_config_entry_not_loaded"


async def test_the_action_exists_without_any_home(hass: HomeAssistant) -> None:
    assert await async_setup_component(hass, DOMAIN, {})

    assert hass.services.has_service(DOMAIN, "report")
