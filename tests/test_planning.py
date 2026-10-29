"""Plans, progress, the planner and the app's status: entities only for what the mower and the app have."""

from __future__ import annotations

import copy
from datetime import timedelta
import json
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry, async_fire_time_changed
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker
from pytest_homeassistant_custom_component.typing import WebSocketGenerator

from homeassistant.const import ATTR_ENTITY_ID
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.util import dt as dt_util

from custom_components.mowbite.app import (
    SKIP_REASONS,
    parse_battery,
    parse_battery_level,
    parse_schedule,
    parse_schedule_log,
    parse_system,
)
from custom_components.mowbite.const import CONF_APP_URL
from custom_components.mowbite.mower import Mower, RpcError
from custom_components.mowbite.planning import lawn_area, plan_progress, trim_plan
from custom_components.mowbite.websocket import planner_sizes

from .conftest import ACTIONS, ROBOT_STATE, app_status, send

TRANSLATIONS = Path(__file__).parent.parent / "custom_components" / "mowbite" / "translations"


def square(x: float, y: float, size: float) -> list[dict[str, float]]:
    return [{"x": x, "y": y}, {"x": x + size, "y": y}, {"x": x + size, "y": y + size}, {"x": x, "y": y + size}]


MAP = {
    "areas": [
        {"id": "front", "properties": {"name": "Front", "type": "mow"}, "outline": square(0, 0, 10)},
        {"id": "path", "properties": {"name": "Path", "type": "mow", "active": False}, "outline": square(20, 0, 2)},
        {"id": "back", "properties": {"name": "Back", "type": "mow"}, "outline": square(0, 20, 5)},
        {"id": "tree", "properties": {"name": "Tree", "type": "obstacle"}, "outline": square(1, 1, 1)},
    ],
    "docking_stations": [],
}


def plan(area_id: str, minutes: float | None = None, area: float | None = None) -> dict[str, Any]:
    """Two paths, an outline of 100 poses and lanes of 300, points every 10 poses."""
    result: dict[str, Any] = {
        "area_id": area_id,
        "angle": 0.0,
        "paths": [
            {
                "is_outline": True,
                "points": [[i, 0] for i in range(10)],
                "pose_index": [i * 10 for i in range(9)] + [99],
            },
            {
                "is_outline": False,
                "points": [[i, 1] for i in range(30)],
                "pose_index": [i * 10 for i in range(29)] + [299],
            },
        ],
    }
    if minutes is not None:
        result["duration"] = {"min": minutes, "model_min": minutes, "factor": 1.0, "runs": 0}
        result["stats"] = {"area": area}
        result["warnings"] = ["one place left out"]
        result["fingerprint"] = "abc"
    return result


SETTINGS = {
    "settings": {
        "fill_pattern": {
            "value": "lanes",
            "type": "string",
            "settable": True,
            "choices": ["lanes", "crosshatch", "concentric"],
        },
        "perimeter_passes": {"value": 2, "type": "integer", "settable": True},
        "overlap": {"value": 0.15, "type": "number", "settable": True},
        "leftovers_auto": {"value": True, "type": "boolean", "settable": True},
        "robot_width": {"value": 0.41, "type": "number", "settable": True},
        "robot_front": {"value": 0.43, "type": "number", "settable": True},
        "robot_rear": {"value": 0.18, "type": "number", "settable": True},
        "mower_width": {"value": 0.18, "type": "number", "settable": True},
        "blade_ahead": {"value": 0.185, "type": "number", "settable": True},
        "blade_offset": {"value": 0.0, "type": "number", "settable": True},
    }
}


class FakeRpc:
    """The mower's rpc: what it answers per method, and what it was asked."""

    def __init__(self, answers: dict[str, Any]) -> None:
        self.answers = answers
        self.calls: list[tuple[str, Any]] = []

    async def __call__(self, method: str, params: Any = None, timeout: float = 20) -> Any:
        self.calls.append((method, params))
        if method not in self.answers:
            raise RpcError("Method not found")
        answer = self.answers[method]
        return answer(params) if callable(answer) else copy.deepcopy(answer)


