"""The two blueprints: loaded and validated by Home Assistant, then run as automations."""

from __future__ import annotations

import datetime
import json
import pathlib
import shutil
from typing import Any

import pytest
from homeassistant.components.automation.helpers import async_get_blueprints
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.setup import async_setup_component
from pytest_homeassistant_custom_component.common import (
    async_fire_time_changed,
    async_mock_service,
)

from custom_components.housecairn.const import DOMAIN
from custom_components.housecairn.services import REPORT_SCHEMA

ROOT = pathlib.Path(__file__).parent.parent
BLUEPRINTS = ROOT / "blueprints" / "automation" / "housecairn"
ON_STATE = "housecairn/report_on_state.yaml"
BELOW = "housecairn/report_below_threshold.yaml"
ENTRY_ID = "0123456789abcdef0123456789abcdef"
LEAK = "binary_sensor.boiler_fault"
BATTERY = "sensor.smoke_detector_battery"


@pytest.fixture
def blueprint_dir(hass: HomeAssistant, tmp_path: pathlib.Path) -> None:
    """The blueprints of the repository, where Home Assistant looks for them."""
    shutil.copytree(BLUEPRINTS, tmp_path / "blueprints" / "automation" / "housecairn")
    hass.config.config_dir = str(tmp_path)


@pytest.fixture
def calls(hass: HomeAssistant) -> list[ServiceCall]:
    """housecairn.report, validated with the schema of the real action."""
    return async_mock_service(hass, DOMAIN, "report", schema=REPORT_SCHEMA)


async def _automation(hass: HomeAssistant, path: str, **inputs: Any) -> None:
    config = {
        "automation": [
            {
                "id": "housecairn_test",
                "alias": "Housecairn test",
                "use_blueprint": {"path": path, "input": {"home": ENTRY_ID, **inputs}},
            }
        ]
    }
    assert await async_setup_component(hass, "automation", config)
    await hass.async_block_till_done()
    assert hass.states.get("automation.housecairn_test").state == "on"  # type: ignore[union-attr]


async def _later(hass: HomeAssistant, freezer: Any, minutes: float) -> None:
    freezer.tick(datetime.timedelta(minutes=minutes))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()


@pytest.mark.usefixtures("blueprint_dir")
@pytest.mark.parametrize("path", [ON_STATE, BELOW])
async def test_each_blueprint_loads_and_is_valid(hass: HomeAssistant, path: str) -> None:
    blueprint = await async_get_blueprints(hass).async_get_blueprint(path)

    hacs = json.loads((ROOT / "hacs.json").read_text())
    assert blueprint.domain == "automation"
    assert blueprint.metadata["homeassistant"]["min_version"] == hacs["homeassistant"]
    assert blueprint.metadata["source_url"].endswith(f"/blob/main/blueprints/automation/{path}")
    inputs = blueprint.inputs
    assert inputs["home"]["selector"] == {"config_entry": {"integration": DOMAIN}}
    assert inputs["create_item"]["default"] is True
    assert inputs["area"]["default"] == ""
    assert inputs["duration"]["default"] == {"hours": 0, "minutes": 5, "seconds": 0}
    assert blueprint.data["mode"] == "queued"


@pytest.mark.usefixtures("blueprint_dir")
async def test_a_state_held_for_the_duration_reports_once(
    hass: HomeAssistant, calls: list[ServiceCall], freezer: Any
) -> None:
    hass.states.async_set(LEAK, "off", {"friendly_name": "Boiler fault"})
    await _automation(hass, ON_STATE, entities=[LEAK])

    hass.states.async_set(LEAK, "on", {"friendly_name": "Boiler fault"})
    await hass.async_block_till_done()
    await _later(hass, freezer, 4)
    assert calls == []

    await _later(hass, freezer, 2)
    await _later(hass, freezer, 30)

    assert [call.data for call in calls] == [
        {
            "config_entry_id": ENTRY_ID,
            "title": "Problem detected: Boiler fault",
            "entity_id": LEAK,
            "area_id": None,
            "create_item": True,
        }
    ]


@pytest.mark.usefixtures("blueprint_dir")
async def test_a_state_that_ends_before_the_duration_reports_nothing(
    hass: HomeAssistant, calls: list[ServiceCall], freezer: Any
) -> None:
    hass.states.async_set(LEAK, "off")
    await _automation(hass, ON_STATE, entities=[LEAK])

    hass.states.async_set(LEAK, "on")
    await hass.async_block_till_done()
    await _later(hass, freezer, 3)
    hass.states.async_set(LEAK, "off")
    await hass.async_block_till_done()
    await _later(hass, freezer, 30)

    assert calls == []


@pytest.mark.usefixtures("blueprint_dir")
async def test_the_inputs_given_reach_the_action(
    hass: HomeAssistant, calls: list[ServiceCall], freezer: Any
) -> None:
    hass.states.async_set(LEAK, "ok")
    await _automation(
        hass,
        ON_STATE,
        entities=[LEAK],
        state="problem",
        duration={"hours": 0, "minutes": 1, "seconds": 0},
        title="Boiler: {{ trigger.to_state.state }}",
        area="kitchen",
        create_item=False,
    )

    hass.states.async_set(LEAK, "problem")
    await hass.async_block_till_done()
    await _later(hass, freezer, 2)

    assert [call.data for call in calls] == [
        {
            "config_entry_id": ENTRY_ID,
            "title": "Boiler: problem",
            "entity_id": LEAK,
            "area_id": "kitchen",
            "create_item": False,
        }
    ]


@pytest.mark.usefixtures("blueprint_dir")
async def test_a_value_below_the_threshold_for_the_duration_reports_once(
    hass: HomeAssistant, calls: list[ServiceCall], freezer: Any
) -> None:
    hass.states.async_set(BATTERY, "80", {"friendly_name": "Smoke detector battery"})
    await _automation(hass, BELOW, entities=[BATTERY])

    hass.states.async_set(BATTERY, "15", {"friendly_name": "Smoke detector battery"})
    await hass.async_block_till_done()
    await _later(hass, freezer, 4)
    assert calls == []

    await _later(hass, freezer, 2)
    await _later(hass, freezer, 30)

    assert [call.data for call in calls] == [
        {
            "config_entry_id": ENTRY_ID,
            "title": "Low: Smoke detector battery",
            "entity_id": BATTERY,
            "area_id": None,
            "create_item": True,
        }
    ]


@pytest.mark.usefixtures("blueprint_dir")
@pytest.mark.parametrize(
    "values",
    [
        # Above the threshold of 20: no problem, however long.
        ["80", "35"],
        # Below, then back above before five minutes.
        ["80", "15", "60"],
    ],
)
async def test_a_value_above_or_back_up_in_time_reports_nothing(
    hass: HomeAssistant, calls: list[ServiceCall], freezer: Any, values: list[str]
) -> None:
    hass.states.async_set(BATTERY, values[0])
    await _automation(hass, BELOW, entities=[BATTERY])

    for value in values[1:]:
        hass.states.async_set(BATTERY, value)
        await hass.async_block_till_done()
        await _later(hass, freezer, 3)
    await _later(hass, freezer, 30)

    assert calls == []
