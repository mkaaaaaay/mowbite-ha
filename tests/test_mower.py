"""The MQTT side without Home Assistant."""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from contextlib import suppress
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from freezegun.api import FrozenDateTimeFactory
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import async_fire_time_changed

from custom_components.mowbite import mower as mower_module
from custom_components.mowbite.mower import Mower, normalize_prefix

from .conftest import ACTIONS, ROBOT_STATE, send


@pytest.mark.parametrize(
    ("prefix", "normalized"),
    [(None, ""), ("", ""), ("  ", ""), ("openmower", "openmower/"), ("openmower/", "openmower/"), (" a/b ", "a/b/")],
)
def test_normalize_prefix(prefix: str | None, normalized: str) -> None:
    assert normalize_prefix(prefix) == normalized


def _mower(prefix: str = "") -> Mower:
    mower = Mower("host", 1883, None, None, prefix)
    mower._connected = True
    return mower


def test_state_behind_prefix() -> None:
    mower = _mower("openmower")
    send(mower, "robot_state/json", ROBOT_STATE)
    assert mower.state is None
    send(mower, "openmower/robot_state/json", ROBOT_STATE)
    assert mower.state == ROBOT_STATE
    assert mower.available


def test_bad_payloads_are_ignored() -> None:
    mower = _mower()
    send(mower, "robot_state/json", "not json")
    send(mower, "robot_state/json", [1, 2])
    send(mower, "actions/json", {"no": "list"})
    send(mower, "events/json", "nope")
    assert mower.state is None
    assert mower.actions is None


def test_bad_positions_are_ignored() -> None:
    mower = _mower()
    send(mower, "position/json", '{"x": NaN, "y": 1}')
    send(mower, "position/json", {"x": True, "y": 1})
    assert mower.position is None
    # half a place is no place
    send(mower, "position/json", {"x": 1, "y": None})
    send(mower, "position/json", {"x": 1})
    assert mower.position is None
    send(mower, "position/json", {"x": 1, "y": 2, "heading": "north", "attributes": ["job"]})
    assert mower.position == {"x": 1.0, "y": 2.0, "heading": 0.0, "blades": False, "job_id": ""}
    send(mower, "position/json", {"x": 2, "y": 3, "attributes": {"job_id": 7, "blades": True}})
    assert mower.position["job_id"] == "" and mower.position["blades"] is True


async def test_a_message_it_cant_handle_keeps_the_connection() -> None:
    mower = Mower("host", 1883, None, None, "")
    handled = []
    handle = mower.handle

    def fussy(topic: str, payload: bytes, kept: bool) -> None:
        handled.append(topic)
        if topic == "bad":
            raise ValueError("bad")
        handle(topic, payload, kept)

    mower.handle = fussy  # type: ignore[method-assign]

    async def messages() -> AsyncIterator[SimpleNamespace]:
        yield SimpleNamespace(topic="bad", payload=b"", retain=False)
        yield SimpleNamespace(topic="robot_state/json", payload=json.dumps(ROBOT_STATE).encode(), retain=False)
        await asyncio.Event().wait()

    connection = MagicMock()
    connection.__aenter__.return_value = SimpleNamespace(subscribe=AsyncMock(), messages=messages())
    with patch.object(mower_module, "_client", return_value=connection):
        task = asyncio.create_task(mower.run())
        for _ in range(20):
            await asyncio.sleep(0)
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task
    assert handled == ["bad", "robot_state/json"]
    assert mower.state == ROBOT_STATE


def test_actions() -> None:
    mower = _mower()
    assert mower.action_enabled("mower_logic:idle/start_mowing") is None
    send(mower, "actions/json", ACTIONS)
    assert mower.action_enabled("mower_logic:idle/start_mowing") is True
    assert mower.action_enabled("mower_logic:mowing/pause") is False
    # an older OpenMower without that action
    assert mower.action_enabled("mower_logic:idle/reset_job") is False


