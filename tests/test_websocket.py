"""What the card talks to, and the card itself."""

from __future__ import annotations

from datetime import timedelta
from unittest.mock import AsyncMock, patch

from pytest_homeassistant_custom_component.common import MockConfigEntry, async_fire_time_changed
from pytest_homeassistant_custom_component.typing import ClientSessionGenerator, WebSocketGenerator

from homeassistant.components.frontend import DATA_EXTRA_MODULE_URL
from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util

from custom_components.mowbite.mower import Mower

from .conftest import ROBOT_STATE, send

MOWER = "lawn_mower.openmower"


async def test_subscribe(hass: HomeAssistant, hass_ws_client: WebSocketGenerator, mower: Mower) -> None:
    send(
        mower,
        "sensor_infos/json",
        [
            {
                "sensor_id": "om_mow_motor_temp",
                "sensor_name": "Mow Motor Temp",
                "value_description": "TEMPERATURE",
                "unit": "deg.C",
                "max_value": 0.0,
                "has_critical_high": 1,
                "upper_critical_value": 80.0,
                "has_min_max": 0,
            }
        ],
    )
    send(mower, "sensors/om_mow_motor_temp/data", "31.5")
    send(mower, "events/json", {"id": "1", "type": "STATE", "state": "IDLE", "t": 1791200000.5})
    client = await hass_ws_client(hass)
    await client.send_json_auto_id({"type": "mowbite/subscribe", "entity_id": MOWER})
    assert (await client.receive_json())["success"]
    data = (await client.receive_json())["event"]
    assert data["available"] is True
    assert data["state"]["current_state"] == "IDLE"
    assert data["sensors"]["om_mow_motor_temp"] == 31.5
    assert data["sensor_infos"]["om_mow_motor_temp"] == {
        "sensor_name": "Mow Motor Temp",
        "value_description": "TEMPERATURE",
        "unit": "deg.C",
        "max_value": 0.0,
        "has_critical_high": 1,
        "upper_critical_value": 80.0,
    }
    assert data["actions"]["mower_logic:idle/start_mowing"] is True
    assert data["since"] == 1791200000.5
    assert data["area"] is None

    # changes come at most twice a second
    send(mower, "events/json", {"id": "2", "type": "STATE", "state": "MOWING", "t": 1791200010.0})
    send(mower, "events/json", {"id": "3", "type": "AREA", "area_name": "Vorgarten", "t": 1791200011.0})
    send(mower, "robot_state/json", {**ROBOT_STATE, "current_state": "MOWING"})
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=1))
    data = (await client.receive_json())["event"]
    assert data["state"]["current_state"] == "MOWING"
    assert data["since"] == 1791200010.0
    assert data["area"] == "Vorgarten"


async def test_subscribe_not_a_mower(hass: HomeAssistant, hass_ws_client: WebSocketGenerator, mower: Mower) -> None:
    client = await hass_ws_client(hass)
    await client.send_json_auto_id({"type": "mowbite/subscribe", "entity_id": "light.kitchen"})
    msg = await client.receive_json()
    assert not msg["success"]
    assert msg["error"]["code"] == "not_found"


async def test_reload_tells_the_card(
    hass: HomeAssistant, hass_ws_client: WebSocketGenerator, entry: MockConfigEntry, mower: Mower
) -> None:
    client = await hass_ws_client(hass)
    await client.send_json_auto_id({"type": "mowbite/subscribe", "entity_id": MOWER})
    assert (await client.receive_json())["success"]
    await client.receive_json()
    assert await hass.config_entries.async_unload(entry.entry_id)
    assert (await client.receive_json())["event"]["closed"] is True


async def test_actions(hass: HomeAssistant, hass_ws_client: WebSocketGenerator, mower: Mower) -> None:
    client = await hass_ws_client(hass)
    with patch.object(mower, "async_action", AsyncMock()) as action:
        await client.send_json_auto_id({"type": "mowbite/action", "entity_id": MOWER, "action": "start"})
        assert (await client.receive_json())["success"]
        action.assert_awaited_once_with("mower_logic:idle/start_mowing")

        # paused only while mowing
        await client.send_json_auto_id({"type": "mowbite/action", "entity_id": MOWER, "action": "pause"})
        msg = await client.receive_json()
        assert msg["error"]["code"] == "action_unavailable"

        await client.send_json_auto_id({"type": "mowbite/action", "entity_id": MOWER, "action": "reset_emergency"})
        assert (await client.receive_json())["success"]
        assert action.await_args.args == ("mower_logic/reset_emergency",)

        await client.send_json_auto_id({"type": "mowbite/action", "entity_id": MOWER, "action": "dance"})
        assert (await client.receive_json())["error"]["code"] == "invalid_format"


async def test_action_without_connection(hass: HomeAssistant, hass_ws_client: WebSocketGenerator, mower: Mower) -> None:
    mower._client = None
    client = await hass_ws_client(hass)
    await client.send_json_auto_id({"type": "mowbite/action", "entity_id": MOWER, "action": "start"})
    assert (await client.receive_json())["error"]["code"] == "not_connected"


async def test_card_is_served(hass: HomeAssistant, hass_client: ClientSessionGenerator, mower: Mower) -> None:
    urls = [u for u in hass.data[DATA_EXTRA_MODULE_URL].urls if u.startswith("/mowbite/mowbite-card.js?v=")]
    assert len(urls) == 1
    client = await hass_client()
    response = await client.get(urls[0])
    assert response.status == 200
    assert "customElements.define('mowbite-card'" in await response.text()


