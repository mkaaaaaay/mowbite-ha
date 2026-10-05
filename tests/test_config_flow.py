"""Setting a mower up."""

from __future__ import annotations

from collections.abc import Generator
from unittest.mock import AsyncMock, patch

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from homeassistant.config_entries import SOURCE_USER
from homeassistant.const import CONF_HOST, CONF_PASSWORD, CONF_PORT, CONF_USERNAME
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType

from custom_components.mowbite.const import CONF_PREFIX, DOMAIN
from custom_components.mowbite.mower import CannotConnect, InvalidAuth, NoMower

INPUT = {CONF_HOST: " 192.168.2.50 ", CONF_PORT: 1883, CONF_USERNAME: "om", CONF_PASSWORD: "secret", CONF_PREFIX: "openmower"}


@pytest.fixture
def probe() -> Generator[AsyncMock]:
    with patch("custom_components.mowbite.config_flow.async_probe", AsyncMock()) as probe:
        yield probe


@pytest.fixture(autouse=True)
def no_setup() -> Generator[None]:
    with patch("custom_components.mowbite.async_setup_entry", AsyncMock(return_value=True)):
        yield


async def test_user(hass: HomeAssistant, probe: AsyncMock) -> None:
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    assert result["type"] is FlowResultType.FORM

    result = await hass.config_entries.flow.async_configure(result["flow_id"], INPUT)
    await hass.async_block_till_done()
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "OpenMower"
    assert result["data"] == {
        CONF_HOST: "192.168.2.50",
        CONF_PORT: 1883,
        CONF_USERNAME: "om",
        CONF_PASSWORD: "secret",
        CONF_PREFIX: "openmower/",
    }
    assert result["result"].unique_id == "192.168.2.50:1883/openmower/"
    probe.assert_awaited_once_with("192.168.2.50", 1883, "om", "secret", "openmower/")


@pytest.mark.parametrize(
    ("error", "key"),
    [(CannotConnect, "cannot_connect"), (InvalidAuth, "invalid_auth"), (NoMower, "no_mower"), (ValueError, "unknown")],
)
async def test_user_errors(hass: HomeAssistant, probe: AsyncMock, error: type[Exception], key: str) -> None:
    probe.side_effect = error
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    result = await hass.config_entries.flow.async_configure(result["flow_id"], INPUT)
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": key}

    probe.side_effect = None
    result = await hass.config_entries.flow.async_configure(result["flow_id"], INPUT)
    await hass.async_block_till_done()
    assert result["type"] is FlowResultType.CREATE_ENTRY


async def test_already_configured(hass: HomeAssistant, probe: AsyncMock) -> None:
    MockConfigEntry(domain=DOMAIN, unique_id="192.168.2.50:1883/openmower/").add_to_hass(hass)
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {**INPUT, CONF_PREFIX: "openmower/"})
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"
    probe.assert_not_awaited()


async def test_reconfigure(hass: HomeAssistant, probe: AsyncMock) -> None:
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id="old:1883/",
        data={CONF_HOST: "old", CONF_PORT: 1883, CONF_PREFIX: ""},
    )
    entry.add_to_hass(hass)
    result = await entry.start_reconfigure_flow(hass)
    assert result["type"] is FlowResultType.FORM

    result = await hass.config_entries.flow.async_configure(result["flow_id"], {CONF_HOST: "new", CONF_PORT: 1884})
    # the reload runs in the background, it has to be done before the patched setup goes away
    await hass.async_block_till_done()
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reconfigure_successful"
    assert entry.data == {CONF_HOST: "new", CONF_PORT: 1884, CONF_PREFIX: ""}
    assert entry.unique_id == "new:1884/"


async def test_reconfigure_onto_another_mower(hass: HomeAssistant, probe: AsyncMock) -> None:
    MockConfigEntry(domain=DOMAIN, unique_id="other:1883/").add_to_hass(hass)
    entry = MockConfigEntry(domain=DOMAIN, unique_id="old:1883/", data={CONF_HOST: "old", CONF_PORT: 1883})
    entry.add_to_hass(hass)
    result = await entry.start_reconfigure_flow(hass)
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {CONF_HOST: "other", CONF_PORT: 1883})
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"
