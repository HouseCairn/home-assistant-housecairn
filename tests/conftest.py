"""Shared fixtures: the Housecairn API is simulated with answers it really gave.

tests/fixtures/api/*.json were captured from Housecairn (main branch) through its
own test client, with tokens issued by its services: `status` and `body` are
those of the real answer. The dates in them are relative to 2026-11-09, the
"today" of the instance at capture time, hence the frozen clock below. The files
of the to-do list, the undo, the reports and the sign-in provider were captured
again for lot 3 in one scenario (Housecairn main 0aa93f1), so their identifiers
match each other.
"""

from __future__ import annotations

import json
import pathlib
from collections.abc import Callable, Iterator
from typing import Any

import pytest
from homeassistant.const import CONF_API_TOKEN, CONF_URL, CONF_VERIFY_SSL
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.test_util.aiohttp import (
    AiohttpClientMocker,
    AiohttpClientMockResponse,
)

from custom_components.housecairn.const import CONF_HOME_ID, DOMAIN

FIXTURES = pathlib.Path(__file__).parent / "fixtures" / "api"
URL = "https://housecairn.example.com"
API = f"{URL}/api/v1"
# Not a real token: the shape of one (hc_ and 43 characters).
TOKEN = "hc_TESTtokenTESTtokenTESTtokenTESTtokenTESTtok"
NEW_TOKEN = "hc_NEWtokenNEWtokenNEWtokenNEWtokenNEWtokenNEW"
HOME_ID = "35d1afd8-747a-41a5-971f-a8701147c27b"
DAY = "2026-11-09"
# The occurrence that cannot exist, which the integration uses to probe the write scope.
PROBE = f"/homes/{HOME_ID}/occurrences/00000000-0000-0000-0000-000000000000/undo/"
# The two lists of the to-do list that lot 3 added: tasks without a date, and the tasks
# done in the last seven days (today and the six days before).
UNDATED = {"due": "none"}
DONE_SINCE = {"status": "done", "closed_after": "2026-11-03", "ordering": "recent"}
# A list with nothing in it, as every list of the API answers it.
EMPTY_PAGE: dict[str, Any] = {"next": None, "previous": None, "results": []}


def load(name: str) -> dict[str, Any]:
    """A captured answer: {"status": ..., "body": ...}."""
    data: dict[str, Any] = json.loads((FIXTURES / f"{name}.json").read_text())
    return data


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations: None) -> None:
    """Load custom_components/ in every test."""


@pytest.fixture(autouse=True)
def frozen_day(freezer: Any) -> None:
    """Noon UTC on the day of the capture: the same date in the test time zone."""
    freezer.move_to(f"{DAY}T12:00:00+00:00")


@pytest.fixture
def answer(aioclient_mock: AiohttpClientMocker) -> Callable[..., None]:
    """Register a captured answer for a path of the API, optionally for some parameters."""

    def register(
        path: str, name: str, params: dict[str, str] | None = None, method: str = "get"
    ) -> None:
        data = load(name)
        aioclient_mock.request(
            method, f"{API}{path}", params=params, status=data["status"], json=data["body"]
        )

    return register


@pytest.fixture
def write_token() -> bool:
    """Whether the token of the test has the `write` scope (override to change it)."""
    return True


@pytest.fixture(autouse=True)
def mock_write_probe(answer: Callable[..., None], write_token: bool) -> None:
    """The probe of the write scope, answered as a token with or without it would be."""
    answer(
        PROBE, "write_probe_not_found" if write_token else "write_probe_forbidden", method="post"
    )


@pytest.fixture
def mock_api(answer: Callable[..., None], aioclient_mock: AiohttpClientMocker) -> None:
    """A home with two overdue tasks, two due today, one later, two stock items low."""
    answer("/homes/", "homes")
    answer(f"/homes/{HOME_ID}/", "home")
    answer(f"/homes/{HOME_ID}/occurrences/", "occurrences_overdue", {"overdue": "true"})
    answer(
        f"/homes/{HOME_ID}/occurrences/",
        "occurrences_open_from_today",
        {"status": "open", "due_after": DAY, "include_hidden": "true"},
    )
    answer(f"/homes/{HOME_ID}/articles/", "articles_low", {"low": "true"})
    empty_lists(aioclient_mock)


def empty_lists(aioclient_mock: AiohttpClientMocker) -> None:
    """No task without a date, nothing done lately: the lists the sensors do not use."""
    aioclient_mock.get(f"{API}/homes/{HOME_ID}/tasks/", params=UNDATED, json=EMPTY_PAGE)
    aioclient_mock.get(f"{API}/homes/{HOME_ID}/occurrences/", params=DONE_SINCE, json=EMPTY_PAGE)


