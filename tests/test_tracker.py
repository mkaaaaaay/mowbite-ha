"""The mower as a gps tracker."""

from __future__ import annotations

from datetime import timedelta

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import async_fire_time_changed

from custom_components.mowbite.geo import map_to_latlon, to_utm, utm_zone
from custom_components.mowbite.mower import Mower

from .conftest import ROBOT_STATE, send

TRACKER = "device_tracker.openmower"
DATUM = {"/ll/services/gps/datum_lat": 52.254119661740596, "/ll/services/gps/datum_long": 10.56}


def test_map_to_latlon_and_back() -> None:
    datum = {"lat": 52.254119661740596, "lon": 10.56}
    assert map_to_latlon(datum, 0, 0) == pytest.approx((datum["lat"], datum["lon"]), abs=1e-8)
    lat, lon = map_to_latlon(datum, 10, 20)
    zone = utm_zone(datum["lat"], datum["lon"])
    e0, n0 = to_utm(datum["lat"], datum["lon"], zone)
    e, n = to_utm(lat, lon, zone)
    # metres east and north of the datum, to the millimetre
    assert (e - e0, n - n0) == pytest.approx((10, 20), abs=0.001)
    # the southern hemisphere too
    lat, lon = map_to_latlon({"lat": -33.9, "lon": 151.2}, 0, 0)
    assert (lat, lon) == pytest.approx((-33.9, 151.2), abs=1e-7)


async def test_no_tracker_without_the_datum(hass: HomeAssistant, mower: Mower) -> None:
    assert hass.states.get(TRACKER) is None


async def test_tracker(hass: HomeAssistant, mower: Mower, freezer) -> None:
    # robot_state again under the frozen clock, else the mower counts as gone quiet
    send(mower, "robot_state/json", ROBOT_STATE)
    send(mower, "params/json", DATUM)
    # the tracker comes with the datum, the positions after it
    await hass.async_block_till_done()
    send(mower, "position/json", {"x": 0, "y": 0, "heading": 0, "attributes": {"job_id": "j", "blades": False}})
    await hass.async_block_till_done()
    state = hass.states.get(TRACKER)
    assert state.attributes["source_type"] == "gps"
    assert state.attributes["latitude"] == pytest.approx(52.254119661740596, abs=1e-7)
    assert state.attributes["longitude"] == pytest.approx(10.56, abs=1e-7)
    assert state.attributes["gps_accuracy"] == 0.01

    # 20 m north: written at once after a while, not with every pose in between
    send(mower, "position/json", {"x": 0, "y": 20, "heading": 0, "attributes": {"job_id": "j", "blades": True}})
    await hass.async_block_till_done()
    assert hass.states.get(TRACKER).attributes["latitude"] == pytest.approx(52.254119661740596, abs=1e-7)
    freezer.tick(timedelta(seconds=11))
    async_fire_time_changed(hass, dt_util.utcnow())
    await hass.async_block_till_done()
    lat = hass.states.get(TRACKER).attributes["latitude"]
    assert lat - 52.254119661740596 == pytest.approx(20 / 111260, rel=0.01)

    # without a gps fix the pose is only a guess from the wheels: it stays where it last had one
    lost = {**ROBOT_STATE, "pose": {**ROBOT_STATE["pose"], "pos_accuracy": 999}}
    send(mower, "robot_state/json", lost)
    send(mower, "position/json", {"x": 0, "y": 100, "heading": 0, "attributes": {"job_id": "j", "blades": True}})
    freezer.tick(timedelta(seconds=11))
    async_fire_time_changed(hass, dt_util.utcnow())
    await hass.async_block_till_done()
    state = hass.states.get(TRACKER)
    assert state.attributes["latitude"] == lat
    assert state.attributes["gps_accuracy"] == 0.01

    # and moves on with the fix back
    fixed = {**ROBOT_STATE, "pose": {**ROBOT_STATE["pose"], "pos_accuracy": 0.5}}
    send(mower, "robot_state/json", fixed)
    freezer.tick(timedelta(seconds=11))
    async_fire_time_changed(hass, dt_util.utcnow())
    await hass.async_block_till_done()
    state = hass.states.get(TRACKER)
    assert state.attributes["latitude"] - 52.254119661740596 == pytest.approx(100 / 111260, rel=0.01)
    assert state.attributes["gps_accuracy"] == 0.5
