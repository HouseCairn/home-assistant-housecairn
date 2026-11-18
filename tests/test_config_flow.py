"""The config flow: address and token, errors, one entry per home, reauthentication,
and the Housecairn app of Home Assistant found by discovery."""

from __future__ import annotations

import json
import pathlib
import ssl
from collections.abc import Callable
from typing import Any
from unittest.mock import Mock

import aiohttp
import pytest
from homeassistant.config_entries import SOURCE_HASSIO, SOURCE_IGNORE, SOURCE_USER, ConfigEntryState
from homeassistant.const import CONF_API_TOKEN, CONF_URL, CONF_VERIFY_SSL
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers.service_info.hassio import HassioServiceInfo
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker

from custom_components.housecairn.const import CONF_HOME_ID, DOMAIN

from .conftest import API, HOME_ID, NEW_TOKEN, PROBE, TOKEN, URL, load

USER_INPUT = {CONF_URL: URL, CONF_API_TOKEN: TOKEN, CONF_VERIFY_SSL: True}
OTHER_HOME = "0b9f6c55-2f4e-4d8a-9a43-6e1f0d6c2a11"
STRINGS = pathlib.Path(__file__).parents[1] / "custom_components" / "housecairn" / "strings.json"


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


# ---------- a home that requires a sign-in provider ----------


def _through_the_provider(name: str) -> dict[str, Any]:
    """An answer captured with a token created through the provider, for HOME_ID."""
    body: dict[str, Any] = load(name)["body"]
    if "results" in body:
        return {**body, "results": [{**row, "id": HOME_ID} for row in body["results"]]}
    return {**body, "id": HOME_ID}


@pytest.mark.usefixtures("no_token_in_logs")
async def test_a_token_created_through_the_provider_adds_the_home(
    hass: HomeAssistant, answer: Callable[..., None], aioclient_mock: AiohttpClientMocker
) -> None:
    """The home requires a provider, and the token carries it: `locked` is false."""
    homes = _through_the_provider("sso_token_homes")
    assert homes["results"][0]["required_provider"]
    assert homes["results"][0]["locked"] is False
    aioclient_mock.get(f"{API}/homes/", json=homes)
    result = await _start(hass)

    result = await _submit(hass, result["flow_id"], USER_INPUT)

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"][CONF_HOME_ID] == HOME_ID


async def test_a_token_created_without_the_provider_says_how_to_make_one(
    hass: HomeAssistant, answer: Callable[..., None]
) -> None:
    answer("/homes/", "homes_locked")
    result = await _start(hass)

    result = await _submit(hass, result["flow_id"], USER_INPUT)

    assert result["errors"] == {"base": "home_locked"}
    strings = json.loads(STRINGS.read_text())
    message = strings["config"]["error"]["home_locked"]
    assert "Continue with" in message
    assert "cannot open" not in message


@pytest.mark.usefixtures("no_token_in_logs")
@pytest.mark.parametrize("name", ["occurrences_locked", "sso_provider_changed"])
async def test_reauth_after_sso_required_says_why_and_takes_a_token_made_through_it(
    hass: HomeAssistant,
    answer: Callable[..., None],
    aioclient_mock: AiohttpClientMocker,
    setup_entry: Callable[[], Any],
    name: str,
) -> None:
    answer(f"/homes/{HOME_ID}/occurrences/", name)
    entry = await setup_entry()
    flow = hass.config_entries.flow.async_progress()[0]
    assert flow["step_id"] == "reauth_sso"
    form = await hass.config_entries.flow.async_configure(flow["flow_id"])
    assert form["description_placeholders"]["home"] == "Main house"

    # A token still made outside a session of the provider: refused, and said why.
    aioclient_mock.clear_requests()
    answer(f"/homes/{HOME_ID}/", "sso_required_home")
    result = await _submit(hass, flow["flow_id"], {CONF_API_TOKEN: NEW_TOKEN})
    assert result["step_id"] == "reauth_sso"
    assert result["errors"] == {"base": "home_locked"}

    # A token created while signed in through the provider: saved.
    aioclient_mock.clear_requests()
    aioclient_mock.get(f"{API}/homes/{HOME_ID}/", json=_through_the_provider("sso_token_home"))
    answer(PROBE, "write_probe_not_found", method="post")
    result = await _submit(hass, flow["flow_id"], {CONF_API_TOKEN: NEW_TOKEN})

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reauth_successful"
    assert entry.data[CONF_API_TOKEN] == NEW_TOKEN


async def test_the_dialog_after_sso_required_explains_the_token_to_create() -> None:
    for path in (STRINGS, STRINGS.parent / "translations" / "fr.json"):
        step = json.loads(path.read_text())["config"]["step"]["reauth_sso"]
        assert "{home}" in step["description"]
    english = json.loads(STRINGS.read_text())["config"]["step"]["reauth_sso"]["description"]
    assert "Continue with" in english
    assert "changed the provider" in english


# ---------- the Housecairn app of Home Assistant, found by discovery ----------

