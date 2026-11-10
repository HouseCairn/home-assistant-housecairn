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
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker

from custom_components.housecairn.const import CONF_HOME_ID, DOMAIN

FIXTURES = pathlib.Path(__file__).parent / "fixtures" / "api"
URL = "https://housecairn.example.com"
API = f"{URL}/api/v1"
# Not a real token: the shape of one (hc_ and 43 characters).
TOKEN = "hc_TESTtokenTESTtokenTESTtokenTESTtokenTESTtok"
NEW_TOKEN = "hc_NEWtokenNEWtokenNEWtokenNEWtokenNEWtokenNEW"
HOME_ID = "35d1afd8-747a-41a5-971f-a8701147c27b"
DAY = "2026-11-09"


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

    def register(path: str, name: str, params: dict[str, str] | None = None) -> None:
        data = load(name)
        aioclient_mock.get(f"{API}{path}", params=params, status=data["status"], json=data["body"])

    return register


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