def test_sensors() -> None:
    mower = _mower()
    calls = []
    mower.add_listener("sensor:om_v_battery", lambda: calls.append(1))
    send(mower, "sensors/om_v_battery/data", "28.410000")
    send(mower, "sensors/om_charge_state/data", "CC")
    send(mower, "sensors/om_mow_motor_temp/data", "25.0")
    assert mower.sensors == {"om_v_battery": 28.41, "om_charge_state": "CC", "om_mow_motor_temp": 25.0}
    assert calls == [1]


def test_a_sensor_that_stops_coming_is_dropped() -> None:
    mower = _mower()
    calls = []
    mower.add_listener("sensor:om_v_charge", lambda: calls.append(1))
    with patch.object(mower_module.time, "monotonic", return_value=1000.0):
        send(mower, "sensors/om_v_charge/data", "28.9")
        send(mower, "sensors/om_v_battery/data", "27.2")
    with patch.object(mower_module.time, "monotonic", return_value=1000.0 + mower_module.STALE_AFTER - 1):
        mower.check()
        assert mower.sensors == {"om_v_charge": 28.9, "om_v_battery": 27.2}
        send(mower, "sensors/om_v_battery/data", "27.1")
    with patch.object(mower_module.time, "monotonic", return_value=1000.0 + mower_module.STALE_AFTER):
        mower.check()
        mower.check()
    # the one that went on coming stays, whoever listens to the other is told once
    assert mower.sensors == {"om_v_battery": 27.1}
    assert calls == [1, 1]
    send(mower, "sensors/om_v_charge/data", "0.2")
    assert mower.sensors["om_v_charge"] == 0.2


def test_events_the_broker_kept() -> None:
    """Handed out on subscribing they're news only from right before the connection, live ones whatever their time."""
    mower = _mower()
    mower._connected_time = 1_800_000_000.0
    seen = []
    mower.add_event_listener(lambda event: seen.append(event["id"]))
    for event_id, t, kept in (
        ("yesterday", 1_800_000_000 - 86400, True),
        ("no time", None, True),
        ("no number", "now", True),
        ("just before", 1_800_000_000 - mower_module.KEPT_EVENT_WITHIN, True),
        # a mower whose clock is behind
        ("live", 1_800_000_000 - 86400, False),
        ("live without", None, False),
    ):
        payload = json.dumps({"id": event_id, "type": "DOCKING_FAILED", "t": t})
        mower.handle("events/json", payload.encode(), kept)
    assert seen == ["just before", "live", "live without"]
    # one of several kept in a list, and its reason isn't taken for the next emergency stop
    kept_list = [
        {"id": "old", "type": "DOCKED", "t": 5},
        {"type": "EMERGENCY", "emergency": True, "reason": "LIFT", "t": 5},
        {"id": "new", "type": "BOOTED", "t": 1_800_000_010},
    ]
    mower.handle("events/json", json.dumps(kept_list).encode(), True)
    assert seen[3:] == ["new"]
    assert mower._emergency_reason is None


def test_events_once_each() -> None:
    mower = _mower()
    seen = []
    mower.add_event_listener(lambda event: seen.append(event["type"]))
    send(mower, "events/json", {"id": "a", "type": "STATE", "state": "MOWING"})
    send(mower, "events/json", {"id": "b", "type": "GPS", "available": False})
    send(mower, "events/json", {"id": "b", "type": "GPS", "available": False})
    send(mower, "events/json", [{"id": "c", "type": "DOCKED"}, {"type": "BOOTED"}])
    send(mower, "events/json", {"id": "d"})
    assert seen == ["STATE", "GPS", "DOCKED", "BOOTED"]


def test_emergency_comes_from_robot_state() -> None:
    mower = _mower()
    seen = []
    mower.add_event_listener(lambda event: seen.append((event["type"], event.get("emergency"), event.get("reason"))))
    # no stop in the first robot_state is nothing to tell
    send(mower, "robot_state/json", ROBOT_STATE)
    assert seen == []
    send(mower, "robot_state/json", {**ROBOT_STATE, "emergency": 1})
    send(mower, "robot_state/json", {**ROBOT_STATE, "emergency": 1})
    send(mower, "robot_state/json", {**ROBOT_STATE, "emergency": 0})
    assert seen == [("EMERGENCY", True, None), ("EMERGENCY", False, None)]
    assert mower.emergency_event is None


