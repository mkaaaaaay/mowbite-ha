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
    send(mower, "position/json", {"x": 1, "y": None, "heading": "north", "attributes": ["job"]})
    assert mower.position == {"x": 1.0, "y": 0.0, "heading": 0.0, "blades": False, "job_id": ""}
    send(mower, "position/json", {"x": 2, "y": 3, "attributes": {"job_id": 7, "blades": True}})
    assert mower.position["job_id"] == "" and mower.position["blades"] is True


async def test_a_message_it_cant_handle_keeps_the_connection() -> None:
    mower = Mower("host", 1883, None, None, "")
    handled = []
    handle = mower.handle

    def fussy(topic: str, payload: bytes) -> None:
        handled.append(topic)
        if topic == "bad":
            raise ValueError("bad")
        handle(topic, payload)

    mower.handle = fussy  # type: ignore[method-assign]

    async def messages() -> AsyncIterator[SimpleNamespace]:
        yield SimpleNamespace(topic="bad", payload=b"")
        yield SimpleNamespace(topic="robot_state/json", payload=json.dumps(ROBOT_STATE).encode())
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
    mower.add_event_listener(lambda event: seen.append((event["type"], event.get("emergency"))))
    # the first robot_state is how things are, not a change
    send(mower, "robot_state/json", {**ROBOT_STATE, "emergency": 1})
    # mower_logic's own EMERGENCY event would be a second message for the same stop
    send(mower, "events/json", {"id": "a", "type": "EMERGENCY", "emergency": True, "reason": "4"})
    send(mower, "robot_state/json", {**ROBOT_STATE, "emergency": 1})
    send(mower, "robot_state/json", {**ROBOT_STATE, "emergency": 0})
    send(mower, "robot_state/json", {**ROBOT_STATE, "emergency": 1})
    assert seen == [("EMERGENCY", False), ("EMERGENCY", True)]


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
        yield SimpleNamespace(topic="actions/json", payload=json.dumps(ACTIONS).encode())
        yield SimpleNamespace(topic="robot_state/json", payload=json.dumps(ROBOT_STATE).encode())
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


async def test_action_needs_a_connection() -> None:
    mower = _mower()
    with pytest.raises(mower_module.CannotConnect):
        await mower.async_action("mower_logic:idle/start_mowing")
