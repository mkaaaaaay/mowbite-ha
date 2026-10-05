"""Setting up a mower: where its MQTT broker is."""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry, ConfigFlow, ConfigFlowResult, OptionsFlowWithReload
from homeassistant.const import CONF_HOST, CONF_PASSWORD, CONF_PORT, CONF_USERNAME
from homeassistant.core import callback
from homeassistant.helpers.selector import (
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
)

from .app import CannotReachApp, async_fetch
from .const import (
    CONF_APP_URL,
    CONF_MAP,
    CONF_MOWER,
    CONF_PREFIX,
    CONF_SIZES,
    DEFAULT_NAME,
    DEFAULT_PORT,
    DOMAIN,
    MAP_MODES,
    MAX_BLADE,
    MOWER_MODELS,
    SIZE_KEYS,
)
from .mower import CannotConnect, InvalidAuth, NoMower, async_probe, normalize_prefix

_LOGGER = logging.getLogger(__name__)


def _schema(defaults: dict[str, Any]) -> vol.Schema:
    return vol.Schema(
        {
            vol.Required(CONF_HOST, default=defaults.get(CONF_HOST, vol.UNDEFINED)): TextSelector(),
            vol.Required(CONF_PORT, default=defaults.get(CONF_PORT, DEFAULT_PORT)): vol.All(
                NumberSelector(NumberSelectorConfig(min=1, max=65535, mode=NumberSelectorMode.BOX)),
                vol.Coerce(int),
            ),
            vol.Optional(CONF_USERNAME, description={"suggested_value": defaults.get(CONF_USERNAME)}): TextSelector(),
            vol.Optional(CONF_PASSWORD, description={"suggested_value": defaults.get(CONF_PASSWORD)}): TextSelector(
                TextSelectorConfig(type=TextSelectorType.PASSWORD)
            ),
            vol.Optional(CONF_PREFIX, description={"suggested_value": defaults.get(CONF_PREFIX)}): TextSelector(),
        }
    )


def _unique_id(data: dict[str, Any]) -> str:
    # one broker can carry several mowers behind different prefixes
    return f"{data[CONF_HOST].strip().lower()}:{data[CONF_PORT]}/{normalize_prefix(data.get(CONF_PREFIX))}"


