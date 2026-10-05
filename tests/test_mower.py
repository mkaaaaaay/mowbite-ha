"""The MQTT side without Home Assistant."""

from __future__ import annotations

from unittest.mock import patch

from freezegun.api import FrozenDateTimeFactory
import pytest
from pytest_homeassistant_custom_component.common import async_fire_time_changed

from homeassistant.core import HomeAssistant

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


async def test_action_needs_a_connection() -> None:
    mower = _mower()
    with pytest.raises(mower_module.CannotConnect):
        await mower.async_action("mower_logic:idle/start_mowing")
