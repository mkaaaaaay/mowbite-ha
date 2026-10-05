"""The card as a dashboard resource."""

from __future__ import annotations

from typing import Any

from pytest_homeassistant_custom_component.common import MockConfigEntry

from homeassistant.components.lovelace.const import LOVELACE_DATA
from homeassistant.core import HomeAssistant

from custom_components.mowbite import CARD_PATH
from custom_components.mowbite.mower import Mower


def _resources(hass: HomeAssistant) -> list[dict[str, Any]]:
    return [dict(item) for item in hass.data[LOVELACE_DATA].resources.async_items()]


async def test_added_once(hass: HomeAssistant, mower: Mower) -> None:
    mine = [r for r in _resources(hass) if r["url"].startswith(CARD_PATH)]
    assert len(mine) == 1
    assert mine[0]["type"] == "module"
    assert mine[0]["url"].startswith(f"{CARD_PATH}?v=")


async def test_old_versions_replaced(
    hass: HomeAssistant, hass_storage: dict[str, Any], entry: MockConfigEntry, no_connection: None
) -> None:
    hass_storage["lovelace_resources"] = {
        "version": 1,
        "minor_version": 1,
        "key": "lovelace_resources",
        "data": {
            "items": [
                {"id": "a", "type": "module", "url": f"{CARD_PATH}?v=old"},
                {"id": "b", "type": "module", "url": "/hacsfiles/other-card.js"},
                {"id": "c", "type": "module", "url": f"{CARD_PATH}?v=older"},
            ]
        },
    }
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    urls = [r["url"] for r in _resources(hass)]
    assert "/hacsfiles/other-card.js" in urls
    mine = [u for u in urls if u.startswith(CARD_PATH)]
    assert len(mine) == 1
    assert mine[0] not in (f"{CARD_PATH}?v=old", f"{CARD_PATH}?v=older")


async def test_removed_with_the_last_mower(hass: HomeAssistant, entry: MockConfigEntry, mower: Mower) -> None:
    assert any(r["url"].startswith(CARD_PATH) for r in _resources(hass))
    assert await hass.config_entries.async_remove(entry.entry_id)
    await hass.async_block_till_done()
    assert not any(r["url"].startswith(CARD_PATH) for r in _resources(hass))