@pytest.fixture
def mock_entry() -> MockConfigEntry:
    return MockConfigEntry(
        domain=DOMAIN,
        title="Main house",
        unique_id=HOME_ID,
        data={
            CONF_URL: URL,
            CONF_API_TOKEN: TOKEN,
            CONF_VERIFY_SSL: True,
            CONF_HOME_ID: HOME_ID,
        },
    )


@pytest.fixture
def setup_entry(hass: HomeAssistant, mock_entry: MockConfigEntry) -> Callable[[], Any]:
    async def setup() -> MockConfigEntry:
        mock_entry.add_to_hass(hass)
        await hass.config_entries.async_setup(mock_entry.entry_id)
        await hass.async_block_till_done()
        return mock_entry

    return setup


@pytest.fixture
def no_token_in_logs(caplog: pytest.LogCaptureFixture) -> Iterator[None]:
    """Fail if a token appears in the logs of the test, tracebacks included."""
    caplog.set_level("DEBUG")
    yield
    assert TOKEN not in caplog.text
    assert NEW_TOKEN not in caplog.text


@pytest.fixture
def todo_state() -> dict[str, bool]:
    """What changed in Housecairn: the lists then answer as it did after the change.

    `done`: the kettle was marked done. `undone`: the "Done" of the oven was taken back.
    """
    return {"done": False, "undone": False}


def _lists(
    aioclient_mock: AiohttpClientMocker,
    state: dict[str, bool],
    path: str,
    params: dict[str, str],
    before: str,
    after: str,
    undone: str | None = None,
) -> None:
    """A list that changes with `todo_state`: every answer was captured."""

    async def serve(method: str, url: Any, _data: Any) -> AiohttpClientMockResponse:
        name = before
        if state["done"]:
            name = after
        if state["undone"] and undone is not None:
            name = undone
        data = load(name)
        return AiohttpClientMockResponse(method, url, status=data["status"], json=data["body"])

    aioclient_mock.request("get", f"{API}{path}", params=params, side_effect=serve)


@pytest.fixture
def mock_todo_api(
    answer: Callable[..., None], aioclient_mock: AiohttpClientMocker, todo_state: dict[str, bool]
) -> None:
    """A home with rooms: one task overdue, two due today, one in five days, two
    without a date, and two done in the last days (the oven and the water softener).

    A task due in ten days is hidden until the 16th, another is due past the two weeks
    of the list: neither is in the to-do list. A task done twelve days ago is not either.
    """
    answer("/homes/", "homes")
    answer(f"/homes/{HOME_ID}/", "home")
    occurrences = f"/homes/{HOME_ID}/occurrences/"
    _lists(
        aioclient_mock,
        todo_state,
        occurrences,
        {"overdue": "true"},
        "todo_overdue",
        "todo_overdue_after",
        "todo_overdue_undone",
    )
    _lists(
        aioclient_mock,
        todo_state,
        occurrences,
        {"status": "open", "due_after": DAY, "include_hidden": "true"},
        "todo_upcoming",
        "todo_upcoming_after",
    )
    # Captured after the kettle was done: the kettle is open in the upcoming list of
    # "before", and is then shown there only.
    _lists(
        aioclient_mock,
        todo_state,
        occurrences,
        DONE_SINCE,
        "todo_done",
        "todo_done_after",
        "todo_done_undone_only",
    )
    answer(f"/homes/{HOME_ID}/tasks/", "todo_undated", UNDATED)
    answer(f"/homes/{HOME_ID}/articles/", "articles_low", {"low": "true"})
    answer(f"/homes/{HOME_ID}/rooms/", "rooms")


@pytest.fixture
def complete(
    aioclient_mock: AiohttpClientMocker, todo_state: dict[str, bool]
) -> Callable[..., None]:
    """Register the answer of `complete` for an occurrence; a 200 flips the lists."""

    def register(occurrence: str, name: str, *, done: bool | None = None) -> None:
        data = load(name)
        flips = data["status"] == 200 if done is None else done

        async def serve(method: str, url: Any, _data: Any) -> AiohttpClientMockResponse:
            todo_state["done"] = flips
            return AiohttpClientMockResponse(method, url, status=data["status"], json=data["body"])

        aioclient_mock.request(
            "post",
            f"{API}/homes/{HOME_ID}/occurrences/{occurrence}/complete/",
            side_effect=serve,
        )

    return register


@pytest.fixture
def undo(aioclient_mock: AiohttpClientMocker, todo_state: dict[str, bool]) -> Callable[..., None]:
    """Register the answer of `undo` for an occurrence; a 200 flips the lists."""

    def register(occurrence: str, name: str) -> None:
        data = load(name)

        async def serve(method: str, url: Any, _data: Any) -> AiohttpClientMockResponse:
            if data["status"] == 200:
                todo_state["undone"] = True
            return AiohttpClientMockResponse(method, url, status=data["status"], json=data["body"])

        aioclient_mock.request(
            "post",
            f"{API}/homes/{HOME_ID}/occurrences/{occurrence}/undo/",
            side_effect=serve,
        )

    return register
