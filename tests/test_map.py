"""What the card's map is drawn from: the map, the position, the track and the app's settings."""

from __future__ import annotations

import asyncio
from datetime import timedelta
import json
from typing import Any
from unittest.mock import AsyncMock, patch

from pytest_homeassistant_custom_component.common import MockConfigEntry, async_fire_time_changed
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker
from pytest_homeassistant_custom_component.typing import WebSocketGenerator

from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.util import dt as dt_util

from custom_components.mowbite.const import CONF_APP_URL, CONF_MAP
from custom_components.mowbite.mower import Mower, RpcError, Track, _history

from .conftest import send

MOWER = "lawn_mower.openmower"
MAP = {
    "areas": [
        {"id": "a", "properties": {"name": "Garten", "type": "mow"}, "outline": [{"x": 0, "y": 0}, {"x": 5, "y": 0}, {"x": 5, "y": 5}]},
        {"id": "b", "properties": {"name": "Baum", "type": "obstacle"}, "outline": [{"x": 1, "y": 1}, {"x": 2, "y": 1}, {"x": 2, "y": 2}]},
    ],
    "docking_stations": [{"id": "d", "properties": {"name": "Docking Station"}, "position": {"x": -0.77, "y": 1.28}, "heading": 2.88}],
}


def _position(x: float, y: float, job: str = "job1", blades: bool = True) -> dict[str, Any]:
    return {"x": x, "y": y, "heading": 1.2, "attributes": {"job_id": job, "session_id": "", "blades": blades}}


def test_track() -> None:
    track = Track()
    assert not track.add(0, 0, True, "")
    assert track.add(0, 0, True, "job1")
    # too close to the last point
    assert not track.add(0.01, 0.01, True, "job1")
    # but the blades going off is a new point
    assert track.add(0.01, 0.01, False, "job1")
    assert track.add(1.234567, 2.345678, False, "job1")
    assert track.points[-1] == (1.23, 2.35, False)
    generation = track.generation
    assert track.add(9, 9, True, "job2")
    assert track.points == [(9, 9, True)]
    assert track.generation == generation + 1


def test_track_seed_and_limit() -> None:
    track = Track()
    track.add(5, 5, True, "job1")
    track.seed("job1", [(0, 0, True), (1, 0, False)])
    assert track.points == [(0, 0, True), (1, 0, False), (5, 5, True)]
    # another job's history isn't this job's
    track.seed("other", [(7, 7, True)])
    assert (7, 7, True) not in track.points
    track.MAX_POINTS = 10
    for i in range(20):
        track.add(i, 0, True, "job1")
    assert len(track.points) <= 10


def test_history() -> None:
    result = {
        "segments": [
            {"points": [[0, 0], [1, 0]], "attributes": {"blades": True}},
            {"points": [[1, 1]], "attributes": {"blades": False}},
        ],
        "buffer": [[2, 2]],
    }
    assert _history(result) == [(0, 0, True), (1, 0, True), (1, 1, False), (2, 2, False)]
    assert _history(None) == []


async def test_rpc(hass: HomeAssistant, mower: Mower) -> None:
    sent: list[dict[str, Any]] = []
    mower._client = AsyncMock()
    mower._client.publish.side_effect = lambda topic, payload: sent.append(json.loads(payload))
    task = asyncio.ensure_future(mower.async_rpc("rpc.methods"))
    await asyncio.sleep(0)
    request = sent[0]
    assert request["method"] == "rpc.methods"
    # someone else's answer is ignored
    send(mower, "rpc/response", {"jsonrpc": "2.0", "id": "x", "result": ["nope"]})
    send(mower, "rpc/response", {"jsonrpc": "2.0", "id": request["id"], "result": ["map.replace"]})
    assert await task == ["map.replace"]

    task = asyncio.ensure_future(mower.async_rpc("dance"))
    await asyncio.sleep(0)
    send(mower, "rpc/response", {"jsonrpc": "2.0", "id": sent[-1]["id"], "error": {"code": -32601, "message": "Method not found"}})
    try:
        await task
    except RpcError:
        pass
    else:
        raise AssertionError("an error answer should raise")


