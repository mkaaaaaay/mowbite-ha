"""The entities once a mower is set up."""

from __future__ import annotations

from datetime import timedelta
from unittest.mock import AsyncMock, patch

import pytest
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_time_changed,
    mock_restore_cache_with_extra_data,
)

from homeassistant.components.lawn_mower import LawnMowerActivity
from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import ATTR_ENTITY_ID, STATE_UNAVAILABLE
from homeassistant.core import Event, EventStateChangedData, HomeAssistant, State, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.event import async_track_state_change_event
from homeassistant.util import dt as dt_util

from custom_components.mowbite.mower import Mower

from .conftest import ACTIONS, ROBOT_STATE, send

MOWER = "lawn_mower.openmower"


async def test_unavailable_until_the_mower_speaks(
    hass: HomeAssistant, entry: MockConfigEntry, no_connection: None
) -> None:
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.LOADED
    assert hass.states.get(MOWER).state == STATE_UNAVAILABLE

    mower: Mower = entry.runtime_data.mower
    mower._connected = True
    send(mower, "robot_state/json", ROBOT_STATE)
    await hass.async_block_till_done()
    assert hass.states.get(MOWER).state == LawnMowerActivity.DOCKED

    assert await hass.config_entries.async_unload(entry.entry_id)
    assert entry.state is ConfigEntryState.NOT_LOADED


async def test_states(hass: HomeAssistant, mower: Mower) -> None:
    assert hass.states.get("sensor.openmower_battery").state == "83"
    assert hass.states.get("sensor.openmower_state").state == "idle"
    assert hass.states.get("sensor.openmower_gps_quality").state == "97"
    assert hass.states.get("binary_sensor.openmower_charging").state == "on"
    assert hass.states.get("binary_sensor.openmower_emergency_stop").state == "off"
    assert hass.states.get("binary_sensor.openmower_rain").state == "off"
    # nothing on the sensor topic yet
    assert hass.states.get("sensor.openmower_battery_voltage").state == STATE_UNAVAILABLE
    send(mower, "sensors/om_v_battery/data", "28.41")
    await hass.async_block_till_done()
    assert hass.states.get("sensor.openmower_battery_voltage").state == "28.41"


@pytest.mark.parametrize(
    ("changes", "activity"),
    [
        ({"current_state": "MOWING"}, LawnMowerActivity.MOWING),
        ({"current_state": "UNDOCKING"}, LawnMowerActivity.MOWING),
        ({"current_state": "PAUSED"}, LawnMowerActivity.PAUSED),
        ({"current_state": "DOCKING"}, LawnMowerActivity.RETURNING),
        ({"current_state": "MOWING", "emergency": 1}, LawnMowerActivity.ERROR),
    ],
)
async def test_activity(hass: HomeAssistant, mower: Mower, changes: dict, activity: LawnMowerActivity) -> None:
    send(mower, "robot_state/json", {**ROBOT_STATE, **changes})
    await hass.async_block_till_done()
    assert hass.states.get(MOWER).state == activity


async def test_idle_in_the_dock_or_on_the_lawn(hass: HomeAssistant, mower: Mower) -> None:
    # Home Assistant before 2026.10 only knows docked
    idle = getattr(LawnMowerActivity, "IDLE", LawnMowerActivity.DOCKED)
    # charging: in the dock
    assert hass.states.get(MOWER).state == LawnMowerActivity.DOCKED
    # not charging, nothing on the charging contacts: standing on the lawn
    send(mower, "robot_state/json", {**ROBOT_STATE, "is_charging": 0})
    await hass.async_block_till_done()
    assert hass.states.get(MOWER).state == idle
    # fully charged it doesn't charge, but the contacts still have the dock's voltage
    send(mower, "sensors/om_v_charge/data", "28.9")
    await hass.async_block_till_done()
    assert hass.states.get(MOWER).state == LawnMowerActivity.DOCKED
    send(mower, "sensors/om_v_charge/data", "0.1")
    await hass.async_block_till_done()
    assert hass.states.get(MOWER).state == idle