async def test_rpc_reads_only(hass: HomeAssistant, hass_ws_client: WebSocketGenerator, mower: Mower) -> None:
    """The card's dashboard asks what the app's pages ask, nothing that changes the mower."""
    asked = []

    async def rpc(method, params=None, timeout=20):
        asked.append((method, params))
        return {"ok": method}

    mower.async_rpc = rpc  # type: ignore[method-assign]
    client = await hass_ws_client(hass)
    await client.send_json_auto_id(
        {"type": "mowbite/rpc", "entity_id": MOWER, "method": "events.history", "params": {"date": "20261018"}}
    )
    answer = await client.receive_json()
    assert answer["success"] and answer["result"] == {"result": {"ok": "events.history"}}
    for method, params in (
        ("params.set", {}),
        ("map.replace", {}),
        ("planner.settings.set", {"fill_pattern": "lanes"}),
        ("planner.leftovers", {"arm": True}),
    ):
        await client.send_json_auto_id({"type": "mowbite/rpc", "entity_id": MOWER, "method": method, "params": params})
        answer = await client.receive_json()
        assert not answer["success"] and answer["error"]["code"] == "not_allowed", method
    assert asked == [("events.history", {"date": "20261018"})]


async def test_rpc_no_mowing_plan_with_the_planner(
    hass: HomeAssistant, hass_ws_client: WebSocketGenerator, entry: MockConfigEntry, mower: Mower
) -> None:
    """With the MowBite Planner planning itself mowing.plan counts as mower_logic fetching its plan."""
    entry.runtime_data.planning.methods = {"planner.plan", "mowing.plan"}
    mower.async_rpc = AsyncMock(return_value={})  # type: ignore[method-assign]
    client = await hass_ws_client(hass)
    await client.send_json_auto_id(
        {"type": "mowbite/rpc", "entity_id": MOWER, "method": "mowing.plan", "params": {"area_id": "a"}}
    )
    answer = await client.receive_json()
    assert answer["error"]["code"] == "not_allowed"
    mower.async_rpc.assert_not_awaited()


async def test_rpc_error_code(hass: HomeAssistant, hass_ws_client: WebSocketGenerator, mower: Mower) -> None:
    from custom_components.mowbite.mower import RpcError

    mower.async_rpc = AsyncMock(side_effect=RpcError("Method not found", -32601))  # type: ignore[method-assign]
    client = await hass_ws_client(hass)
    await client.send_json_auto_id({"type": "mowbite/rpc", "entity_id": MOWER, "method": "logs.recent"})
    answer = await client.receive_json()
    assert answer["error"]["code"] == "rpc_-32601"


async def test_app_reads_only(
    hass: HomeAssistant, hass_ws_client: WebSocketGenerator, aioclient_mock, entry: MockConfigEntry, no_connection: None
) -> None:
    from custom_components.mowbite.const import CONF_APP_URL

    from .conftest import app_status

    url = "http://openmower:8082"
    aioclient_mock.get(url + "/cgi-bin/settings", json={})
    app_status(
        aioclient_mock,
        url,
        {"/version.json": '{"version": "1.4.0", "art": 1}', "/cgi-bin/schedule?log": "100 skip_rain\n"},
    )
    aioclient_mock.get(url + "/mowbite-art.js", text="export const ART_API = 1;")
    entry.add_to_hass(hass)
    hass.config_entries.async_update_entry(entry, options={CONF_APP_URL: url})
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    client = await hass_ws_client(hass)
    await client.send_json_auto_id({"type": "mowbite/app", "entity_id": MOWER, "path": "/cgi-bin/schedule?log"})
    answer = await client.receive_json()
    assert answer["result"] == {"status": 200, "body": "100 skip_rain\n"}
    for path in ("/cgi-bin/settings", "/cgi-bin/schedule?x=1", "/../etc/passwd", "http://elsewhere/"):
        await client.send_json_auto_id({"type": "mowbite/app", "entity_id": MOWER, "path": path})
        answer = await client.receive_json()
        assert answer["error"]["code"] == "not_allowed", path
    # the map's pictures the app serves, for the card's sandbox
    await client.send_json_auto_id({"type": "mowbite/art", "entity_id": MOWER})
    answer = await client.receive_json()
    assert answer["result"] == {"api": 1, "code": "export const ART_API = 1;"}


async def test_params_only_what_the_card_needs(
    hass: HomeAssistant, hass_ws_client: WebSocketGenerator, mower: Mower
) -> None:
    send(
        mower,
        "params/json",
        {
            "/ll/services/gps/datum_lat": 52.25,
            "/ll/services/gps/datum_long": 10.56,
            "/mower_logic/max_position_accuracy": 0.15,
            "/ll/services/gps/ntrip_password": "secret",
        },
    )
    client = await hass_ws_client(hass)
    await client.send_json_auto_id({"type": "mowbite/subscribe", "entity_id": MOWER})
    assert (await client.receive_json())["success"]
    data = (await client.receive_json())["event"]
    assert data["datum"] == {"lat": 52.25, "lon": 10.56}
    assert data["max_position_accuracy"] == 0.15
    assert "secret" not in str(data)
