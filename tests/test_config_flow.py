"""The config flow: address and token, errors, one entry per home, reauthentication."""

from __future__ import annotations

import ssl
from collections.abc import Callable
from typing import Any
from unittest.mock import Mock

import aiohttp
import pytest
from homeassistant.config_entries import SOURCE_USER
from homeassistant.const import CONF_API_TOKEN, CONF_URL, CONF_VERIFY_SSL
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker

from custom_components.housecairn.const import CONF_HOME_ID, DOMAIN

from .conftest import API, HOME_ID, NEW_TOKEN, PROBE, TOKEN, URL, load

USER_INPUT = {CONF_URL: URL, CONF_API_TOKEN: TOKEN, CONF_VERIFY_SSL: True}
OTHER_HOME = "0b9f6c55-2f4e-4d8a-9a43-6e1f0d6c2a11"


async def _start(hass: HomeAssistant) -> dict[str, Any]:
    result: dict[str, Any] = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    return result


async def _submit(hass: HomeAssistant, flow_id: str, data: dict[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = await hass.config_entries.flow.async_configure(flow_id, data)
    return result


def _two_homes() -> dict[str, Any]:
    body = load("homes")["body"]
    other = {**body["results"][0], "id": OTHER_HOME, "name": "Holiday flat"}
    return {**body, "results": [*body["results"], other]}


@pytest.mark.usefixtures("mock_api")
async def test_one_home_creates_the_entry(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    result = await _start(hass)
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "user"

    result = await _submit(hass, result["flow_id"], {**USER_INPUT, CONF_URL: f" {URL}/ "})

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Main house"
    assert result["data"] == {**USER_INPUT, CONF_HOME_ID: HOME_ID}
    assert result["result"].unique_id == HOME_ID
    # The real call carried the token in the Authorization header only.
    method, url, _data, headers = aioclient_mock.mock_calls[0]
    assert (method, url.path) == ("GET", "/api/v1/homes/")
    assert headers["Authorization"] == f"Bearer {TOKEN}"
    assert TOKEN not in str(url)


@pytest.mark.usefixtures("no_token_in_logs")
@pytest.mark.parametrize(
    ("name", "exc", "error"),
    [
        ("homes_invalid_token", None, "invalid_auth"),
        ("homes_events_token", None, "insufficient_scope"),
        ("homes_locked", None, "home_locked"),
        (None, aiohttp.ClientConnectionError(), "cannot_connect"),
        (None, TimeoutError(), "cannot_connect"),
        (
            None,
            aiohttp.ClientConnectorCertificateError(
                Mock(), ssl.SSLCertVerificationError("certificate verify failed")
            ),
            "ssl_error",
        ),
    ],
)
async def test_errors_then_recovery(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    answer: Callable[..., None],
    name: str | None,
    exc: Exception | None,
    error: str,
) -> None:
    if name is not None:
        answer("/homes/", name)
    else:
        aioclient_mock.get(f"{API}/homes/", exc=exc)
    result = await _start(hass)

    result = await _submit(hass, result["flow_id"], USER_INPUT)

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": error}

    aioclient_mock.clear_requests()
    answer("/homes/", "homes")
    answer(PROBE, "write_probe_not_found", method="post")
    result = await _submit(hass, result["flow_id"], USER_INPUT)
    assert result["type"] is FlowResultType.CREATE_ENTRY


@pytest.mark.usefixtures("no_token_in_logs")
async def test_unexpected_answer(hass: HomeAssistant, aioclient_mock: AiohttpClientMocker) -> None:
    aioclient_mock.get(f"{API}/homes/", status=500, text="Server Error")
    result = await _start(hass)

    result = await _submit(hass, result["flow_id"], USER_INPUT)

    assert result["errors"] == {"base": "unknown"}


async def test_no_home(hass: HomeAssistant, aioclient_mock: AiohttpClientMocker) -> None:
    aioclient_mock.get(f"{API}/homes/", json={"next": None, "previous": None, "results": []})
    result = await _start(hass)

    result = await _submit(hass, result["flow_id"], USER_INPUT)

    assert result["errors"] == {"base": "no_homes"}


@pytest.mark.parametrize(
    "url", ["housecairn.example.com", "ftp://housecairn.example.com", "https://u:p@example.com"]
)
async def test_invalid_url(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker, url: str
) -> None:
    result = await _start(hass)

    result = await _submit(hass, result["flow_id"], {**USER_INPUT, CONF_URL: url})

    assert result["errors"] == {CONF_URL: "invalid_url"}
    assert aioclient_mock.call_count == 0


@pytest.mark.usefixtures("mock_api")
async def test_home_already_configured(hass: HomeAssistant, mock_entry: MockConfigEntry) -> None:
    mock_entry.add_to_hass(hass)
    result = await _start(hass)

    result = await _submit(hass, result["flow_id"], USER_INPUT)

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"


async def test_token_with_several_homes_asks_which(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    aioclient_mock.get(f"{API}/homes/", json=_two_homes())
    aioclient_mock.post(
        f"{API}{PROBE.replace(HOME_ID, OTHER_HOME)}",
        status=404,
        json={"detail": "No Occurrence matches"},
    )
    result = await _start(hass)

    result = await _submit(hass, result["flow_id"], USER_INPUT)
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "home"

    result = await _submit(hass, result["flow_id"], {CONF_HOME_ID: OTHER_HOME})

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Holiday flat"
    assert result["result"].unique_id == OTHER_HOME


async def test_several_homes_offers_only_those_not_configured(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker, mock_entry: MockConfigEntry
) -> None:
    mock_entry.add_to_hass(hass)
    aioclient_mock.get(f"{API}/homes/", json=_two_homes())
    result = await _start(hass)

    result = await _submit(hass, result["flow_id"], USER_INPUT)

    options = result["data_schema"].schema[CONF_HOME_ID].config["options"]
    assert [option["value"] for option in options] == [OTHER_HOME]


async def test_several_homes_all_configured(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker, mock_entry: MockConfigEntry
) -> None:
    mock_entry.add_to_hass(hass)
    MockConfigEntry(domain=DOMAIN, unique_id=OTHER_HOME, data={}).add_to_hass(hass)
    aioclient_mock.get(f"{API}/homes/", json=_two_homes())
    result = await _start(hass)

    result = await _submit(hass, result["flow_id"], USER_INPUT)

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"


# ---------- reauthentication ----------


async def test_reauth_saves_the_new_token(
    hass: HomeAssistant, answer: Callable[..., None], mock_entry: MockConfigEntry
) -> None:
    mock_entry.add_to_hass(hass)
    answer(f"/homes/{HOME_ID}/", "home")
    result = await mock_entry.start_reauth_flow(hass)
    assert result["step_id"] == "reauth_confirm"

    result = await _submit(hass, result["flow_id"], {CONF_API_TOKEN: NEW_TOKEN})

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reauth_successful"
    assert mock_entry.data[CONF_API_TOKEN] == NEW_TOKEN
    assert mock_entry.data[CONF_HOME_ID] == HOME_ID


@pytest.mark.usefixtures("no_token_in_logs")
@pytest.mark.parametrize(
    ("name", "error"),
    [
        ("homes_invalid_token", "invalid_auth"),
        ("homes_events_token", "insufficient_scope"),
        ("home_other", "wrong_home"),
        ("occurrences_locked", "home_locked"),
    ],
)
async def test_reauth_errors(
    hass: HomeAssistant,
    answer: Callable[..., None],
    aioclient_mock: AiohttpClientMocker,
    mock_entry: MockConfigEntry,
    name: str,
    error: str,
) -> None:
    mock_entry.add_to_hass(hass)
    answer(f"/homes/{HOME_ID}/", name)
    result = await mock_entry.start_reauth_flow(hass)

    result = await _submit(hass, result["flow_id"], {CONF_API_TOKEN: NEW_TOKEN})

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": error}
    assert mock_entry.data[CONF_API_TOKEN] == TOKEN


async def test_reauth_refuses_a_locked_home(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker, mock_entry: MockConfigEntry
) -> None:
    mock_entry.add_to_hass(hass)
    locked = load("homes_locked")["body"]["results"][0]
    aioclient_mock.get(f"{API}/homes/{HOME_ID}/", json=locked)
    result = await mock_entry.start_reauth_flow(hass)

    result = await _submit(hass, result["flow_id"], {CONF_API_TOKEN: NEW_TOKEN})

    assert result["errors"] == {"base": "home_locked"}


# ---------- the address, and what the token may do ----------


async def test_an_address_with_a_path_is_kept_in_every_request(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """Housecairn behind a prefix: the path is saved and every call goes through it."""
    base = "https://example.com/housecairn/api/v1"
    homes = load("homes")
    aioclient_mock.get(f"{base}/homes/", json=homes["body"])
    aioclient_mock.post(
        f"{base}/homes/{HOME_ID}/occurrences/00000000-0000-0000-0000-000000000000/undo/",
        status=404,
        json=load("write_probe_not_found")["body"],
    )
    result = await _start(hass)

    result = await _submit(
        hass, result["flow_id"], {**USER_INPUT, CONF_URL: "https://example.com/housecairn/"}
    )

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"][CONF_URL] == "https://example.com/housecairn"
    assert {url.path for _m, url, _d, _h in aioclient_mock.mock_calls} >= {
        "/housecairn/api/v1/homes/"
    }
    assert all(
        url.path.startswith("/housecairn/api/v1/") for _m, url, _d, _h in aioclient_mock.mock_calls
    )


@pytest.mark.usefixtures("mock_api")
@pytest.mark.parametrize("write_token", [False])
async def test_a_read_only_token_is_told_so_then_accepted(hass: HomeAssistant) -> None:
    result = await _start(hass)

    result = await _submit(hass, result["flow_id"], USER_INPUT)

    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "read_only"
    assert result["description_placeholders"] == {"home": "Main house"}
    result = await _submit(hass, result["flow_id"], {})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["result"].unique_id == HOME_ID


@pytest.mark.usefixtures("mock_api")
async def test_a_token_that_can_write_is_not_told_anything(hass: HomeAssistant) -> None:
    result = await _start(hass)

    result = await _submit(hass, result["flow_id"], USER_INPUT)

    assert result["type"] is FlowResultType.CREATE_ENTRY


@pytest.mark.usefixtures("no_token_in_logs")
async def test_the_scope_cannot_be_told_aborts_the_flow(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker, answer: Callable[..., None]
) -> None:
    aioclient_mock.clear_requests()
    answer("/homes/", "homes")
    aioclient_mock.post(f"{API}{PROBE}", exc=aiohttp.ClientConnectionError())
    result = await _start(hass)

    result = await _submit(hass, result["flow_id"], USER_INPUT)

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "probe_failed"


@pytest.mark.parametrize("status", [400, 405, 500, 200])
@pytest.mark.usefixtures("no_token_in_logs")
async def test_an_unexpected_probe_answer_gives_a_read_only_entry(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    answer: Callable[..., None],
    status: int,
) -> None:
    """The scope stays unknown, which is no reason to refuse a token that can read."""
    aioclient_mock.clear_requests()
    answer("/homes/", "homes")
    aioclient_mock.post(f"{API}{PROBE}", status=status, json=load("occurrence_done")["body"])
    result = await _start(hass)

    result = await _submit(hass, result["flow_id"], USER_INPUT)

    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "read_only"
    result = await _submit(hass, result["flow_id"], {})
    assert result["type"] is FlowResultType.CREATE_ENTRY


@pytest.mark.parametrize("status", [400, 405, 500, 200])
async def test_reauth_with_an_unexpected_probe_answer_saves_the_token(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    answer: Callable[..., None],
    mock_entry: MockConfigEntry,
    status: int,
) -> None:
    mock_entry.add_to_hass(hass)
    aioclient_mock.clear_requests()
    answer(f"/homes/{HOME_ID}/", "home")
    aioclient_mock.post(f"{API}{PROBE}", status=status, json=load("occurrence_done")["body"])
    result = await mock_entry.start_reauth_flow(hass)

    result = await _submit(hass, result["flow_id"], {CONF_API_TOKEN: NEW_TOKEN})

    assert result["step_id"] == "reauth_read_only"
    result = await _submit(hass, result["flow_id"], {})
    assert result["reason"] == "reauth_successful"
    assert mock_entry.data[CONF_API_TOKEN] == NEW_TOKEN


@pytest.mark.parametrize("write_token", [False])
async def test_reauth_with_a_read_only_token_says_so_then_saves_it(
    hass: HomeAssistant, answer: Callable[..., None], mock_entry: MockConfigEntry
) -> None:
    mock_entry.add_to_hass(hass)
    answer(f"/homes/{HOME_ID}/", "home")
    result = await mock_entry.start_reauth_flow(hass)

    result = await _submit(hass, result["flow_id"], {CONF_API_TOKEN: NEW_TOKEN})

    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "reauth_read_only"
    assert mock_entry.data[CONF_API_TOKEN] == TOKEN
    result = await _submit(hass, result["flow_id"], {})
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reauth_successful"
    assert mock_entry.data[CONF_API_TOKEN] == NEW_TOKEN