async def _call(hass: HomeAssistant, service: str) -> None:
    await hass.services.async_call("lawn_mower", service, {ATTR_ENTITY_ID: MOWER}, blocking=True)


def _enable(mower: Mower, *action_ids: str) -> None:
    send(mower, "actions/json", [{**a, "enabled": int(a["action_id"] in action_ids)} for a in ACTIONS])


async def test_start_pause_dock(hass: HomeAssistant, mower: Mower) -> None:
    with patch.object(mower, "async_action", AsyncMock()) as action:
        await _call(hass, "start_mowing")
        action.assert_awaited_once_with("mower_logic:idle/start_mowing")

        _enable(mower, "mower_logic:mowing/pause", "mower_logic:mowing/abort_mowing")
        send(mower, "robot_state/json", {**ROBOT_STATE, "current_state": "MOWING"})
        action.reset_mock()
        await _call(hass, "pause")
        action.assert_awaited_once_with("mower_logic:mowing/pause")

        _enable(mower, "mower_logic:mowing/continue", "mower_logic:mowing/abort_mowing")
        send(mower, "robot_state/json", {**ROBOT_STATE, "current_state": "PAUSED"})
        action.reset_mock()
        await _call(hass, "start_mowing")
        action.assert_awaited_once_with("mower_logic:mowing/continue")

        action.reset_mock()
        await _call(hass, "dock")
        action.assert_awaited_once_with("mower_logic:mowing/abort_mowing")


async def test_action_the_mower_doesnt_take(hass: HomeAssistant, mower: Mower) -> None:
    with patch.object(mower, "async_action", AsyncMock()) as action:
        with pytest.raises(HomeAssistantError) as err:
            await _call(hass, "pause")
        assert err.value.translation_key == "action_unavailable"
        action.assert_not_awaited()


async def test_action_without_connection(hass: HomeAssistant, mower: Mower) -> None:
    mower._client = None
    with pytest.raises(HomeAssistantError) as err:
        await _call(hass, "start_mowing")
    assert err.value.translation_key == "not_connected"


async def test_buttons(hass: HomeAssistant, entity_registry: er.EntityRegistry, mower: Mower) -> None:
    skip = "button.openmower_skip_area"
    assert hass.states.get(skip).state == STATE_UNAVAILABLE
    _enable(mower, "mower_logic:mowing/skip_area")
    await hass.async_block_till_done()
    assert hass.states.get(skip).state != STATE_UNAVAILABLE
    with patch.object(mower, "async_action", AsyncMock()) as action:
        await hass.services.async_call("button", "press", {ATTR_ENTITY_ID: skip}, blocking=True)
        action.assert_awaited_once_with("mower_logic:mowing/skip_area")
    # clearing an emergency stop from afar is opt-in
    reset = entity_registry.async_get("button.openmower_reset_emergency_stop")
    assert reset.disabled_by is er.RegistryEntryDisabler.INTEGRATION


async def test_events(hass: HomeAssistant, mower: Mower) -> None:
    event = "event.openmower_events"
    assert hass.states.get(event).state == "unknown"
    send(mower, "events/json", {"id": "1", "type": "STATE", "state": "MOWING"})
    await hass.async_block_till_done()
    assert hass.states.get(event).state == "unknown"

    send(mower, "events/json", {"id": "2", "type": "DOCKING", "reason": "Rain detected"})
    await hass.async_block_till_done()
    state = hass.states.get(event)
    assert state.attributes["event_type"] == "heading_home"
    assert state.attributes["reason"] == "rain"
    assert state.attributes["severity"] == "info"
    assert state.attributes["message"] == "Heading home: rain"


