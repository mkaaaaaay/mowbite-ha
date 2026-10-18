"""What the MowBite card talks to: the mower's state as it comes in, and its actions."""

from __future__ import annotations

import time
from typing import TYPE_CHECKING, Any

import voluptuous as vol

from homeassistant.components import websocket_api
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import CALLBACK_TYPE, HomeAssistant, callback
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.event import async_call_later

from .app import APP_READ, async_read
from .const import DOMAIN
from .mower import (
    ACTION_CONTINUE,
    ACTION_HOME,
    ACTION_PAUSE,
    ACTION_RESET_EMERGENCY,
    ACTION_RESET_JOB,
    ACTION_SKIP_AREA,
    ACTION_SKIP_PATH,
    ACTION_START,
    CannotConnect,
    RpcError,
)
from .planning import PLAN

if TYPE_CHECKING:
    from . import MowbiteData

# the card's buttons by name, each the mower_logic action the MowBite app sends for it
ACTIONS = {
    "start": ACTION_START,
    "pause": ACTION_PAUSE,
    "continue": ACTION_CONTINUE,
    "home": ACTION_HOME,
    "skip_area": ACTION_SKIP_AREA,
    "reset_emergency": ACTION_RESET_EMERGENCY,
    "reset_job": ACTION_RESET_JOB,
    "skip_path": ACTION_SKIP_PATH,
}

# what the card may ask the mower for its dashboard, as the app's own pages ask it: only what reads. planner.leftovers
# without "arm" (that's mowing the leftovers, the mow_leftovers action), mowing.plan only without the MowBite Planner
# planning itself (with it, it counts as mower_logic fetching its plan, see planning.plan_method)
READ_RPC = {
    "rpc.methods",
    "events.history",
    "events.history.list",
    "logs.recent",
    "position.history",
    "position.history.list",
    "planner.plan",
    "planner.settings",
    "planner.leftovers",
    "planner.drive",
    "planner.log",
    PLAN,
}
RPC_TIMEOUT = 30

# robot_state comes about once a second, the card gets at most two updates a second
SEND_INTERVAL = 0.5

# what the card reads of a sensor info: its name, what it measures and its limits
_INFO_KEYS = ("sensor_name", "value_description", "unit", "max_value", "has_critical_high", "upper_critical_value")


@callback
def async_setup(hass: HomeAssistant) -> None:
    websocket_api.async_register_command(hass, ws_subscribe)
    websocket_api.async_register_command(hass, ws_action)
    websocket_api.async_register_command(hass, ws_rpc)
    websocket_api.async_register_command(hass, ws_app)
    websocket_api.async_register_command(hass, ws_art)


def _data(hass: HomeAssistant, entity_id: str) -> MowbiteData | None:
    """The mower behind one of its entities, None when it isn't a loaded MowBite entity."""
    entity = er.async_get(hass).async_get(entity_id)
    if entity is None or entity.platform != DOMAIN or entity.config_entry_id is None:
        return None
    entry = hass.config_entries.async_get_entry(entity.config_entry_id)
    if entry is None or entry.state is not ConfigEntryState.LOADED:
        return None
    return entry.runtime_data


class Feed:
    """What one card got so far: the map and the app's settings only when they change, of the track only what's new."""

    def __init__(self, data: MowbiteData) -> None:
        self._data = data
        self._map = -1
        self._settings = -1
        self._track = -1
        self._points = 0
        self._planning = -1

    def next(self) -> dict[str, Any]:
        data = self._data
        out = snapshot(data)
        mower = data.mower
        if mower.map_version != self._map:
            self._map = mower.map_version
            out["map"] = mower.map
        if data.app.version != self._settings:
            self._settings = data.app.version
            out["settings"] = data.app.data
        planning = data.planning
        if planning.version != self._planning:
            self._planning = planning.version
            out["planning"] = planning.card()
        track = mower.track
        if track.generation != self._track:
            self._track = track.generation
            self._points = len(track.points)
            out["track"] = {"reset": True, "points": track.points}
        elif len(track.points) > self._points:
            out["track"] = {"reset": False, "points": track.points[self._points :]}
            self._points = len(track.points)
        return out