PLANNER_ANSWERS = {
    "rpc.methods": [
        "events.history",
        "mowing.plan",
        "planner.angle.reset",
        "planner.drive",
        "planner.leftovers",
        "planner.plan",
        "planner.settings",
        "planner.settings.set",
        "rpc.methods",
    ],
    "planner.settings": SETTINGS,
    "planner.plan": lambda params: plan(
        params["area_id"], 40 if params["area_id"] == "front" else 20, 90 if params["area_id"] == "front" else 25
    ),
    "planner.leftovers": {
        "file": "1.jsonl",
        "armed": 0,
        "areas": {
            "front": {"area_id": "front", "left_m2": 1.25, "paths": [{"points": [[1, 1], [2, 2]]}], "message": ""},
            "back": {"area_id": "back", "left_m2": 0.5, "paths": [[[3, 3], [4, 4]]], "message": ""},
        },
    },
    "planner.drive": {"file": "1.jsonl", "areas": {"front": {"checked": 10, "places": [[1, 2, 0.03]], "worst": 0.03}}},
    "events.history": [],
}


def test_trim_and_progress() -> None:
    trimmed = trim_plan(plan("front", 40, 90))
    assert trimmed is not None
    assert [p["poses"] for p in trimmed["paths"]] == [100, 300]
    assert trimmed["minutes"] == 40 and trimmed["area"] == 90
    assert plan_progress(trimmed, 0, 0) == 0
    assert plan_progress(trimmed, 0, 50) == pytest.approx(50 / 400)
    assert plan_progress(trimmed, 1, 100) == pytest.approx(200 / 400)
    # not mowing, or a path the plan doesn't have
    assert plan_progress(trimmed, -1, -1) is None
    assert plan_progress(trimmed, 5, 0) is None
    # mowing.plan without the planner: no time, no area
    plain = trim_plan(plan("front"))
    assert plain is not None and plain["minutes"] is None
    assert trim_plan({"error": "x"}) is None


def test_lawn_area_from_the_map() -> None:
    # the active areas less the tree in the front one, the inactive path doesn't count
    assert lawn_area(MAP) == pytest.approx(100 + 25 - 1)
    assert lawn_area({"areas": []}) is None
    # a decoration is only a picture in MowBite, the mower mows under it (and a type it doesn't know changes nothing)
    decor = {"id": "bed", "properties": {"name": "Bed", "type": "decor"}, "outline": square(2, 2, 3)}
    assert lawn_area({"areas": [*MAP["areas"], decor]}) == pytest.approx(100 + 25 - 1)


def test_planner_sizes() -> None:
    assert planner_sizes(SETTINGS["settings"]) == {
        "width": 0.41,
        "front": 0.43,
        "rear": 0.18,
        "blade": 0.18,
        "bladeAhead": 0.185,
        "bladeOffset": 0.0,
    }
    assert planner_sizes({"robot_width": {"value": 0.4}}) is None
    assert planner_sizes(None) is None


def test_app_status_texts() -> None:
    system = parse_system(
        "remote 0\nmem_total 4000\nmem_available 1000\nload 0.85 0.54 0.55\nuptime 3600\ncpu_temp 66.7\n"
    )
    assert system["cpu_temp"] == 66.7 and system["uptime"] == 3600 and system["load"] == [0.85, 0.54, 0.55]
    schedule = parse_schedule("enabled 1\nskiprain 0\nplan 1,3,5 10:00\nplan 6 09:00 a,b\n")
    assert schedule["enabled"] is True and schedule["plans"] == 2
    log = parse_schedule_log("100 started 100\n200 skipped_area x\n300 skip_rain\n400 started 80\n")
    assert log == {"started": 400, "skipped": 300, "skip_reason": "rain"}
    # every reason the app's scheduler logs, each with its words in both languages
    for reason in ("cold", "end", "gone", "no_area"):
        assert parse_schedule_log(f"500 skip_{reason} 4\n")["skip_reason"] in SKIP_REASONS
    for lang in ("en", "de"):
        words = json.loads((TRANSLATIONS / f"{lang}.json").read_text(encoding="utf-8"))
        assert set(words["entity"]["sensor"]["schedule_skipped"]["state"]) == set(SKIP_REASONS)
    battery = parse_battery(
        "charge 1 2 12.1 29.09 27.78\nrun 2 3 70.0 27.78 26.0\nrun 3000000 3000100 60.8 27.78 26.71\n"
        "run 3000100 3000200 0.0 29.09 27.54\nrun 3000200 3000300 1.3 29.09 28.5\n",
        3000400,
    )
    # the longest of the last 30 days, the 70 minutes are older
    assert battery == {"blade_minutes": 60.8, "run_end": 3000100, "low_voltage": 26.71}