def test_emergency_on_at_the_first_robot_state() -> None:
    """Home Assistant started while the stop was on: told once, nobody heard of it yet."""
    mower = _mower()
    seen = []
    mower.add_event_listener(lambda event: seen.append((event["type"], event.get("emergency"))))
    send(mower, "robot_state/json", {**ROBOT_STATE, "emergency": 1})
    send(mower, "robot_state/json", {**ROBOT_STATE, "emergency": 1})
    assert seen == [("EMERGENCY", True)]
    assert mower.emergency_event is not None


def test_emergency_with_mower_logics_reason() -> None:
    """mower_logic's own EMERGENCY event isn't a second message, its reason goes with the stop robot_state shows."""
    mower = _mower()
    seen = []
    mower.add_event_listener(lambda event: seen.append((event.get("emergency"), event.get("reason"))))
    send(mower, "robot_state/json", ROBOT_STATE)
    # the reason first, as it mostly comes
    send(mower, "events/json", {"id": "a", "type": "EMERGENCY", "emergency": True, "reason": "4"})
    assert seen == []
    send(mower, "robot_state/json", {**ROBOT_STATE, "emergency": 1})
    assert seen == [(True, "4")]
    send(mower, "robot_state/json", ROBOT_STATE)
    # the stop first: told again with the reason, once
    send(mower, "robot_state/json", {**ROBOT_STATE, "emergency": 1})
    send(mower, "events/json", {"id": "b", "type": "EMERGENCY", "emergency": True, "reason": "8"})
    send(mower, "events/json", {"id": "c", "type": "EMERGENCY", "emergency": True, "reason": "8"})
    assert seen[2:] == [(True, None), (True, "8")]
    send(mower, "robot_state/json", ROBOT_STATE)
    # a reason from long before isn't this stop's
    now = mower_module.time.monotonic()
    send(mower, "events/json", {"id": "d", "type": "EMERGENCY", "emergency": True, "reason": "2"})
    with patch.object(mower_module.time, "monotonic", return_value=now + mower_module.EMERGENCY_REASON_WITHIN + 1):
        send(mower, "robot_state/json", {**ROBOT_STATE, "emergency": 1})
    assert seen[-1] == (True, None)


def test_goes_stale_without_robot_state() -> None:
    mower = _mower()
    calls = []
    mower.add_listener("state", lambda: calls.append(1))
    with patch.object(mower_module.time, "monotonic", return_value=1000.0):
        send(mower, "robot_state/json", ROBOT_STATE)
        assert mower.available
    assert len(calls) == 1
    with patch.object(mower_module.time, "monotonic", return_value=1000.0 + mower_module.STALE_AFTER + 1):
        assert not mower.available
        mower.check()
        mower.check()
    assert len(calls) == 2
    with patch.object(mower_module.time, "monotonic", return_value=2000.0):
        send(mower, "robot_state/json", ROBOT_STATE)
        assert mower.available
    assert len(calls) == 3


async def test_going_quiet_reaches_the_entities(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory, mower: Mower
) -> None:
    # the 10 s check runs in the event loop, an entity writing its state from a worker thread would raise here
    assert hass.states.get("lawn_mower.openmower").state != "unavailable"
    freezer.tick(mower_module.STALE_AFTER + 11)
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    assert hass.states.get("lawn_mower.openmower").state == "unavailable"