# the planner's settings that are the card's mower sizes
_PLANNER_SIZES = {
    "width": "robot_width",
    "front": "robot_front",
    "rear": "robot_rear",
    "blade": "mower_width",
    "bladeAhead": "blade_ahead",
    "bladeOffset": "blade_offset",
}


def planner_sizes(settings: dict[str, Any] | None) -> dict[str, float] | None:
    """The mower's sizes as the planner has them (measured on the mower), None without all of them."""
    sizes = {}
    for key, name in _PLANNER_SIZES.items():
        value = ((settings or {}).get(name) or {}).get("value")
        if not isinstance(value, (int, float)):
            return None
        sizes[key] = value
    # the body's real contour, [ahead, left] in m, when the planner has one
    outline = ((settings or {}).get("robot_outline") or {}).get("value")
    if isinstance(outline, list) and len(outline) >= 3:
        sizes["outline"] = outline
    return sizes


def snapshot(data: MowbiteData) -> dict[str, Any]:
    mower = data.mower
    current = (mower.state or {}).get("current_state")
    last = mower.last_state_event or {}
    return {
        "position": mower.position,
        "closed": mower.closed,
        "connected": mower.connected,
        "available": mower.available,
        "state": mower.state,
        "state_time": mower.state_time,
        "actions": mower.actions or {},
        "sensors": mower.sensors,
        "sensor_infos": {
            sensor_id: {k: info[k] for k in _INFO_KEYS if k in info} for sensor_id, info in mower.sensor_infos.items()
        },
        # only when the newest state change is this state, older mowers don't record every one (a pause, say)
        "since": last.get("t") if current is not None and last.get("state") == current else None,
        "map_mode": data.map_mode,
        "mower_sizes": data.mower_sizes,
        "planner_sizes": planner_sizes(data.planning.settings),
        # where the mower is in the plan of the area, for drawing what's still to mow
        "plan_at": [(mower.state or {}).get("current_path"), (mower.state or {}).get("current_path_index")],
        "area": mower.area if current == "MOWING" else None,
        "datum": mower.datum,
        "max_position_accuracy": mower.max_position_accuracy,
    }


@websocket_api.websocket_command({vol.Required("type"): "mowbite/subscribe", vol.Required("entity_id"): str})
@callback
def ws_subscribe(hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]) -> None:
    """Sends the mower's state now and whenever it changes, until the card unsubscribes."""
    data = _data(hass, msg["entity_id"])
    if data is None:
        connection.send_error(msg["id"], websocket_api.ERR_NOT_FOUND, "Not a MowBite entity")
        return
    pending: CALLBACK_TYPE | None = None
    sent_at = 0.0
    feed = Feed(data)

    @callback
    def send(_now: Any = None) -> None:
        nonlocal pending, sent_at
        pending = None
        sent_at = time.monotonic()
        connection.send_message(websocket_api.event_message(msg["id"], feed.next()))

    @callback
    def changed() -> None:
        nonlocal pending
        if pending is not None:
            return
        wait = SEND_INTERVAL - (time.monotonic() - sent_at)
        if wait <= 0 or data.mower.closed:
            send()
        else:
            pending = async_call_later(hass, wait, send)

    removes = [data.mower.add_change_listener(changed), data.app.add_listener(changed)]

    @callback
    def unsubscribe() -> None:
        for remove in removes:
            remove()
        if pending is not None:
            pending()

    connection.subscriptions[msg["id"]] = unsubscribe
    connection.send_result(msg["id"])
    send()