def test_parse_battery_level() -> None:
    assert parse_battery_level("1000 950 64 out\n") == 64
    assert parse_battery_level("1000 880 100 full") == 100
    # too old, none yet, a mower MowBite doesn't work it out for, not a whole percentage
    assert parse_battery_level("1000 870 64 out") is None
    assert parse_battery_level("1000 ") is None
    assert parse_battery_level("1000 950 - off") is None
    assert parse_battery_level("1000 950 64.5 out") is None
    assert parse_battery_level("") is None


async def setup_mower(hass: HomeAssistant, entry: MockConfigEntry, rpc: FakeRpc) -> Mower:
    with patch.object(Mower, "async_rpc", rpc):
        entry.add_to_hass(hass)
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
    mower: Mower = entry.runtime_data.mower
    mower.async_rpc = rpc  # type: ignore[method-assign]
    mower._connected = True
    send(mower, "actions/json", ACTIONS)
    send(mower, "robot_state/json", ROBOT_STATE)
    await hass.async_block_till_done()
    return mower


async def test_nothing_without_the_planner(hass: HomeAssistant, entry: MockConfigEntry, no_connection: None) -> None:
    """An OpenMower without the rpcs: none of the new entities, the map's area only once a map came."""
    mower = await setup_mower(hass, entry, FakeRpc({"rpc.methods": ["rpc.methods"]}))
    for entity_id in (
        "sensor.openmower_area_progress",
        "sensor.openmower_time_left",
        "sensor.openmower_left_uncut",
        "sensor.openmower_last_problem",
        "sensor.openmower_lawn_area",
        "select.openmower_fill_pattern",
        "switch.openmower_mow_leftovers_by_itself",
        "button.openmower_mow_leftovers",
        "button.openmower_skip_path",
        "button.openmower_drop_interrupted_job",
        "binary_sensor.openmower_schedule",
        "sensor.openmower_cpu_temperature",
    ):
        assert hass.states.get(entity_id) is None, entity_id

    send(mower, "map/json", MAP)
    send(mower, "events/json", {"type": "GPS", "t": 1, "id": "e1"})
    # an OpenMower that has skip_path and reset_job lists them, enabled or not
    send(mower, "actions/json", [*ACTIONS, {"action_id": "mower_logic:mowing/skip_path", "enabled": 0}])
    await hass.async_block_till_done()
    assert hass.states.get("sensor.openmower_lawn_area").state == "124.0"
    assert hass.states.get("sensor.openmower_last_problem") is not None
    assert hass.states.get("button.openmower_skip_path") is not None
    assert hass.states.get("button.openmower_drop_interrupted_job") is None
    assert hass.states.get("sensor.openmower_area_progress") is None


async def test_progress_without_the_planner(hass: HomeAssistant, entry: MockConfigEntry, no_connection: None) -> None:
    """mowing.plan alone: progress, but no time."""
    rpc = FakeRpc(
        {"rpc.methods": ["mowing.plan", "rpc.methods"], "mowing.plan": lambda params: plan(params["area_id"])}
    )
    mower = await setup_mower(hass, entry, rpc)
    send(mower, "map/json", MAP)
    await hass.async_block_till_done()
    assert hass.states.get("sensor.openmower_area_progress") is not None
    assert hass.states.get("sensor.openmower_area_time_left") is None

    send(
        mower,
        "events/json",
        {"type": "AREA", "area_id": "front", "area_name": "Front", "job_id": "j", "t": 2, "id": "a1"},
    )
    send(
        mower,
        "robot_state/json",
        {**ROBOT_STATE, "current_state": "MOWING", "current_path": 1, "current_path_index": 100},
    )
    await hass.async_block_till_done()
    assert hass.states.get("sensor.openmower_area_progress").state == "50"
    assert hass.states.get("sensor.openmower_current_area").state == "Front"


