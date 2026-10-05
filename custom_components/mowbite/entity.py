"""The base all MowBite entities share."""

from __future__ import annotations

from homeassistant.core import callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity import Entity

from . import MowbiteConfigEntry
from .const import DOMAIN
from .mower import KEY_STATE, Mower


class MowbiteEntity(Entity):
    """One thing on the mower, updated whenever the mower says something about it."""

    _attr_has_entity_name = True
    _attr_should_poll = False
    # what this entity listens to on the mower
    _listen: tuple[str, ...] = (KEY_STATE,)

    def __init__(self, entry: MowbiteConfigEntry, key: str) -> None:
        self.mower: Mower = entry.runtime_data.mower
        self.snooze = entry.runtime_data.snooze
        self._attr_unique_id = f"{entry.entry_id}_{key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=entry.title,
            manufacturer="OpenMower",
        )

    @property
    def available(self) -> bool:
        return self.mower.available

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        for key in self._listen:
            self.async_on_remove(self.mower.add_listener(key, self._update))

    @callback
    def _update(self) -> None:
        self.async_write_ha_state()