@websocket_api.websocket_command(
    {
        vol.Required("type"): "mowbite/action",
        vol.Required("entity_id"): str,
        vol.Required("action"): vol.In([*ACTIONS, "mow_leftovers"]),
    }
)
@websocket_api.async_response
async def ws_action(hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]) -> None:
    """One of the card's buttons."""
    data = _data(hass, msg["entity_id"])
    if data is None:
        connection.send_error(msg["id"], websocket_api.ERR_NOT_FOUND, "Not a MowBite entity")
        return
    if msg["action"] == "mow_leftovers":
        # the planner gets the leftovers ready, a start in the next minutes mows only them
        try:
            armed = await data.mower.async_rpc("planner.leftovers", {"arm": True})
        except (RpcError, TimeoutError, CannotConnect):
            connection.send_error(msg["id"], "planner_failed", "The planner didn't take it")
            return
        if not isinstance(armed, dict) or not armed.get("armed"):
            connection.send_error(msg["id"], "planner_failed", "The planner didn't take it")
            return
        msg = {**msg, "action": "start"}
    action_id = ACTIONS[msg["action"]]
    # actions/json says which actions the mower takes right now, one it doesn't take would just be dropped
    if data.mower.action_enabled(action_id) is False:
        connection.send_error(msg["id"], "action_unavailable", "The mower doesn't take that right now")
        return
    try:
        await data.mower.async_action(action_id)
    except CannotConnect:
        connection.send_error(msg["id"], "not_connected", "Not connected to the mower")
        return
    connection.send_result(msg["id"])


@websocket_api.websocket_command(
    {
        vol.Required("type"): "mowbite/rpc",
        vol.Required("entity_id"): str,
        vol.Required("method"): str,
        vol.Optional("params"): vol.Any(dict, list),
    }
)
@websocket_api.async_response
async def ws_rpc(hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]) -> None:
    """Asks the mower one of READ_RPC for the card's dashboard."""
    data = _data(hass, msg["entity_id"])
    if data is None:
        connection.send_error(msg["id"], websocket_api.ERR_NOT_FOUND, "Not a MowBite entity")
        return
    method = msg["method"]
    params = msg.get("params", {})
    allowed = method in READ_RPC
    if method == "planner.leftovers" and isinstance(params, dict) and params.get("arm"):
        allowed = False
    if method == PLAN and data.planning.plan_method != PLAN:
        allowed = False
    if not allowed:
        connection.send_error(msg["id"], "not_allowed", f"{method} isn't read only")
        return
    try:
        result = await data.mower.async_rpc(method, params, RPC_TIMEOUT)
    except RpcError as err:
        # the json-rpc code goes along, the card tells a method the mower doesn't have (-32601) from a failure
        connection.send_error(msg["id"], f"rpc_{err.code}" if err.code is not None else "rpc_error", str(err))
        return
    except TimeoutError:
        connection.send_error(msg["id"], "timeout", f"{method} timed out")
        return
    except CannotConnect:
        connection.send_error(msg["id"], "not_connected", "Not connected to the mower")
        return
    connection.send_result(msg["id"], {"result": result})


@websocket_api.websocket_command(
    {vol.Required("type"): "mowbite/app", vol.Required("entity_id"): str, vol.Required("path"): str}
)
@websocket_api.async_response
async def ws_app(hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]) -> None:
    """Reads one of the app's endpoints for the card's dashboard (APP_READ), with the MowBite address set."""
    data = _data(hass, msg["entity_id"])
    if data is None:
        connection.send_error(msg["id"], websocket_api.ERR_NOT_FOUND, "Not a MowBite entity")
        return
    if not APP_READ.match(msg["path"]):
        connection.send_error(msg["id"], "not_allowed", "Not one the card reads")
        return
    if not data.app.url:
        connection.send_result(msg["id"], {"status": 404, "body": ""})
        return
    status, body = await async_read(hass, data.app.url, msg["path"])
    connection.send_result(msg["id"], {"status": status, "body": body})


@websocket_api.websocket_command({vol.Required("type"): "mowbite/art", vol.Required("entity_id"): str})
@websocket_api.async_response
async def ws_art(hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]) -> None:
    """The map's pictures the mower's MowBite serves, for the card to draw with in a sandbox. None without them."""
    data = _data(hass, msg["entity_id"])
    if data is None:
        connection.send_error(msg["id"], websocket_api.ERR_NOT_FOUND, "Not a MowBite entity")
        return
    art = await data.status.async_art()
    connection.send_result(msg["id"], {"api": art[0], "code": art[1]} if art else {"api": None, "code": None})