async def test_with_the_planner(hass: HomeAssistant, entry: MockConfigEntry, no_connection: None, freezer: Any) -> None:
    rpc = FakeRpc(PLANNER_ANSWERS)
    mower = await setup_mower(hass, entry, rpc)
    send(mower, "map/json", MAP)
    await hass.async_block_till_done()

    # every active area planned once while idle: a whole job's time and area by the planner
    asked = [params["area_id"] for method, params in rpc.calls if method == "planner.plan"]
    assert sorted(asked) == ["back", "front"]
    assert hass.states.get("sensor.openmower_duration_for_all_areas").state == "60"
    assert hass.states.get("sensor.openmower_lawn_area").state == "115.0"
    leftovers = hass.states.get("sensor.openmower_left_uncut")
    assert leftovers.state == "1.8"
    assert leftovers.attributes["areas"] == {"Front": 1.2, "Back": 0.5}
    assert hass.states.get("select.openmower_fill_pattern").state == "lanes"
    assert hass.states.get("switch.openmower_mow_leftovers_by_itself").state == "on"
    assert hass.states.get("number.openmower_outline_loops").state == "2"

    # mowing the front, half through: the rest of the front and all of the back to go
    send(
        mower,
        "events/json",
        {"type": "AREA", "area_id": "front", "area_name": "Front", "job_id": "j", "t": 2, "id": "a1"},
    )
    send(mower, "position/json", {"x": 1, "y": 1, "heading": 0, "attributes": {"job_id": "j", "blades": True}})
    send(
        mower,
        "robot_state/json",
        {**ROBOT_STATE, "current_state": "MOWING", "current_path": 1, "current_path_index": 100},
    )
    await hass.async_block_till_done()
    assert hass.states.get("sensor.openmower_area_progress").state == "50"
    assert hass.states.get("sensor.openmower_area_time_left").state == "20"
    assert hass.states.get("sensor.openmower_time_left").state == "40"

    # no settings while mowing: the planner would plan the area anew and start it over
    with pytest.raises(HomeAssistantError):
        await hass.services.async_call(
            "select",
            "select_option",
            {ATTR_ENTITY_ID: "select.openmower_fill_pattern", "option": "crosshatch"},
            blocking=True,
        )
    assert not any(method == "planner.settings.set" for method, _ in rpc.calls)

    # docked again: the leftovers asked once more after a while, not polled
    send(mower, "robot_state/json", ROBOT_STATE)
    rpc.calls.clear()
    send(mower, "events/json", {"type": "DOCKED", "t": 3, "id": "d1"})
    await hass.async_block_till_done()
    assert not any(method == "planner.leftovers" for method, _ in rpc.calls)
    freezer.tick(timedelta(seconds=31))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    assert any(method == "planner.leftovers" for method, _ in rpc.calls)


async def test_setting_changes_while_idle(hass: HomeAssistant, entry: MockConfigEntry, no_connection: None) -> None:
    answers = dict(PLANNER_ANSWERS)

    def set_setting(params: dict[str, Any]) -> dict[str, Any]:
        changed = copy.deepcopy(SETTINGS)
        for name, value in params.items():
            changed["settings"][name]["value"] = value
        return changed

    answers["planner.settings.set"] = set_setting
    rpc = FakeRpc(answers)
    mower = await setup_mower(hass, entry, rpc)
    send(mower, "map/json", MAP)
    await hass.async_block_till_done()
    rpc.calls.clear()
    await hass.services.async_call(
        "select",
        "select_option",
        {ATTR_ENTITY_ID: "select.openmower_fill_pattern", "option": "crosshatch"},
        blocking=True,
    )
    await hass.async_block_till_done()
    assert ("planner.settings.set", {"fill_pattern": "crosshatch"}) in rpc.calls
    assert hass.states.get("select.openmower_fill_pattern").state == "crosshatch"
    # the plans again, they change with the setting
    assert any(method == "planner.plan" for method, _ in rpc.calls)