async def test_track_comes_from_the_history(hass: HomeAssistant, mower: Mower) -> None:
    history = {"segments": [{"points": [[0, 0], [3, 0]], "attributes": {"blades": True}}], "buffer": []}
    with patch.object(mower, "async_rpc", AsyncMock(return_value=history)) as rpc:
        send(mower, "position/json", _position(4, 0))
        await hass.async_block_till_done()
    rpc.assert_awaited_once_with("position.history", {"job_id": "job1"})
    assert mower.track.points == [(0, 0, True), (3, 0, True), (4, 0, True)]
    # once per job
    with patch.object(mower, "async_rpc", AsyncMock(return_value=history)) as rpc:
        send(mower, "position/json", _position(5, 0))
        await hass.async_block_till_done()
    rpc.assert_not_awaited()


async def test_feed(hass: HomeAssistant, hass_ws_client: WebSocketGenerator, mower: Mower) -> None:
    send(mower, "map/json", MAP)
    with patch.object(mower, "async_rpc", AsyncMock(side_effect=RpcError("no history here"))):
        send(mower, "position/json", _position(0, 0))
        send(mower, "position/json", _position(1, 0))
        await hass.async_block_till_done()
    client = await hass_ws_client(hass)
    await client.send_json_auto_id({"type": "mowbite/subscribe", "entity_id": MOWER})
    assert (await client.receive_json())["success"]
    first = (await client.receive_json())["event"]
    assert first["map"] == MAP
    assert first["track"] == {"reset": True, "points": [[0, 0, True], [1, 0, True]]}
    assert first["position"] == {"x": 1, "y": 0, "heading": 1.2, "blades": True, "job_id": "job1"}
    assert first["settings"] == {}

    # afterwards only what's new
    send(mower, "position/json", _position(2, 0, blades=False))
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=1))
    update = (await client.receive_json())["event"]
    assert "map" not in update
    assert "settings" not in update
    assert update["track"] == {"reset": False, "points": [[2, 0, False]]}

    send(mower, "map/json", {**MAP, "areas": MAP["areas"][:1]})
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=2))
    update = (await client.receive_json())["event"]
    assert len(update["map"]["areas"]) == 1
    assert "track" not in update


SETTINGS = {
    "icons": {"mower": "nx100", "dock": "yardforce", "mowerSize": 1.9, "dockSize": 1.1, "mowerRealSize": True},
    "colors": {"mower": "#32b341", "obstacle": "#4400ff"},
    "dashboard": {"map": "auto"},
    "weather": True,
    "mowers": [],
}


async def test_app_settings(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    hass_ws_client: WebSocketGenerator,
    entry: MockConfigEntry,
    no_connection: None,
) -> None:
    aioclient_mock.get("http://openmower:8082/cgi-bin/settings", json=SETTINGS)
    entry.add_to_hass(hass)
    hass.config_entries.async_update_entry(entry, options={CONF_APP_URL: "http://openmower:8082"})
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    entry.runtime_data.mower._connected = True
    client = await hass_ws_client(hass)
    await client.send_json_auto_id({"type": "mowbite/subscribe", "entity_id": MOWER})
    assert (await client.receive_json())["success"]
    # only what the card draws with
    assert (await client.receive_json())["event"]["settings"] == {
        "icons": SETTINGS["icons"],
        "colors": SETTINGS["colors"],
        "dashboard": SETTINGS["dashboard"],
    }


async def test_options(hass: HomeAssistant, aioclient_mock: AiohttpClientMocker, entry: MockConfigEntry, no_connection: None) -> None:
    aioclient_mock.get("http://openmower:8082/cgi-bin/settings", json=SETTINGS)
    aioclient_mock.get("http://nothing:8082/cgi-bin/settings", status=404)
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["type"] is FlowResultType.FORM
    result = await hass.config_entries.options.async_configure(result["flow_id"], {CONF_APP_URL: "nothing:8082"})
    assert result["errors"] == {"base": "cannot_reach_app"}
    # without http:// it's added
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {CONF_APP_URL: "openmower:8082/", CONF_MAP: "always"}
    )
    await hass.async_block_till_done()
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert entry.options == {CONF_APP_URL: "http://openmower:8082", CONF_MAP: "always"}
    # the entry was loaded again with it
    assert entry.runtime_data.app.data["icons"]["mower"] == "nx100"
    assert entry.runtime_data.map_mode == "always"


async def test_map_mode_reaches_the_card(hass: HomeAssistant, hass_ws_client: WebSocketGenerator, mower: Mower) -> None:
    client = await hass_ws_client(hass)
    await client.send_json_auto_id({"type": "mowbite/subscribe", "entity_id": MOWER})
    assert (await client.receive_json())["success"]
    # without a setting the cards go by the app's own
    assert (await client.receive_json())["event"]["map_mode"] == "app"
