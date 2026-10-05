"""Shared fixtures."""

from __future__ import annotations

from collections.abc import Generator
import json
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from homeassistant.const import CONF_HOST, CONF_PORT
from homeassistant.core import HomeAssistant

from custom_components.mowbite.const import CONF_PREFIX, DOMAIN
from custom_components.mowbite.mower import Mower

# what the simulator sent on robot_state/json
ROBOT_STATE: dict[str, Any] = {
    "battery_percentage": 0.83,
    "gps_percentage": 0.97,
    "current_action_progress": 0.0,
    "current_state": "IDLE",
    "current_sub_state": "",
    "current_area": -1,
    "current_path": -1,
    "current_path_index": -1,
    "emergency": 0,
    "is_charging": 1,
    "rain_detected": 0,
    "pose": {"x": -3.47, "y": 2.09, "heading": 52.3, "pos_accuracy": 0.012, "heading_accuracy": 0.01, "heading_valid": 1},
}

ACTIONS = [
    {"action_id": "mower_logic/reset_emergency", "action_name": "Reset Emergency", "enabled": 1},
    {"action_id": "mower_logic:docking/abort_docking", "action_name": "Stop Docking", "enabled": 0},
    {"action_id": "mower_logic:idle/start_mowing", "action_name": "Start Mowing", "enabled": 1},
    {"action_id": "mower_logic:mowing/pause", "action_name": "Pause", "enabled": 0},
    {"action_id": "mower_logic:mowing/continue", "action_name": "Continue", "enabled": 0},
    {"action_id": "mower_logic:mowing/abort_mowing", "action_name": "Stop", "enabled": 0},
    {"action_id": "mower_logic:mowing/skip_area", "action_name": "Skip Area", "enabled": 0},
]


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations: None) -> None:
    """Let Home Assistant load the integration from custom_components."""


@pytest.fixture
def entry() -> MockConfigEntry:
    return MockConfigEntry(
        domain=DOMAIN,
        title="OpenMower",
        unique_id="mower.local:1883/",
        data={CONF_HOST: "mower.local", CONF_PORT: 1883, CONF_PREFIX: ""},
    )


@pytest.fixture
def no_connection() -> Generator[None]:
    """The background task doesn't connect anywhere, the tests feed messages themselves."""
    with patch.object(Mower, "run", AsyncMock(return_value=None)):
        yield


@pytest.fixture
async def mower(hass: HomeAssistant, entry: MockConfigEntry, no_connection: None) -> Mower:
    """A set up mower that is connected and has said hello."""
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    mower: Mower = entry.runtime_data.mower
    mower._connected = True
    send(mower, "actions/json", ACTIONS)
    send(mower, "robot_state/json", ROBOT_STATE)
    await hass.async_block_till_done()
    return mower


def send(mower: Mower, topic: str, payload: Any) -> None:
    """A message as the broker would deliver it."""
    if not isinstance(payload, (str, bytes)):
        payload = json.dumps(payload)
    mower.handle(topic, payload.encode() if isinstance(payload, str) else payload)