async def test_mow_leftovers(hass: HomeAssistant, entry: MockConfigEntry, no_connection: None) -> None:
    rpc = FakeRpc({**PLANNER_ANSWERS, "planner.leftovers": lambda params: {**PLANNER_ANSWERS["planner.leftovers"]}})
    mower = await setup_mower(hass, entry, rpc)
    send(mower, "map/json", MAP)
    await hass.async_block_till_done()
    assert hass.states.get("button.openmower_mow_leftovers").state != "unavailable"
    with patch.object(mower, "async_action", AsyncMock()) as action:
        await hass.services.async_call(
            "button", "press", {ATTR_ENTITY_ID: "button.openmower_mow_leftovers"}, blocking=True
        )
    assert ("planner.leftovers", {"arm": True}) in rpc.calls
    action.assert_awaited_once_with("mower_logic:idle/start_mowing")


async def test_features_stay(hass: HomeAssistant, entry: MockConfigEntry, no_connection: None) -> None:
    """Seen once, the entities are there after a restart too, also while the mower is off."""
    mower = await setup_mower(hass, entry, FakeRpc(PLANNER_ANSWERS))
    send(mower, "map/json", MAP)
    await hass.async_block_till_done()
    assert hass.states.get("sensor.openmower_time_left") is not None
    await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert hass.states.get("sensor.openmower_time_left").state == "unavailable"


async def test_app_status(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker, entry: MockConfigEntry, no_connection: None
) -> None:
    url = "http://openmower:8082"
    aioclient_mock.get(url + "/cgi-bin/settings", json={})
    app_status(
        aioclient_mock,
        url,
        {
            "/version.json": '{"version": "1.4.0"}',
            "/cgi-bin/system": "mem_total 4000\nmem_available 1000\ndata_free 1668079616\nuptime 3600\ncpu_temp 66.7\n",
            "/cgi-bin/schedule": "enabled 1\nplan 1 10:00\n",
            # the newest one counts, cold with the temperature after it
            "/cgi-bin/schedule?log": f"{dt_util.utcnow().timestamp() - 120:.0f} skip_rain\n"
            f"{dt_util.utcnow().timestamp() - 60:.0f} skip_cold 4\n",
        },
    )
    entry.add_to_hass(hass)
    hass.config_entries.async_update_entry(entry, options={CONF_APP_URL: url})
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert hass.states.get("sensor.openmower_mowbite_version").state == "1.4.0"
    assert hass.states.get("sensor.openmower_cpu_temperature").state == "66.7"
    assert hass.states.get("sensor.openmower_free_storage").state == "1.7"
    assert hass.states.get("binary_sensor.openmower_schedule").state == "on"
    assert hass.states.get("sensor.openmower_last_skipped_start").state == "cold"
    # the battery's log didn't answer: no sensor for it
    assert hass.states.get("sensor.openmower_longest_blade_time_per_charge") is None
    # a container below level 4 isn't asked for MowBite's battery level
    assert not any(str(call[1]).endswith("battery?level") for call in aioclient_mock.mock_calls)


async def test_mowbites_battery_level(
    hass: HomeAssistant,
    hass_ws_client: WebSocketGenerator,
    aioclient_mock: AiohttpClientMocker,
    entry: MockConfigEntry,
    no_connection: None,
) -> None:
    """MowBite's own level while it has one, it stays put when the mower sets off where OpenMower's drops."""
    url = "http://openmower:8082"
    now = dt_util.utcnow().timestamp()
    aioclient_mock.get(url + "/cgi-bin/settings", json={})
    app_status(
        aioclient_mock,
        url,
        {
            "/version.json": '{"version": "1.5.0", "level": 4}',
            "/cgi-bin/battery?level": f"{now:.0f} {now - 30:.0f} 97 out\n",
        },
    )
    entry.add_to_hass(hass)
    hass.config_entries.async_update_entry(entry, options={CONF_APP_URL: url})
    mower = await setup_mower(hass, entry, FakeRpc({}))
    send(mower, "robot_state/json", {**ROBOT_STATE, "battery_percentage": 0.81})
    await hass.async_block_till_done()
    assert hass.states.get("sensor.openmower_battery").state == "97"
    client = await hass_ws_client(hass)
    await client.send_json_auto_id({"type": "mowbite/subscribe", "entity_id": "lawn_mower.openmower"})
    assert (await client.receive_json())["success"]
    assert (await client.receive_json())["event"]["battery_level"] == 97

    # without one OpenMower's percentage again
    status = entry.runtime_data.status
    status.battery_level = None
    send(mower, "robot_state/json", {**ROBOT_STATE, "battery_percentage": 0.80})
    await hass.async_block_till_done()
    assert hass.states.get("sensor.openmower_battery").state == "80"