# The app's host name on the Supervisor's network: its slug with `-` for `_`.
APP_HOST = "0f1e2d3c-housecairn"
APP_URL = f"http://{APP_HOST}:8000"
APP_API = f"{APP_URL}/api/v1"
# What the app announces, and what the Supervisor adds (`addon`, the name of the app).
ANNOUNCED = {"host": APP_HOST, "port": 8000, "addon": "Housecairn"}


def _discovery(config: dict[str, Any] | None = None) -> HassioServiceInfo:
    return HassioServiceInfo(
        config=ANNOUNCED if config is None else config,
        name="Housecairn",
        slug="0f1e2d3c_housecairn",
        uuid="5f0c1e1e6b1d4a8e9f3a2b7c6d5e4f30",
    )


async def _discover(hass: HomeAssistant, config: dict[str, Any] | None = None) -> dict[str, Any]:
    result: dict[str, Any] = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_HASSIO}, data=_discovery(config)
    )
    return result


def _app_answers(aioclient_mock: AiohttpClientMocker, homes: str = "homes") -> None:
    """The app answers at its internal address as Housecairn does anywhere."""
    aioclient_mock.get(f"{APP_API}/homes/", status=load(homes)["status"], json=load(homes)["body"])
    aioclient_mock.post(f"{APP_API}{PROBE}", status=404, json=load("write_probe_not_found")["body"])


