"""The blueprints: an automation made from each one calls housecairn.report."""

from __future__ import annotations

import pathlib
import shutil
from datetime import timedelta
from typing import Any

import pytest
import yaml
from homeassistant.components.automation import DOMAIN as AUTOMATION
from homeassistant.components.blueprint import BLUEPRINT_SCHEMA, models
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.setup import async_setup_component
from homeassistant.util import dt as dt_util
from homeassistant.util.yaml import load_yaml_dict
from pytest_homeassistant_custom_component.common import (
    async_fire_time_changed,
    async_mock_service,
)

from custom_components.housecairn.const import DOMAIN
from custom_components.housecairn.services import REPORT_SCHEMA

ROOT = pathlib.Path(__file__).parent.parent
BLUEPRINTS = ROOT / "blueprints" / "automation" / "housecairn"
NAMES = ("report_on_state", "report_below_threshold")
ENTRY = "0123456789abcdef0123456789abcdef"
ROOM = "978c6a38-de2c-4c8e-8eff-ee38d0536a82"
ITEM = "4f51cf6f-8837-452c-b04e-3f81344cd9df"
ARTICLE = "2a9c0edf-e533-4d21-b185-0913b8654f08"
WATCHED = "sensor.hallway_smoke_detector_battery"
LEAK = "binary_sensor.kitchen_leak"
FIVE_MINUTES = {"hours": 0, "minutes": 5, "seconds": 0}


def test_every_blueprint_file_is_covered() -> None:
    """A blueprint added without a test fails here."""
    assert sorted(p.stem for p in BLUEPRINTS.glob("*.yaml")) == sorted(NAMES)


class _Loader(yaml.SafeLoader):
    """Reads the `!input` tag of blueprints as a plain string."""


_Loader.add_constructor("!input", lambda loader, node: f"!input {loader.construct_scalar(node)}")


@pytest.mark.parametrize("name", NAMES)
def test_blueprint_declares_what_hacs_and_the_action_need(name: str) -> None:
    """Domain, minimum version (as hacs.json), inputs used, no token, mode queued."""
    text = (BLUEPRINTS / f"{name}.yaml").read_text()
    data = yaml.load(text, Loader=_Loader)  # noqa: S506  (SafeLoader subclass)
    blueprint = data["blueprint"]
    hacs = yaml.safe_load((ROOT / "hacs.json").read_text())
    assert blueprint["domain"] == "automation"
    assert blueprint["homeassistant"]["min_version"] == hacs["homeassistant"]
    assert blueprint["source_url"].endswith(f"/blueprints/automation/housecairn/{name}.yaml")
    assert data["mode"] == "queued"
    assert blueprint["input"]["config_entry"]["selector"] == {
        "config_entry": {"integration": DOMAIN}
    }
    used = {v.removeprefix("!input ") for v in _strings(data) if v.startswith("!input ")}
    assert used <= set(blueprint["input"])
    # Nothing but the Housecairn action is called: no token, no address.
    assert [a["action"] for a in data["actions"]] == ["housecairn.report"]
    assert "http" not in "".join(_strings(data["actions"])).lower()
    assert "token" not in "".join(_strings(data["actions"])).lower()


def _strings(node: Any) -> list[str]:
    if isinstance(node, str):
        return [node]
    if isinstance(node, dict):
        return [s for v in node.values() for s in _strings(v)]
    if isinstance(node, list):
        return [s for v in node for s in _strings(v)]
    return []


@pytest.fixture
def calls(hass: HomeAssistant) -> list[ServiceCall]:
    """housecairn.report, simulated, with the schema of the real action."""
    return async_mock_service(hass, DOMAIN, "report", schema=REPORT_SCHEMA)


def _install(hass: HomeAssistant) -> None:
    target = pathlib.Path(hass.config.path("blueprints", "automation", "housecairn"))
    target.mkdir(parents=True, exist_ok=True)
    for path in BLUEPRINTS.glob("*.yaml"):
        shutil.copy(path, target / path.name)


async def _automation(hass: HomeAssistant, name: str, inputs: dict[str, Any]) -> None:
    await hass.async_add_executor_job(_install, hass)
    assert await async_setup_component(
        hass,
        AUTOMATION,
        {
            AUTOMATION: {
                "use_blueprint": {"path": f"housecairn/{name}.yaml", "input": inputs},
            }
        },
    )
    await hass.async_block_till_done()
    assert len(hass.states.async_entity_ids(AUTOMATION)) == 1


async def _wait(hass: HomeAssistant, delta: timedelta) -> None:
    async_fire_time_changed(hass, dt_util.utcnow() + delta)
    await hass.async_block_till_done()


STATE_INPUTS = {
    "entities": [LEAK, "binary_sensor.cellar_leak"],
    "state": "wet",
    "duration": FIVE_MINUTES,
    "config_entry": ENTRY,
}
BELOW_INPUTS = {
    "entities": [WATCHED, "sensor.cellar_battery"],
    "threshold": 20,
    "duration": FIVE_MINUTES,
    "config_entry": ENTRY,
}


@pytest.mark.parametrize(
    ("name", "inputs"),
    [("report_on_state", STATE_INPUTS), ("report_below_threshold", BELOW_INPUTS)],
)
async def test_blueprint_loads_and_validates(
    hass: HomeAssistant, name: str, inputs: dict[str, Any]
) -> None:
    blueprint = models.Blueprint(
        await hass.async_add_executor_job(_load, BLUEPRINTS / f"{name}.yaml"),
        expected_domain=AUTOMATION,
        schema=BLUEPRINT_SCHEMA,
    )
    assert blueprint.domain == AUTOMATION
    assert set(inputs) <= set(blueprint.inputs)
    # What the user did not fill in has a default.
    assert {k for k in blueprint.inputs if k not in inputs} <= {
        "report_title",
        "room",
        "item",
        "article",
        "state",
    }
    assert blueprint.validate() is None