async def test_slic3r_mode_asks_mowing_plan(hass: HomeAssistant, entry: MockConfigEntry, no_connection: None) -> None:
    """The planner handing planning on to slic3r: mowing.plan is mower_logic's plan, planner.plan only a copy."""
    settings = copy.deepcopy(SETTINGS)
    settings["settings"]["planner"] = {"value": "slic3r", "type": "string", "settable": True}
    rpc = FakeRpc(
        {
            **PLANNER_ANSWERS,
            "planner.settings": settings,
            "mowing.plan": lambda params: plan(params["area_id"]),
        }
    )
    mower = await setup_mower(hass, entry, rpc)
    send(mower, "map/json", MAP)
    await hass.async_block_till_done()
    asked = {method for method, _ in rpc.calls}
    assert "mowing.plan" in asked
    assert "planner.plan" not in asked
    send(
        mower,
        "events/json",
        {"type": "AREA", "area_id": "front", "area_name": "Front", "job_id": "j", "t": 2, "id": "a1"},
    )
    send(
        mower,
        "robot_state/json",
        {**ROBOT_STATE, "current_state": "MOWING", "current_path": 1, "current_path_index": 100},
    )
    await hass.async_block_till_done()
    assert hass.states.get("sensor.openmower_area_progress").state == "50"
    # no time from mowing.plan
    assert hass.states.get("sensor.openmower_area_time_left").state == "unknown"


async def test_mowbite_mode_never_asks_mowing_plan(
    hass: HomeAssistant, entry: MockConfigEntry, no_connection: None
) -> None:
    """The planner planning itself: mowing.plan would count as mower_logic fetching its plan."""
    rpc = FakeRpc({**PLANNER_ANSWERS, "mowing.plan": lambda params: plan(params["area_id"])})
    mower = await setup_mower(hass, entry, rpc)
    send(mower, "map/json", MAP)
    send(
        mower,
        "events/json",
        {"type": "AREA", "area_id": "front", "area_name": "Front", "job_id": "j", "t": 2, "id": "a1"},
    )
    send(
        mower,
        "robot_state/json",
        {**ROBOT_STATE, "current_state": "MOWING", "current_path": 1, "current_path_index": 100},
    )
    await hass.async_block_till_done()
    assert "mowing.plan" not in {method for method, _ in rpc.calls}