def _fired(hass: HomeAssistant) -> list[str]:
    """The event types the event entity fires from now on."""
    fired: list[str] = []

    @callback
    def changed(event: Event[EventStateChangedData]) -> None:
        if (new := event.data["new_state"]) and new.state not in ("unknown", STATE_UNAVAILABLE):
            fired.append(new.attributes["event_type"])

    async_track_state_change_event(hass, "event.openmower_events", changed)
    return fired


# what the simulator sent for start, pause, continue, home, two docking retries and docked
SIM_RUN = [
    {"type": "STATE", "state": "MOWING"},
    {"type": "AREA", "area_name": "Patch A"},
    {"type": "GPS", "available": True},
    {"type": "BLADES", "enabled": True},
    {"type": "BLADES", "enabled": False},
    {"type": "BLADES", "enabled": True},
    {"type": "NAVIGATION_ERROR"},
    {"type": "STATE", "state": "DOCKING"},
    {"type": "BLADES", "enabled": False},
    {"type": "GPS", "available": False},
    {"type": "DOCKING_RETRY", "reason": "dock_failed", "attempts": 1},
    {"type": "STATE", "state": "UNDOCKING"},
    {"type": "GPS", "available": True},
    {"type": "UNDOCKED"},
    {"type": "STATE", "state": "DOCKING"},
    {"type": "GPS", "available": False},
    {"type": "DOCKING_RETRY", "reason": "dock_failed", "attempts": 2},
    {"type": "STATE", "state": "UNDOCKING"},
    {"type": "GPS", "available": True},
    {"type": "UNDOCKED"},
    {"type": "STATE", "state": "DOCKING"},
    {"type": "DOCKED"},
    {"type": "STATE", "state": "IDLE"},
]


async def test_simulator_run(hass: HomeAssistant, mower: Mower) -> None:
    fired = _fired(hass)
    for i, event in enumerate(SIM_RUN):
        send(mower, "events/json", {"id": str(i), **event})
        await hass.async_block_till_done()
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=10))
    await hass.async_block_till_done()
    # the NAVIGATION_ERROR was sending it home, the UNDOCKED backing out for another try
    assert fired == ["area_started", "docking_retry", "docking_retry", "docked"]


async def test_navigation_error_on_its_own(hass: HomeAssistant, mower: Mower) -> None:
    fired = _fired(hass)
    send(mower, "events/json", {"id": "1", "type": "STATE", "state": "MOWING"})
    send(mower, "events/json", {"id": "2", "type": "NAVIGATION_ERROR"})
    await hass.async_block_till_done()
    assert fired == []
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=10))
    await hass.async_block_till_done()
    assert fired == ["navigation_error"]
    assert hass.states.get("event.openmower_events").attributes["severity"] == "error"


async def test_emergency_stop(hass: HomeAssistant, mower: Mower) -> None:
    fired = _fired(hass)
    send(mower, "robot_state/json", {**ROBOT_STATE, "emergency": 1})
    await hass.async_block_till_done()
    # it counts once it holds 10 s
    assert fired == []
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=11))
    await hass.async_block_till_done()
    state = hass.states.get("event.openmower_events")
    assert fired == ["emergency"]
    assert state.attributes["message"] == "Emergency stop"
    assert state.attributes["severity"] == "error"
    send(mower, "robot_state/json", {**ROBOT_STATE, "emergency": 0})
    await hass.async_block_till_done()
    assert fired == ["emergency", "emergency_cleared"]


async def test_short_emergency_stop_is_no_message(hass: HomeAssistant, mower: Mower) -> None:
    fired = _fired(hass)
    send(mower, "robot_state/json", {**ROBOT_STATE, "emergency": 1})
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=4))
    await hass.async_block_till_done()
    send(mower, "robot_state/json", {**ROBOT_STATE, "emergency": 0})
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=30))
    await hass.async_block_till_done()
    assert fired == []


