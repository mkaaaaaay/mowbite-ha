"""Pausing notifications."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from freezegun.api import FrozenDateTimeFactory
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry, async_fire_time_changed

from homeassistant.const import ATTR_ENTITY_ID, STATE_OFF, STATE_ON, STATE_UNKNOWN
from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util

from custom_components.mowbite.mower import Mower
from custom_components.mowbite.snooze import next_morning

from .conftest import send

SWITCH = "switch.openmower_notifications"
UNTIL = "sensor.openmower_notifications_paused_until"
EVENT = "event.openmower_events"


def test_next_morning() -> None:
    tz = dt_util.get_default_time_zone()
    assert next_morning(datetime(2026, 10, 5, 13, 0, tzinfo=tz)) == datetime(2026, 10, 6, 7, 0, tzinfo=tz)
    assert next_morning(datetime(2026, 10, 5, 2, 30, tzinfo=tz)) == datetime(2026, 10, 5, 7, 0, tzinfo=tz)
    assert next_morning(datetime(2026, 10, 5, 7, 0, tzinfo=tz)) == datetime(2026, 10, 6, 7, 0, tzinfo=tz)


async def _press(hass: HomeAssistant, button: str) -> None:
    await hass.services.async_call("button", "press", {ATTR_ENTITY_ID: button}, blocking=True)


def _event(mower: Mower, event_id: str) -> None:
    send(mower, "events/json", {"id": event_id, "type": "DOCKING_FAILED", "reason": "dock_failed", "attempts": 3})


async def test_switch(hass: HomeAssistant, mower: Mower) -> None:
    assert hass.states.get(SWITCH).state == STATE_ON
    _event(mower, "1")
    await hass.async_block_till_done()
    assert hass.states.get(EVENT).attributes["snoozed"] is False

    await hass.services.async_call("switch", "turn_off", {ATTR_ENTITY_ID: SWITCH}, blocking=True)
    assert hass.states.get(SWITCH).state == STATE_OFF
    # off without an end
    assert hass.states.get(UNTIL).state == STATE_UNKNOWN
    _event(mower, "2")
    await hass.async_block_till_done()
    assert hass.states.get(EVENT).attributes["snoozed"] is True

    await hass.services.async_call("switch", "turn_on", {ATTR_ENTITY_ID: SWITCH}, blocking=True)
    assert hass.states.get(SWITCH).state == STATE_ON


async def test_snooze_ends_by_itself(hass: HomeAssistant, freezer: FrozenDateTimeFactory, mower: Mower) -> None:
    freezer.move_to("2026-10-05 11:00:00+00:00")
    await _press(hass, "button.openmower_pause_notifications_for_1_h")
    assert hass.states.get(SWITCH).state == STATE_OFF
    assert hass.states.get(UNTIL).state == "2026-10-05T12:00:00+00:00"

    freezer.tick(timedelta(minutes=59))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    assert hass.states.get(SWITCH).state == STATE_OFF

    freezer.tick(timedelta(minutes=2))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    assert hass.states.get(SWITCH).state == STATE_ON
    assert hass.states.get(UNTIL).state == STATE_UNKNOWN


async def test_buttons_in_the_notification(hass: HomeAssistant, entry: MockConfigEntry, mower: Mower) -> None:
    _event(mower, "1")
    await hass.async_block_till_done()
    actions: list[dict[str, Any]] = hass.states.get(EVENT).attributes["notification_actions"]
    assert actions == [
        {"action": f"MOWBITE_SNOOZE_HOUR_{entry.entry_id}", "title": "Snooze 1 h"},
        {"action": f"MOWBITE_SNOOZE_MORNING_{entry.entry_id}", "title": "Until tomorrow morning"},
    ]

    # another mower's button does nothing here
    hass.bus.async_fire("mobile_app_notification_action", {"action": "MOWBITE_SNOOZE_HOUR_someoneelse"})
    await hass.async_block_till_done()
    assert hass.states.get(SWITCH).state == STATE_ON

    hass.bus.async_fire("mobile_app_notification_action", {"action": actions[1]["action"]})
    await hass.async_block_till_done()
    assert hass.states.get(SWITCH).state == STATE_OFF
    until = dt_util.parse_datetime(hass.states.get(UNTIL).state)
    assert dt_util.as_local(until).hour == 7
    assert until > dt_util.utcnow()


async def test_kept_over_a_restart(
    hass: HomeAssistant, hass_storage: dict[str, Any], entry: MockConfigEntry, no_connection: None
) -> None:
    until = dt_util.utcnow() + timedelta(hours=2)
    entry.add_to_hass(hass)
    hass_storage[f"mowbite.{entry.entry_id}.snooze"] = {
        "version": 1,
        "minor_version": 1,
        "key": f"mowbite.{entry.entry_id}.snooze",
        "data": {"off": False, "until": until.isoformat()},
    }
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert hass.states.get(SWITCH).state == STATE_OFF
    assert entry.runtime_data.snooze.until == until
    # a timestamp sensor shows whole seconds
    assert dt_util.parse_datetime(hass.states.get(UNTIL).state) == until.replace(microsecond=0)


@pytest.mark.parametrize(
    ("stored", "switch"),
    [
        ({"off": True, "until": None}, STATE_OFF),
        # the snooze ended while Home Assistant was down
        ({"off": False, "until": "2020-01-01T00:00:00+00:00"}, STATE_ON),
    ],
)
async def test_stored_state(
    hass: HomeAssistant,
    hass_storage: dict[str, Any],
    entry: MockConfigEntry,
    no_connection: None,
    stored: dict,
    switch: str,
) -> None:
    entry.add_to_hass(hass)
    hass_storage[f"mowbite.{entry.entry_id}.snooze"] = {
        "version": 1,
        "minor_version": 1,
        "key": f"mowbite.{entry.entry_id}.snooze",
        "data": stored,
    }
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert hass.states.get(SWITCH).state == switch
    assert hass.states.get(UNTIL).state == STATE_UNKNOWN


async def test_saved(
    hass: HomeAssistant,
    hass_storage: dict[str, Any],
    freezer: FrozenDateTimeFactory,
    entry: MockConfigEntry,
    mower: Mower,
) -> None:
    await hass.services.async_call("switch", "turn_off", {ATTR_ENTITY_ID: SWITCH}, blocking=True)
    freezer.tick(timedelta(seconds=5))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    assert hass_storage[f"mowbite.{entry.entry_id}.snooze"]["data"] == {"off": True, "until": None}