class MowbiteConfigFlow(ConfigFlow, domain=DOMAIN):
    """Asks for the broker and checks that a mower answers there."""

    VERSION = 1

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> MowbiteOptionsFlow:
        return MowbiteOptionsFlow()

    async def _check(self, data: dict[str, Any]) -> dict[str, str]:
        try:
            await async_probe(
                data[CONF_HOST].strip(),
                data[CONF_PORT],
                data.get(CONF_USERNAME),
                data.get(CONF_PASSWORD),
                data.get(CONF_PREFIX, ""),
            )
        except InvalidAuth:
            return {"base": "invalid_auth"}
        except CannotConnect:
            return {"base": "cannot_connect"}
        except NoMower:
            return {"base": "no_mower"}
        except Exception:
            _LOGGER.exception("Unexpected error while checking the mower")
            return {"base": "unknown"}
        return {}

    @staticmethod
    def _clean(user_input: dict[str, Any]) -> dict[str, Any]:
        data = {**user_input, CONF_HOST: user_input[CONF_HOST].strip()}
        data[CONF_PREFIX] = normalize_prefix(user_input.get(CONF_PREFIX))
        return data

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            data = self._clean(user_input)
            await self.async_set_unique_id(_unique_id(data))
            self._abort_if_unique_id_configured()
            errors = await self._check(data)
            if not errors:
                return self.async_create_entry(title=DEFAULT_NAME, data=data)
        return self.async_show_form(step_id="user", data_schema=_schema(user_input or {}), errors=errors)

    async def async_step_reconfigure(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        entry = self._get_reconfigure_entry()
        errors: dict[str, str] = {}
        if user_input is not None:
            data = self._clean(user_input)
            # moving to another broker is what this is for, only not onto a mower that's already set up
            other = self.hass.config_entries.async_entry_for_domain_unique_id(DOMAIN, _unique_id(data))
            if other is not None and other.entry_id != entry.entry_id:
                return self.async_abort(reason="already_configured")
            errors = await self._check(data)
            if not errors:
                return self.async_update_reload_and_abort(entry, unique_id=_unique_id(data), data=data)
        return self.async_show_form(
            step_id="reconfigure", data_schema=_schema(user_input or dict(entry.data)), errors=errors
        )


class MowbiteOptionsFlow(OptionsFlowWithReload):
    """Where the MowBite app runs, when the cards show the map, and the mower's sizes for drawing it."""

    def __init__(self) -> None:
        self._options: dict[str, Any] = {}

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            url = (user_input.get(CONF_APP_URL) or "").strip().rstrip("/")
            if url and "://" not in url:
                url = f"http://{url}"
            if url:
                try:
                    await async_fetch(self.hass, url)
                except CannotReachApp:
                    errors["base"] = "cannot_reach_app"
            if not errors:
                mower = user_input.get(CONF_MOWER, "none")
                self._options = {CONF_APP_URL: url, CONF_MAP: user_input.get(CONF_MAP, "app"), CONF_MOWER: mower}
                if mower == "custom":
                    return await self.async_step_sizes()
                self._options[CONF_SIZES] = MOWER_MODELS.get(mower)
                return self.async_create_entry(data=self._options)
        current = user_input or self.config_entry.options
        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Optional(CONF_APP_URL, description={"suggested_value": current.get(CONF_APP_URL)}): TextSelector(),
                    vol.Optional(CONF_MAP, default=current.get(CONF_MAP, "app")): SelectSelector(
                        SelectSelectorConfig(options=MAP_MODES, mode=SelectSelectorMode.DROPDOWN, translation_key="map_mode")
                    ),
                    vol.Optional(CONF_MOWER, default=current.get(CONF_MOWER, "none")): SelectSelector(
                        SelectSelectorConfig(
                            options=["none", *MOWER_MODELS, "custom"],
                            mode=SelectSelectorMode.DROPDOWN,
                            translation_key="mower",
                        )
                    ),
                }
            ),
            errors=errors,
        )

    async def async_step_sizes(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """The mower's own sizes in cm, like under Mower sizes in the MowBite app, kept in metres like the app keeps them."""
        errors: dict[str, str] = {}
        if user_input is not None and SIZE_KEYS[0] in user_input:
            sizes = {key: round(float(user_input.get(key, 0)) / 100, 4) for key in SIZE_KEYS}
            if sizes["width"] <= 0 or sizes["front"] + sizes["rear"] <= 0:
                errors["base"] = "body_needed"
            elif not 0 <= sizes["blade"] <= MAX_BLADE:
                errors["blade"] = "blade_too_big"
            else:
                self._options[CONF_SIZES] = sizes
                return self.async_create_entry(data=self._options)
            current = user_input
        else:
            stored = self.config_entry.options.get(CONF_SIZES) or MOWER_MODELS["yf_nx"]
            current = {key: round(stored.get(key, 0) * 100, 1) for key in SIZE_KEYS}

        def cm(low: float, high: float) -> NumberSelector:
            return NumberSelector(
                NumberSelectorConfig(min=low, max=high, step=0.1, mode=NumberSelectorMode.BOX, unit_of_measurement="cm")
            )

        limits = {
            "width": cm(1, 200),
            "front": cm(-100, 200),
            "rear": cm(-100, 200),
            "blade": cm(0, MAX_BLADE * 100),
            "bladeAhead": cm(-100, 200),
            "bladeOffset": cm(-100, 100),
        }
        return self.async_show_form(
            step_id="sizes",
            data_schema=vol.Schema(
                {vol.Required(key, default=current.get(key, 0.0)): limits[key] for key in SIZE_KEYS}
            ),
            errors=errors,
        )