@patch("custom_components.mowbite.planning.LEFTOVERS_RECHECK", 0)
async def test_leftover_run(hass: HomeAssistant, entry: MockConfigEntry, no_connection: None) -> None:
    """A job mowing only an area's leftovers: robot_state's path counts in the leftovers, no progress or time."""
    log = {
        "lines": [
            {"t": 1.5, "level": "INFO", "msg": "MowBite Planner: area front, the leftovers: 3 passes, 1.2 m2"},
        ]
    }
    rpc = FakeRpc(
        {
            **PLANNER_ANSWERS,
            "rpc.methods": [*PLANNER_ANSWERS["rpc.methods"], "planner.log"],
            # only the lines since the time asked, like the planner
            "planner.log": lambda params: {"lines": [line for line in log["lines"] if line["t"] >= params["since"]]},
        }
    )
    mower = await setup_mower(hass, entry, rpc)
    send(mower, "map/json", MAP)
    send(
        mower,
        "events/json",
        {"type": "AREA", "area_id": "front", "area_name": "Front", "job_id": "j", "t": 2, "id": "a1"},
    )
    send(mower, "position/json", {"x": 1, "y": 1, "heading": 0, "attributes": {"job_id": "j", "blades": True}})
    send(
        mower,
        "robot_state/json",
        {**ROBOT_STATE, "current_state": "MOWING", "current_path": 0, "current_path_index": 10},
    )
    await hass.async_block_till_done()
    assert ("planner.log", {"since": -28, "limit": 200}) in rpc.calls
    assert hass.states.get("sensor.openmower_area_progress").state == "unknown"
    assert hass.states.get("sensor.openmower_time_left").state == "unknown"
    assert hass.states.get("sensor.openmower_current_area").attributes["leftovers"] is True
    assert entry.runtime_data.planning.card()["plan"] is None

    # the next job is a whole one again
    send(
        mower,
        "events/json",
        {"type": "AREA", "area_id": "front", "area_name": "Front", "job_id": "k", "t": 900, "id": "a2"},
    )
    send(mower, "position/json", {"x": 1, "y": 1, "heading": 0, "attributes": {"job_id": "k", "blades": True}})
    send(
        mower,
        "robot_state/json",
        {**ROBOT_STATE, "current_state": "MOWING", "current_path": 1, "current_path_index": 100},
    )
    await hass.async_block_till_done()
    assert hass.states.get("sensor.openmower_area_progress").state == "50"


@patch("custom_components.mowbite.planning.LEFTOVERS_RECHECK", 0)
async def test_leftover_run_stays_for_the_job(hass: HomeAssistant, entry: MockConfigEntry, no_connection: None) -> None:
    """Home for rain and out again starts the area anew without a new line, it's still only leftovers. A line from
    before the job left the dock isn't its own"""
    lines = [{"t": 95.0, "level": "INFO", "msg": "MowBite Planner: area back, the leftovers: 1 pass"}]
    rpc = FakeRpc(
        {
            **PLANNER_ANSWERS,
            "rpc.methods": [*PLANNER_ANSWERS["rpc.methods"], "planner.log"],
            "planner.log": lambda params: {"lines": [line for line in lines if line["t"] >= params["since"]]},
        }
    )
    mower = await setup_mower(hass, entry, rpc)
    send(mower, "map/json", MAP)
    send(mower, "position/json", {"x": 1, "y": 1, "heading": 0, "attributes": {"job_id": "j", "blades": True}})
    mowing = {**ROBOT_STATE, "current_state": "MOWING", "current_path": 0, "current_path_index": 10}

    # left the dock at 98: the line at 95 belongs to the job before
    send(mower, "events/json", {"type": "STATE", "state": "UNDOCKING", "job_id": "j", "t": 98, "id": "s1"})
    send(
        mower,
        "events/json",
        {"type": "AREA", "area_id": "back", "area_name": "Back", "job_id": "j", "t": 100, "id": "a1"},
    )
    send(mower, "robot_state/json", mowing)
    await hass.async_block_till_done()
    assert hass.states.get("sensor.openmower_current_area").attributes["leftovers"] is False

    # the front only its leftovers, then home for rain and out again: no new line, still leftovers
    lines.append({"t": 199.5, "level": "INFO", "msg": "MowBite Planner: area front, the leftovers: 2 passes"})
    send(
        mower,
        "events/json",
        {"type": "AREA", "area_id": "front", "area_name": "Front", "job_id": "j", "t": 200, "id": "a2"},
    )
    send(mower, "robot_state/json", {**mowing, "current_path_index": 11})
    await hass.async_block_till_done()
    assert hass.states.get("sensor.openmower_current_area").attributes["leftovers"] is True
    send(
        mower,
        "events/json",
        {"type": "AREA", "area_id": "front", "area_name": "Front", "job_id": "j", "t": 900, "id": "a3"},
    )
    send(mower, "robot_state/json", {**mowing, "current_path_index": 12})
    await hass.async_block_till_done()
    assert hass.states.get("sensor.openmower_current_area").attributes["leftovers"] is True

    # the job done, the flag goes with it
    send(mower, "events/json", {"type": "JOB_COMPLETE", "job_id": "j", "t": 950, "id": "c1"})
    assert entry.runtime_data.planning._leftover_runs == set()
