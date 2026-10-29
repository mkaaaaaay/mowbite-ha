"""What else the app tells: its counts, the parts' maintenance, the wifi and the schedule's starts."""

from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker

from custom_components.mowbite.app import (
    next_start,
    parse_schedule,
    parse_stats,
    part_hours_left,
    schedule_starts,
    stats_since,
)
from custom_components.mowbite.const import CONF_APP_URL
from custom_components.mowbite.mower import Mower

from .conftest import ROBOT_STATE, app_status, send

BERLIN = ZoneInfo("Europe/Berlin")
STATS = (
    "since 1000\n"
    "total 36000 5000.0 1200.0 12\n"
    "hour 7200 1800 300.0 50.0 1\n"
    "hour 10800 600 100.0 20.0 0\n"
    "maint blade 60 7200 0\n"
    "maint clean 5 0 0\n"
)


def test_stats() -> None:
    stats = parse_stats(STATS)
    assert stats["total"] == {"blade": 36000, "mowed": 5000, "driven": 1200, "runs": 12}
    # from the hour at 10800 on
    assert stats_since(stats, 10800) == {"blade": 600, "mowed": 100, "driven": 20, "runs": 0}
    # 10 blade hours in total, 2 of them before the blades were changed: 52 of 60 left, cleaning 5 hours ago due
    assert part_hours_left(stats, "blade") == 52
    assert part_hours_left(stats, "clean") == 0
    assert part_hours_left(stats, "wheels") is None
    assert parse_stats("nothing\n")["total"] is None


def test_schedule_starts() -> None:
    schedule = parse_schedule(
        "enabled 1\nplan 1,3,5 10:00\nplan 6 09:30 front,back end=11:00 dark=1\nplan 2 25:00\npause 2026-10-27 all\n"
    )
    # a time that isn't one is left out
    assert schedule["plans"] == 3 and len(schedule["starts"]) == 2
    assert schedule["starts"][1] == {"days": [6], "time": "09:30", "end": "11:00", "areas": ["front", "back"]}
    # monday 26.10. 08:00: paused up to and including tuesday, wednesday 28. at 10, friday 30. at 10, saturday 31.
    # 9:30 to 11
    now = datetime(2026, 10, 26, 8, 0, tzinfo=BERLIN)
    runs = schedule_starts(schedule, now, now + timedelta(days=6))
    assert [(r["start"].day, r["start"].hour, r["start"].minute) for r in runs] == [(28, 10, 0), (30, 10, 0), (31, 9, 30)]
    assert runs[2]["end"] == datetime(2026, 10, 31, 11, 0, tzinfo=BERLIN)
    assert next_start(schedule, now) == datetime(2026, 10, 28, 10, 0, tzinfo=BERLIN)
    assert next_start(schedule, datetime(2026, 10, 28, 10, 0, tzinfo=BERLIN)) == datetime(2026, 10, 30, 10, 0, tzinfo=BERLIN)
    # off: no starts
    assert next_start(parse_schedule("enabled 0\nplan 1 10:00\n"), now) is None


async def test_entities_off_at_first(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker, entry: MockConfigEntry, no_connection: None
) -> None:
    url = "http://openmower:8082"
    aioclient_mock.get(url + "/cgi-bin/settings", json={})
    app_status(
        aioclient_mock,
        url,
        {
            "/version.json": '{"version": "1.4.0"}',
            "/cgi-bin/system": "remote 0\nuptime 3600\nwifi_signal -68\n",
            "/cgi-bin/schedule": "enabled 1\nplan 1,2,3,4,5,6,7 10:00\n",
            "/cgi-bin/stats": STATS,
        },
    )
    entry.add_to_hass(hass)
    hass.config_entries.async_update_entry(entry, options={CONF_APP_URL: url})
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    registry = er.async_get(hass)
    for entity_id in (
        "sensor.openmower_wi_fi_signal",
        "sensor.openmower_next_scheduled_start",
        "sensor.openmower_blade_time_total",
        "sensor.openmower_mowing_distance_total",
        "sensor.openmower_distance_total",
        "sensor.openmower_mowing_runs_total",
        "sensor.openmower_blade_time_today",
        "sensor.openmower_mowing_runs_today",
        "sensor.openmower_blade_change_in",
        "sensor.openmower_cleaning_in",
        "binary_sensor.openmower_blade_change_due",
        "binary_sensor.openmower_cleaning_due",
        "calendar.openmower_mowing_calendar",
    ):
        item = registry.async_get(entity_id)
        assert item is not None, entity_id
        assert item.disabled_by is er.RegistryEntryDisabler.INTEGRATION, entity_id
        assert hass.states.get(entity_id) is None, entity_id

    # switched on they show what the app said
    for entity_id in (
        "sensor.openmower_blade_time_total",
        "sensor.openmower_cleaning_in",
        "binary_sensor.openmower_cleaning_due",
        "sensor.openmower_wi_fi_signal",
        "sensor.openmower_next_scheduled_start",
        "sensor.openmower_mowing_runs_total",
        "calendar.openmower_mowing_calendar",
    ):
        registry.async_update_entity(entity_id, disabled_by=None)
    await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    assert hass.states.get("sensor.openmower_blade_time_total").state == "10.0"
    assert hass.states.get("sensor.openmower_cleaning_in").state == "0.0"
    assert hass.states.get("binary_sensor.openmower_cleaning_due").state == "on"
    assert hass.states.get("sensor.openmower_wi_fi_signal").state == "-68.0"
    # a count without decimals
    assert hass.states.get("sensor.openmower_mowing_runs_total").state == "12"
    start = dt_util.parse_datetime(hass.states.get("sensor.openmower_next_scheduled_start").state)
    assert start is not None and start > dt_util.utcnow()
    calendar = hass.states.get("calendar.openmower_mowing_calendar")
    assert calendar.attributes["message"] == "Mowing"


async def test_no_accuracy_without_a_fix(hass: HomeAssistant, mower: Mower) -> None:
    assert hass.states.get("sensor.openmower_position_accuracy").state == "0.012"
    send(mower, "robot_state/json", {**ROBOT_STATE, "pose": {**ROBOT_STATE["pose"], "pos_accuracy": 999}})
    await hass.async_block_till_done()
    assert hass.states.get("sensor.openmower_position_accuracy").state == "unknown"


async def test_gps_fix(hass: HomeAssistant, mower: Mower) -> None:
    assert hass.states.get("binary_sensor.openmower_gps_fix").state == "on"
    send(mower, "robot_state/json", {**ROBOT_STATE, "pose": {**ROBOT_STATE["pose"], "pos_accuracy": 999}})
    await hass.async_block_till_done()
    assert hass.states.get("binary_sensor.openmower_gps_fix").state == "off"
