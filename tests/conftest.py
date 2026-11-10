"""Shared fixtures: the Housecairn API is simulated with answers it really gave.

tests/fixtures/api/*.json were captured from Housecairn (main branch) through its
own test client, with tokens issued by its services: `status` and `body` are
those of the real answer. The dates in them are relative to 2026-11-09, the
"today" of the instance at capture time, hence the frozen clock below.
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
def mock_api(answer: Callable[..., None]) -> None:
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
    """Whether a task was marked done: the lists then answer as Housecairn does after it."""
    return {"done": False}


def _lists(
    aioclient_mock: AiohttpClientMocker,
    state: dict[str, bool],
    path: str,
    params: dict[str, str],
    before: str,
    after: str,
) -> None:
    """A list that changes once `state["done"]` is set: both answers were captured."""

    async def serve(method: str, url: Any, _data: Any) -> AiohttpClientMockResponse:
        data = load(after if state["done"] else before)
        return AiohttpClientMockResponse(method, url, status=data["status"], json=data["body"])

    aioclient_mock.request("get", f"{API}{path}", params=params, side_effect=serve)


@pytest.fixture
def mock_todo_api(
    answer: Callable[..., None], aioclient_mock: AiohttpClientMocker, todo_state: dict[str, bool]
) -> None:
    """A home with rooms: one task overdue, two due today, one in five days.

    A task due in ten days is hidden until the 16th, another is due past the two weeks
    of the list: neither is in the to-do list.
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
    )
    _lists(
        aioclient_mock,
        todo_state,
        occurrences,
        {"status": "open", "due_after": DAY, "include_hidden": "true"},
        "todo_upcoming",
        "todo_upcoming_after",
    )
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
