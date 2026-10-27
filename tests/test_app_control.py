"""What can be changed in the MowBite app from here: the parts seen to and when they're due, some of the schedule."""

from __future__ import annotations

import re

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker

from homeassistant.const import ATTR_ENTITY_ID
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import entity_registry as er
from homeassistant.util import dt as dt_util

from custom_components.mowbite.const import CONF_APP_URL

from .conftest import app_status

URL = "http://openmower:8082"
SCHEDULE = "enabled 0\nminbattery 60\nskiprain 1\nskipforecast 0\ntz CET-1\nplan 1,3,5 10:00 front\n"
STATS = "since 1000\ntotal 36000 5000.0 1200.0 12\nmaint blade 60 7200 0\nmaint clean 5 0 0\n"
ENTITIES = (
    "button.openmower_blades_changed",
    "button.openmower_cleaned",
    "button.openmower_skip_today",
    "button.openmower_end_pause",
    "switch.openmower_mow_on_schedule",
    "switch.openmower_skip_when_it_rains",
    "switch.openmower_skip_when_rain_is_forecast",
    "number.openmower_blade_change_every",
    "number.openmower_cleaning_every",
    "number.openmower_start_from_battery_level",
)


def posted(aioclient_mock: AiohttpClientMocker, path: str) -> list[str]:
    """The bodies sent to a path (with its query) of the app."""
    return [
        (call[2] or b"").decode()
        for call in aioclient_mock.mock_calls
        if call[0] == "POST" and str(call[1]).endswith(path)
    ]


@pytest.fixture
async def app(hass: HomeAssistant, aioclient_mock: AiohttpClientMocker, entry: MockConfigEntry, no_connection: None) -> None:
    aioclient_mock.get(URL + "/cgi-bin/settings", json={})
    app_status(
        aioclient_mock,
        URL,
        {"/version.json": '{"version": "1.4.0"}', "/cgi-bin/schedule": SCHEDULE, "/cgi-bin/stats": STATS},
    )
    entry.add_to_hass(hass)
    hass.config_entries.async_update_entry(entry, options={CONF_APP_URL: URL})
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    registry = er.async_get(hass)
    for entity_id in ENTITIES:
        item = registry.async_get(entity_id)
        assert item is not None and item.disabled_by is er.RegistryEntryDisabler.INTEGRATION, entity_id
        registry.async_update_entity(entity_id, disabled_by=None)
    await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()


async def test_states(hass: HomeAssistant, app: None) -> None:
    assert hass.states.get("switch.openmower_mow_on_schedule").state == "off"
    assert hass.states.get("switch.openmower_skip_when_it_rains").state == "on"
    assert hass.states.get("switch.openmower_skip_when_rain_is_forecast").state == "off"
    assert hass.states.get("number.openmower_start_from_battery_level").state == "60"
    assert hass.states.get("number.openmower_blade_change_every").state == "60"
    assert hass.states.get("number.openmower_cleaning_every").state == "5"


async def test_parts(hass: HomeAssistant, aioclient_mock: AiohttpClientMocker, app: None) -> None:
    aioclient_mock.post(re.compile(re.escape(URL + "/cgi-bin/stats?done=blade") + "$"), text=STATS.replace("7200 0", "36000 2000"))
    aioclient_mock.post(re.compile(re.escape(URL + "/cgi-bin/stats?due=clean&h=40") + "$"), text=STATS.replace("clean 5", "clean 40"))
    await hass.services.async_call("button", "press", {ATTR_ENTITY_ID: "button.openmower_blades_changed"}, blocking=True)
    assert posted(aioclient_mock, "/cgi-bin/stats?done=blade") == [""]
    await hass.services.async_call(
        "number", "set_value", {ATTR_ENTITY_ID: "number.openmower_cleaning_every", "value": 40}, blocking=True
    )
    assert posted(aioclient_mock, "/cgi-bin/stats?due=clean&h=40") == [""]
    # what the app answered shows right away
    assert hass.states.get("number.openmower_cleaning_every").state == "40"


async def test_schedule_lines(hass: HomeAssistant, aioclient_mock: AiohttpClientMocker, app: None) -> None:
    aioclient_mock.post(re.compile(re.escape(URL + "/cgi-bin/schedule") + "$"), text=SCHEDULE.replace("enabled 0", "enabled 1"))
    await hass.services.async_call("switch", "turn_on", {ATTR_ENTITY_ID: "switch.openmower_mow_on_schedule"}, blocking=True)
    body = posted(aioclient_mock, "/cgi-bin/schedule")[-1]
    # only that line changed, the plans and everything else as they were
    assert sorted(body.splitlines()) == sorted(SCHEDULE.replace("enabled 0", "enabled 1").splitlines())
    assert hass.states.get("switch.openmower_mow_on_schedule").state == "on"

    await hass.services.async_call("button", "press", {ATTR_ENTITY_ID: "button.openmower_skip_today"}, blocking=True)
    body = posted(aioclient_mock, "/cgi-bin/schedule")[-1]
    assert f"pause {dt_util.now().date().isoformat()} all" in body.splitlines()
    assert "plan 1,3,5 10:00 front" in body.splitlines()


async def test_refused(hass: HomeAssistant, aioclient_mock: AiohttpClientMocker, app: None) -> None:
    aioclient_mock.post(re.compile(re.escape(URL + "/cgi-bin/stats?due=blade&h=80") + "$"), status=400)
    with pytest.raises(HomeAssistantError):
        await hass.services.async_call(
            "number", "set_value", {ATTR_ENTITY_ID: "number.openmower_blade_change_every", "value": 80}, blocking=True
        )