async def test_the_discovered_app_asks_for_the_token_only(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    _app_answers(aioclient_mock)

    result = await _discover(hass)

    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "hassio_confirm"
    assert list(result["data_schema"].schema) == [CONF_API_TOKEN]
    assert result["description_placeholders"] == {"addon": "Housecairn"}
    flow = hass.config_entries.flow.async_get(result["flow_id"])
    assert flow["context"]["title_placeholders"] == {"name": "Housecairn"}

    result = await _submit(hass, result["flow_id"], {CONF_API_TOKEN: TOKEN})

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Main house"
    assert result["data"] == {
        CONF_URL: APP_URL,
        CONF_VERIFY_SSL: True,
        CONF_API_TOKEN: TOKEN,
        CONF_HOME_ID: HOME_ID,
    }
    assert result["result"].unique_id == HOME_ID
    assert result["result"].source == SOURCE_HASSIO
    # Plain HTTP to the internal host name, the token in the header only.
    method, url, _data, headers = aioclient_mock.mock_calls[0]
    assert (method, url.scheme, url.host, url.port, url.path) == (
        "GET",
        "http",
        APP_HOST,
        8000,
        "/api/v1/homes/",
    )
    assert headers["Authorization"] == f"Bearer {TOKEN}"


@pytest.mark.parametrize("port", [8000, "8000"])
async def test_the_address_is_built_from_host_and_port(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker, port: Any
) -> None:
    _app_answers(aioclient_mock)
    result = await _discover(hass, {**ANNOUNCED, "port": port})

    result = await _submit(hass, result["flow_id"], {CONF_API_TOKEN: TOKEN})

    assert result["data"][CONF_URL] == APP_URL


@pytest.mark.parametrize(
    "config",
    [
        {},
        {"port": 8000},
        {"host": APP_HOST},
        {"host": "", "port": 8000},
        {"host": APP_HOST, "port": 0},
        {"host": APP_HOST, "port": 70000},
        {"host": APP_HOST, "port": True},
        {"host": APP_HOST, "port": "web"},
        {"host": f"{APP_HOST}/path", "port": 8000},
        {"host": "user@example.com", "port": 8000},
        {"host": f"{APP_HOST}:9000", "port": 8000},
    ],
)
async def test_an_announcement_without_an_address_is_ignored(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker, config: dict[str, Any]
) -> None:
    result = await _discover(hass, config)

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "invalid_discovery_info"
    assert aioclient_mock.call_count == 0


@pytest.mark.usefixtures("no_token_in_logs")
async def test_the_discovered_app_refuses_an_invalid_token_then_takes_a_good_one(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    _app_answers(aioclient_mock, "homes_invalid_token")
    result = await _discover(hass)

    result = await _submit(hass, result["flow_id"], {CONF_API_TOKEN: TOKEN})

    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "hassio_confirm"
    assert result["errors"] == {"base": "invalid_auth"}

    aioclient_mock.clear_requests()
    _app_answers(aioclient_mock)
    result = await _submit(hass, result["flow_id"], {CONF_API_TOKEN: NEW_TOKEN})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"][CONF_API_TOKEN] == NEW_TOKEN


async def test_the_discovered_app_with_a_read_only_token_says_so(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    aioclient_mock.get(f"{APP_API}/homes/", json=load("homes")["body"])
    forbidden = load("write_probe_forbidden")
    aioclient_mock.post(f"{APP_API}{PROBE}", status=forbidden["status"], json=forbidden["body"])
    result = await _discover(hass)

    result = await _submit(hass, result["flow_id"], {CONF_API_TOKEN: TOKEN})

    assert result["step_id"] == "read_only"
    result = await _submit(hass, result["flow_id"], {})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"][CONF_URL] == APP_URL


async def test_the_discovered_app_with_a_token_of_several_homes_asks_which(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    aioclient_mock.get(f"{APP_API}/homes/", json=_two_homes())
    aioclient_mock.post(
        f"{APP_API}{PROBE.replace(HOME_ID, OTHER_HOME)}",
        status=404,
        json=load("write_probe_not_found")["body"],
    )
    result = await _discover(hass)

    result = await _submit(hass, result["flow_id"], {CONF_API_TOKEN: TOKEN})
    assert result["step_id"] == "home"
    result = await _submit(hass, result["flow_id"], {CONF_HOME_ID: OTHER_HOME})

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["result"].unique_id == OTHER_HOME


async def test_an_entry_made_by_hand_for_the_same_address_is_not_offered_again(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id=HOME_ID,
        data={CONF_URL: APP_URL, CONF_API_TOKEN: TOKEN, CONF_VERIFY_SSL: True},
    )
    entry.add_to_hass(hass)

    result = await _discover(hass)

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"
    assert aioclient_mock.call_count == 0


async def test_a_second_announcement_joins_the_flow_in_progress(hass: HomeAssistant) -> None:
    first = await _discover(hass)
    assert first["step_id"] == "hassio_confirm"

    second = await _discover(hass)

    assert second["type"] is FlowResultType.ABORT
    assert second["reason"] == "already_in_progress"
    assert len(hass.config_entries.flow.async_progress_by_handler(DOMAIN)) == 1


async def test_an_ignored_announcement_stays_ignored(hass: HomeAssistant) -> None:
    MockConfigEntry(domain=DOMAIN, unique_id=APP_URL, source=SOURCE_IGNORE).add_to_hass(hass)

    result = await _discover(hass)

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"


async def test_an_entry_made_by_hand_at_another_address_is_left_alone(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker, mock_entry: MockConfigEntry
) -> None:
    """The same home, reached by hand at its public address: the app is offered, but
    adding the home again is refused and the entry keeps its address and token."""
    mock_entry.add_to_hass(hass)
    before = dict(mock_entry.data)
    _app_answers(aioclient_mock)

    result = await _discover(hass)
    assert result["step_id"] == "hassio_confirm"
    result = await _submit(hass, result["flow_id"], {CONF_API_TOKEN: NEW_TOKEN})

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"
    assert dict(mock_entry.data) == before
    assert mock_entry.data[CONF_URL] == URL


@pytest.mark.parametrize("state", [ConfigEntryState.LOADED, ConfigEntryState.NOT_LOADED])
async def test_an_entry_made_by_discovery_follows_the_app_to_its_new_address(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker, state: ConfigEntryState
) -> None:
    old = "http://0a0b0c0d-housecairn:8000"
    by_hand = MockConfigEntry(
        domain=DOMAIN,
        unique_id=OTHER_HOME,
        data={CONF_URL: URL, CONF_API_TOKEN: TOKEN, CONF_VERIFY_SSL: True},
    )
    by_hand.add_to_hass(hass)
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id=HOME_ID,
        source=SOURCE_HASSIO,
        state=state,
        data={CONF_URL: old, CONF_API_TOKEN: TOKEN, CONF_VERIFY_SSL: True, CONF_HOME_ID: HOME_ID},
    )
    entry.add_to_hass(hass)
    reload = Mock()
    hass.config_entries.async_schedule_reload = reload  # type: ignore[method-assign]

    result = await _discover(hass)

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"
    assert entry.data[CONF_URL] == APP_URL
    assert entry.data[CONF_API_TOKEN] == TOKEN
    assert by_hand.data[CONF_URL] == URL
    if state is ConfigEntryState.LOADED:
        reload.assert_called_once_with(entry.entry_id)
    else:
        reload.assert_not_called()
    assert aioclient_mock.call_count == 0


async def test_an_entry_made_by_discovery_at_the_same_address_is_not_reloaded(
    hass: HomeAssistant,
) -> None:
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id=HOME_ID,
        source=SOURCE_HASSIO,
        state=ConfigEntryState.LOADED,
        data={CONF_URL: APP_URL, CONF_API_TOKEN: TOKEN, CONF_VERIFY_SSL: True},
    )
    entry.add_to_hass(hass)
    reload = Mock()
    hass.config_entries.async_schedule_reload = reload  # type: ignore[method-assign]

    result = await _discover(hass)

    assert result["reason"] == "already_configured"
    reload.assert_not_called()


async def test_the_texts_of_the_discovered_app() -> None:
    for path, app in (
        (STRINGS, "Home Assistant app"),
        (STRINGS.parent / "translations" / "fr.json", "app Home Assistant"),
    ):
        config = json.loads(path.read_text())["config"]
        assert config["flow_title"] == f"{{name}} ({app})"
        step = config["step"]["hassio_confirm"]
        assert step["title"] == f"{{addon}} ({app})"
        assert list(step["data"]) == [CONF_API_TOKEN]
        assert "invalid_discovery_info" in config["abort"]
    english = json.loads(STRINGS.read_text())["config"]["step"]["user"]["description"]
    assert "found on its own" in english