def test_map_keeps_only_numbers_to_draw() -> None:
    """What isn't a number in an outline or a dock's place never reaches the card, it writes them into its svg."""
    mower = _mower()
    bad = '0)"><img src=x onerror=alert(1)>'
    send(
        mower,
        "map/json",
        {
            "areas": [
                {"id": "a", "properties": {"type": "mow"}, "outline": [{"x": 0, "y": 0}, {"x": bad, "y": 1}, {"x": 5, "y": 5}, [1, 2]]},
                {"id": "b", "outline": "nope"},
                "nope",
            ],
            "docking_stations": [
                {"id": "d", "position": {"x": -0.77, "y": 1.28}, "heading": 2.88},
                {"id": "e", "position": {"x": bad, "y": 1}, "heading": 0},
                {"id": "f", "position": {"x": 1, "y": 1}, "heading": bad},
                {"id": "g", "position": {"x": 1, "y": 2}},
                {"id": "h", "position": [1, 2]},
            ],
        },
    )
    assert mower.map is not None
    assert [area["outline"] for area in mower.map["areas"]] == [[{"x": 0.0, "y": 0.0}, {"x": 5.0, "y": 5.0}], []]
    assert mower.map["areas"][0]["properties"] == {"type": "mow"}
    assert [(dock["id"], dock["position"], dock["heading"]) for dock in mower.map["docking_stations"]] == [
        ("d", {"x": -0.77, "y": 1.28}, 2.88),
        ("g", {"x": 1.0, "y": 2.0}, 0.0),
    ]
    assert bad not in json.dumps(mower.map)
    # no docks at all is a map too
    send(mower, "map/json", {"areas": [], "docking_stations": "nope"})
    assert mower.map == {"areas": [], "docking_stations": []}


def test_a_listener_that_fails_doesnt_stop_the_others() -> None:
    mower = _mower()
    calls = []

    def broken() -> None:
        raise ValueError("broken")

    mower.add_listener("state", broken)
    mower.add_listener("state", lambda: calls.append("state"))
    mower.add_change_listener(broken)
    mower.add_change_listener(lambda: calls.append("change"))
    mower.add_event_listener(lambda event: broken())
    mower.add_event_listener(lambda event: calls.append(event["type"]))
    send(mower, "robot_state/json", ROBOT_STATE)
    send(mower, "robot_state/json", ROBOT_STATE)
    send(mower, "events/json", {"id": "a", "type": "DOCKED"})
    assert calls == ["state", "change", "state", "change", "DOCKED", "change"]


async def test_connects_again_after_any_error() -> None:
    """Something unexpected while connected is logged and the mower is connected to again, not left until a reload."""
    mower = Mower("host", 1883, None, None, "")
    connections = []

    async def messages() -> AsyncIterator[SimpleNamespace]:
        yield SimpleNamespace(topic="actions/json", payload=json.dumps(ACTIONS).encode(), retain=False)
        yield SimpleNamespace(topic="robot_state/json", payload=json.dumps(ROBOT_STATE).encode(), retain=False)
        if len(connections) == 1:
            raise RuntimeError("unexpected")
        await asyncio.Event().wait()

    def client(*args: object) -> MagicMock:
        connection = MagicMock()
        connection.__aenter__.return_value = SimpleNamespace(subscribe=AsyncMock(), messages=messages())
        connection.__aexit__.return_value = False
        connections.append(connection)
        return connection

    gone = []
    mower.add_listener("state", lambda: gone.append(mower.connected))
    with patch.object(mower_module, "_client", client), patch.object(mower_module, "RECONNECT_MIN", 0):
        task = asyncio.create_task(mower.run())
        for _ in range(40):
            await asyncio.sleep(0)
        assert len(connections) == 2 and mower.connected
        assert mower.actions is not None
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task
    # the listeners heard it go and come back, and what it took before says nothing once it's gone
    assert False in gone and gone[-1] is False
    assert mower.actions is None


def test_refusal() -> None:
    mower = Mower("host", 1883, None, None, "")
    start, home = "mower_logic:idle/start_mowing", "mower_logic:mowing/abort_mowing"
    assert mower.refusal(start) == "not_connected"
    mower._connected = True
    # nothing known yet: nothing that sets it moving, the rest is the mower's to take or drop
    assert mower.refusal(start) == "action_unavailable"
    assert mower.refusal(home) is None
    send(mower, "robot_state/json", ROBOT_STATE)
    assert mower.refusal(start) == "action_unavailable"
    send(mower, "actions/json", ACTIONS)
    assert mower.refusal(start) is None
    assert mower.refusal(home) == "action_unavailable"
    # the mower goes on offering start while its emergency stop is on
    send(mower, "robot_state/json", {**ROBOT_STATE, "emergency": 1})
    assert mower.refusal(start) == "emergency_active"
    assert mower.refusal("mower_logic/reset_emergency") is None
    send(mower, "robot_state/json", ROBOT_STATE)
    with patch.object(mower_module.time, "monotonic", return_value=mower_module.time.monotonic() + mower_module.STALE_AFTER + 1):
        assert mower.refusal(start) == "action_unavailable"


