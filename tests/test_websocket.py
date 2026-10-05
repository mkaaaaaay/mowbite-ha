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
    send(mower, "sensor_infos/json", [{"sensor_id": "om_mow_motor_temp", "sensor_name": "Mow Motor Temp",
                                       "value_description": "TEMPERATURE", "unit": "deg.C", "max_value": 0.0,
                                       "has_critical_high": 1, "upper_critical_value": 80.0, "has_min_max": 0}])
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
