"""The card as a dashboard resource."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from pytest_homeassistant_custom_component.common import MockConfigEntry

from homeassistant.components.lovelace.const import LOVELACE_DATA
from homeassistant.core import HomeAssistant

from custom_components.mowbite import BLUEPRINT_FILE, BLUEPRINT_SOURCE, CARD_PATH, install_blueprint
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


def test_the_app_files_come_along() -> None:
    """The card's pictures and dashboard logic, built from MowBite (scripts/build-art.mjs), go with the integration."""
    from pathlib import Path

    frontend = Path(__file__).parent.parent / "custom_components" / "mowbite" / "frontend"
    art = (frontend / "mowbite-art.js").read_text()
    app = (frontend / "mowbite-app.js").read_text()
    assert "export const ART_API = 3;" in art and "export function gardenAreas" in art
    assert "export const APP_API = 1;" in app and "export const DASHBOARD_CSS" in app
    # drawing only, nothing loaded from elsewhere
    assert "fetch(" not in art.split("// what the card uses")[0].split("const transportMowers")[0]


def test_blueprint_comes_with_the_integration() -> None:
    # the one in the integration is the one the README links to
    shown = Path(__file__).parent.parent / "blueprints/automation/mowbite/notify.yaml"
    assert BLUEPRINT_FILE.read_bytes() == shown.read_bytes()
    assert BLUEPRINT_SOURCE in BLUEPRINT_FILE.read_text(encoding="utf-8")


def test_install_blueprint(tmp_path: Path) -> None:
    folder = tmp_path / "automation"
    # not before Home Assistant made the folder (it fills a new one with its examples)
    install_blueprint(folder)
    assert not folder.exists()

    folder.mkdir()
    install_blueprint(folder)
    target = folder / "mowbite" / "notify.yaml"
    assert target.read_bytes() == BLUEPRINT_FILE.read_bytes()

    # one changed by hand stays as it is
    target.write_text("changed", encoding="utf-8")
    install_blueprint(folder)
    assert target.read_text(encoding="utf-8") == "changed"


def test_no_second_blueprint(tmp_path: Path) -> None:
    # imported by hand from GitHub it's under the user's name, not twice
    imported = tmp_path / "mkaaaaaay" / "notify.yaml"
    imported.parent.mkdir()
    imported.write_bytes(BLUEPRINT_FILE.read_bytes())
    install_blueprint(tmp_path)
    assert not (tmp_path / "mowbite").exists()