def _load(path: pathlib.Path) -> Any:
    return load_yaml_dict(str(path))


async def test_state_reports_after_the_duration(
    hass: HomeAssistant, calls: list[ServiceCall]
) -> None:
    hass.states.async_set(LEAK, "dry", {"friendly_name": "Kitchen leak"})
    await _automation(
        hass,
        "report_on_state",
        {**STATE_INPUTS, "room": ROOM, "report_title": "Leak: {{ trigger.to_state.name }}"},
    )

    hass.states.async_set(LEAK, "wet", {"friendly_name": "Kitchen leak"})
    await hass.async_block_till_done()
    await _wait(hass, timedelta(minutes=4))
    assert calls == []

    await _wait(hass, timedelta(minutes=6))
    assert len(calls) == 1
    # Only the place that was given is sent, and the title names the entity.
    assert calls[0].data == {
        "config_entry_id": ENTRY,
        "title": "Leak: Kitchen leak",
        "room": ROOM,
    }


async def test_state_default_title_and_state(hass: HomeAssistant, calls: list[ServiceCall]) -> None:
    """The defaults: the state `on`, a title with the entity name, no place."""
    inputs = {
        "entities": [LEAK],
        "config_entry": ENTRY,
    }
    hass.states.async_set(LEAK, "off", {"friendly_name": "Kitchen leak"})
    await _automation(hass, "report_on_state", inputs)
    hass.states.async_set(LEAK, "on", {"friendly_name": "Kitchen leak"})
    await hass.async_block_till_done()
    await _wait(hass, timedelta(minutes=6))
    assert [c.data for c in calls] == [{"config_entry_id": ENTRY, "title": "Problem: Kitchen leak"}]


async def test_state_does_not_report_when_it_stops_before_the_duration(
    hass: HomeAssistant, calls: list[ServiceCall]
) -> None:
    hass.states.async_set(LEAK, "dry", {"friendly_name": "Kitchen leak"})
    await _automation(hass, "report_on_state", STATE_INPUTS)

    hass.states.async_set(LEAK, "wet", {"friendly_name": "Kitchen leak"})
    await hass.async_block_till_done()
    await _wait(hass, timedelta(minutes=3))
    hass.states.async_set(LEAK, "dry", {"friendly_name": "Kitchen leak"})
    await hass.async_block_till_done()
    await _wait(hass, timedelta(minutes=10))
    assert calls == []


async def test_state_ignores_another_state(hass: HomeAssistant, calls: list[ServiceCall]) -> None:
    hass.states.async_set(LEAK, "dry", {"friendly_name": "Kitchen leak"})
    await _automation(hass, "report_on_state", STATE_INPUTS)
    hass.states.async_set(LEAK, "on", {"friendly_name": "Kitchen leak"})
    await hass.async_block_till_done()
    await _wait(hass, timedelta(minutes=10))
    assert calls == []


async def test_threshold_reports_after_the_duration(
    hass: HomeAssistant, calls: list[ServiceCall]
) -> None:
    hass.states.async_set(WATCHED, "80", {"friendly_name": "Hallway smoke detector battery"})
    await _automation(hass, "report_below_threshold", {**BELOW_INPUTS, "item": ITEM})

    hass.states.async_set(WATCHED, "15", {"friendly_name": "Hallway smoke detector battery"})
    await hass.async_block_till_done()
    await _wait(hass, timedelta(minutes=4))
    assert calls == []

    await _wait(hass, timedelta(minutes=6))
    assert len(calls) == 1
    assert calls[0].data == {
        "config_entry_id": ENTRY,
        "title": "Battery low: Hallway smoke detector battery",
        "item": ITEM,
    }


async def test_threshold_article_and_custom_threshold(
    hass: HomeAssistant, calls: list[ServiceCall]
) -> None:
    """A stock item as the place, and a threshold other than the default."""
    hass.states.async_set(WATCHED, "80", {"friendly_name": "Tank"})
    await _automation(
        hass,
        "report_below_threshold",
        {**BELOW_INPUTS, "threshold": 50, "article": ARTICLE, "report_title": "Tank low"},
    )
    hass.states.async_set(WATCHED, "40", {"friendly_name": "Tank"})
    await hass.async_block_till_done()
    await _wait(hass, timedelta(minutes=6))
    assert [c.data for c in calls] == [
        {"config_entry_id": ENTRY, "title": "Tank low", "article": ARTICLE}
    ]


async def test_threshold_does_not_report_when_the_value_recovers(
    hass: HomeAssistant, calls: list[ServiceCall]
) -> None:
    hass.states.async_set(WATCHED, "80", {"friendly_name": "Battery"})
    await _automation(hass, "report_below_threshold", BELOW_INPUTS)

    hass.states.async_set(WATCHED, "15", {"friendly_name": "Battery"})
    await hass.async_block_till_done()
    await _wait(hass, timedelta(minutes=3))
    hass.states.async_set(WATCHED, "60", {"friendly_name": "Battery"})
    await hass.async_block_till_done()
    await _wait(hass, timedelta(minutes=10))
    assert calls == []


async def test_threshold_does_not_report_a_value_above_it(
    hass: HomeAssistant, calls: list[ServiceCall]
) -> None:
    """A value at the threshold or above is no problem (the comparison is strict)."""
    hass.states.async_set(WATCHED, "80", {"friendly_name": "Battery"})
    await _automation(hass, "report_below_threshold", BELOW_INPUTS)
    hass.states.async_set(WATCHED, "20", {"friendly_name": "Battery"})
    await hass.async_block_till_done()
    await _wait(hass, timedelta(minutes=10))
    assert calls == []
