"""What goes along with a question or a bug."""

from __future__ import annotations

import time

from homeassistant.const import CONF_HOST, CONF_PASSWORD, CONF_PORT, CONF_USERNAME
from homeassistant.core import HomeAssistant
from homeassistant.helpers import issue_registry as ir
from homeassistant.setup import async_setup_component
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.components.diagnostics import get_diagnostics_for_config_entry
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker
from pytest_homeassistant_custom_component.typing import ClientSessionGenerator

from custom_components.mowbite.const import CONF_APP_URL, CONF_PREFIX, DOMAIN
from custom_components.mowbite.mower import Mower

from .conftest import ACTIONS, ROBOT_STATE, app_status, send

MAP = {
    "areas": [
        {"id": "a", "properties": {"type": "mow"}, "outline": [{"x": 0, "y": 0}, {"x": 5, "y": 0}, {"x": 5, "y": 5}]},
        {"id": "b", "properties": {"type": "obstacle"}, "outline": [{"x": 1, "y": 1}, {"x": 2, "y": 1}, {"x": 2, "y": 2}]},
    ],
    "docking_stations": [{"position": {"x": 0, "y": 0}}],
}


async def test_diagnostics(hass: HomeAssistant, hass_client: ClientSessionGenerator, no_connection: None) -> None:
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="OpenMower",
        unique_id="mower.local:1883/",
        data={CONF_HOST: "mower.local", CONF_PORT: 1883, CONF_PREFIX: "", CONF_USERNAME: "me", CONF_PASSWORD: "secret"},
    )
    entry.add_to_hass(hass)
    assert await async_setup_component(hass, "diagnostics", {})
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    mower: Mower = entry.runtime_data.mower
    mower._connected = True
    send(mower, "actions/json", ACTIONS)
    send(mower, "robot_state/json", ROBOT_STATE)
    send(mower, "map/json", MAP)
    send(mower, "params/json", {"/ll/services/gps/datum_lat": 52.25, "/ll/services/gps/datum_long": 10.56})
    await hass.async_block_till_done()

    diagnostics = await get_diagnostics_for_config_entry(hass, hass_client, entry)
    assert diagnostics["entry"]["data"][CONF_USERNAME] == "**REDACTED**"
    assert diagnostics["entry"]["data"][CONF_PASSWORD] == "**REDACTED**"
    assert diagnostics["mower"]["available"] is True
    assert diagnostics["mower"]["robot_state"]["current_state"] == ROBOT_STATE["current_state"]
    assert diagnostics["mower"]["map"] == {"areas": {"mow": 1, "obstacle": 1}, "docking_stations": 1}
    # where the garden is stays home
    assert diagnostics["mower"]["datum"] is True
    text = str(diagnostics)
    for leak in ("secret", "52.25", "10.56"):
        assert leak not in text
    assert diagnostics["app"]["address_set"] is False


async def test_repair_when_mowbite_does_not_answer(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker, entry: MockConfigEntry, no_connection: None
) -> None:
    url = "http://openmower:8080"
    aioclient_mock.get(url + "/cgi-bin/settings", status=404)
    app_status(aioclient_mock, url)
    entry.add_to_hass(hass)
    hass.config_entries.async_update_entry(entry, options={CONF_APP_URL: url})
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    mower: Mower = entry.runtime_data.mower
    mower._connected = True
    send(mower, "robot_state/json", ROBOT_STATE)
    await hass.async_block_till_done()
    app = entry.runtime_data.app
    issues = ir.async_get(hass)
    issue_id = f"app_unreachable_{entry.entry_id}"

    # not answering for a moment is no wrong address
    await app.async_refresh()
    assert issues.async_get_issue(DOMAIN, issue_id) is None
    # for ten minutes while the mower answers: a repair
    app.failing_since = time.monotonic() - 601
    await app.async_refresh()
    issue = issues.async_get_issue(DOMAIN, issue_id)
    assert issue is not None and issue.translation_placeholders == {"name": "OpenMower", "url": url}

    # answering again, the repair goes
    aioclient_mock.clear_requests()
    aioclient_mock.get(url + "/cgi-bin/settings", json={})
    await app.async_refresh()
    assert issues.async_get_issue(DOMAIN, issue_id) is None


async def test_no_repair_while_the_mower_is_off(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker, entry: MockConfigEntry, no_connection: None
) -> None:
    url = "http://openmower:8082"
    aioclient_mock.get(url + "/cgi-bin/settings", status=404)
    app_status(aioclient_mock, url)
    entry.add_to_hass(hass)
    hass.config_entries.async_update_entry(entry, options={CONF_APP_URL: url})
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    app = entry.runtime_data.app
    app.failing_since = time.monotonic() - 601
    await app.async_refresh()
    assert ir.async_get(hass).async_get_issue(DOMAIN, f"app_unreachable_{entry.entry_id}") is None