async def test_mow_motor_spinup_is_the_emergency_reason(hass: HomeAssistant, mower: Mower) -> None:
    fired = _fired(hass)
    send(mower, "events/json", {"id": "1", "type": "STATE", "state": "MOWING"})
    send(mower, "events/json", {"id": "2", "type": "MOW_MOTOR_SPINUP_FAILED"})
    await hass.async_block_till_done()
    assert fired == []
    send(mower, "robot_state/json", {**ROBOT_STATE, "current_state": "MOWING", "emergency": 1})
    await hass.async_block_till_done()
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=11))
    await hass.async_block_till_done()
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=20))
    await hass.async_block_till_done()
    # one message, not two
    assert fired == ["emergency"]
    state = hass.states.get("event.openmower_events")
    assert state.attributes["reason"] == "mow_motor_spinup_failed"
    assert state.attributes["message"] == "Emergency stop: the mow motor didn't start"


async def test_mow_motor_spinup_on_its_own(hass: HomeAssistant, mower: Mower) -> None:
    fired = _fired(hass)
    send(mower, "events/json", {"id": "1", "type": "MOW_MOTOR_SPINUP_FAILED"})
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=16))
    await hass.async_block_till_done()
    assert fired == ["mow_motor_spinup_failed"]


async def test_docking_retry_is_on_the_way_home(hass: HomeAssistant, mower: Mower) -> None:
    for state in ("MOWING", "DOCKING", "UNDOCKING"):
        send(mower, "robot_state/json", {**ROBOT_STATE, "current_state": state})
    await hass.async_block_till_done()
    assert hass.states.get(MOWER).state == LawnMowerActivity.RETURNING
    for state in ("DOCKING", "IDLE", "UNDOCKING"):
        send(mower, "robot_state/json", {**ROBOT_STATE, "current_state": state})
    await hass.async_block_till_done()
    assert hass.states.get(MOWER).state == LawnMowerActivity.MOWING


async def test_event_before_the_first_robot_state(
    hass: HomeAssistant, entry: MockConfigEntry, no_connection: None
) -> None:
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    mower: Mower = entry.runtime_data.mower
    mower._connected = True
    send(mower, "events/json", {"id": "1", "type": "BOOTED"})
    await hass.async_block_till_done()
    assert hass.states.get(MOWER).state == STATE_UNAVAILABLE
    assert hass.states.get("event.openmower_events").attributes["event_type"] == "booted"


async def test_last_event_survives_a_restart(hass: HomeAssistant, entry: MockConfigEntry, no_connection: None) -> None:
    mock_restore_cache_with_extra_data(
        hass,
        [
            (
                State("event.openmower_events", "2026-10-05T10:00:00.000+00:00"),
                {
                    "last_event_type": "job_complete",
                    "last_event_attributes": {"severity": "info", "message": "All areas done"},
                },
            )
        ],
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    mower: Mower = entry.runtime_data.mower
    mower._connected = True
    send(mower, "robot_state/json", ROBOT_STATE)
    await hass.async_block_till_done()
    state = hass.states.get("event.openmower_events")
    assert state.state == "2026-10-05T10:00:00.000+00:00"
    assert state.attributes["event_type"] == "job_complete"
    assert state.attributes["message"] == "All areas done"


async def test_event_messages_follow_the_language(hass: HomeAssistant, mower: Mower) -> None:
    hass.config.language = "de"
    send(mower, "events/json", {"id": "1", "type": "DOCKING_FAILED", "reason": "dock_failed", "attempts": 3})
    await hass.async_block_till_done()
    state = hass.states.get("event.openmower_events")
    assert state.attributes["message"] == "Andocken nach 3 Versuchen fehlgeschlagen (kein Kontakt zur Ladestation)"


async def test_lost_connection(hass: HomeAssistant, mower: Mower) -> None:
    assert hass.states.get(MOWER).state == LawnMowerActivity.DOCKED
    mower._connected = False
    mower.check()
    await hass.async_block_till_done()
    assert hass.states.get(MOWER).state == STATE_UNAVAILABLE
    assert hass.states.get("sensor.openmower_battery").state == STATE_UNAVAILABLE