def test_only_finite_numbers() -> None:
    mower = _mower()
    send(mower, "sensors/om_v_battery/data", "26.4")
    for bad in ("nan", "inf", "-inf"):
        send(mower, "sensors/om_v_battery/data", bad)
    assert mower.sensors == {"om_v_battery": 26.4}
    # a datum that isn't a number is no datum, the tracker would work out a place with it
    send(mower, "params/json", '{"/ll/services/gps/datum_lat": NaN, "/ll/services/gps/datum_long": 10.5}')
    assert mower.datum is None
    send(mower, "params/json", {"/ll/services/gps/datum_lat": 52.2, "/ll/services/gps/datum_long": 10.5})
    assert mower.datum == {"lat": 52.2, "lon": 10.5}
    history = {
        "segments": [
            {"attributes": {"blades": True}, "points": [[0, 0], ["1", 0], [1, None], [2, 0, 9]]},
            {"attributes": "nope", "points": [[3, 0]]},
            "nope",
        ],
        "buffer": [[4, 0], [float("nan"), 0], "nope"],
    }
    assert mower_module._history(history) == [(0.0, 0.0, True), (2.0, 0.0, True), (3.0, 0.0, False), (4.0, 0.0, False)]
    assert mower_module._history({"segments": "nope", "buffer": 5}) == []


def test_the_position_counts_while_it_comes() -> None:
    mower = _mower()
    send(mower, "robot_state/json", ROBOT_STATE)
    assert mower.live_position is None
    assert mower.pose["x"] == ROBOT_STATE["pose"]["x"]
    now = mower_module.time.monotonic()
    send(mower, "position/json", {"x": 1, "y": 2, "heading": 0.5})
    assert mower.live_position == {"x": 1.0, "y": 2.0, "heading": 0.5, "blades": False, "job_id": ""}
    # it stopped coming: robot_state's pose is the newer one then
    with patch.object(mower_module.time, "monotonic", return_value=now + mower_module.STALE_AFTER + 1):
        assert mower.live_position is None
    # a pose that's no object is none
    send(mower, "robot_state/json", {**ROBOT_STATE, "pose": [1, 2]})
    assert mower.pose == {}


def test_the_area_goes_with_its_job() -> None:
    mower = _mower()
    send(mower, "events/json", {"id": "1", "type": "AREA", "area_id": "front", "area_name": "Front", "job_id": "j1"})
    send(mower, "position/json", {"x": 1, "y": 1, "attributes": {"job_id": "j1"}})
    assert (mower.area, mower.area_id) == ("Front", "front")
    # the next job's AREA event got lost: it isn't on the last job's area
    send(mower, "position/json", {"x": 1, "y": 1, "attributes": {"job_id": "j2"}})
    assert (mower.area, mower.area_id) == (None, None)
    send(mower, "events/json", {"id": "2", "type": "AREA", "area_id": "back", "area_name": "Back", "job_id": "j2"})
    assert mower.area_id == "back"
    # and not after it stopped mowing
    send(mower, "events/json", {"id": "3", "type": "STATE", "state": "DOCKING"})
    assert (mower.area, mower.area_id) == (None, None)


async def test_rpc_error_says_what_the_mower_said() -> None:
    mower = _mower()
    mower._client = SimpleNamespace(publish=AsyncMock())
    task = asyncio.create_task(mower.async_rpc("planner.plan", {"area_id": "front"}))
    await asyncio.sleep(0)
    request = json.loads(mower._client.publish.await_args.args[1])
    error = {"code": -32000, "message": "the body doesn't fit", "data": {"code": "BODY_OUT"}}
    send(mower, "rpc/response", {"id": request["id"], "error": error})
    with pytest.raises(mower_module.RpcError) as err:
        await task
    assert (err.value.code, err.value.data, str(err.value)) == (-32000, {"code": "BODY_OUT"}, "the body doesn't fit")


async def test_action_needs_a_connection() -> None:
    mower = _mower()
    with pytest.raises(mower_module.CannotConnect):
        await mower.async_action("mower_logic:idle/start_mowing")
