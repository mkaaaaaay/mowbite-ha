"""Where on earth a point of the mower's map is.

OpenMower's map frame is UTM (LLtoUTM from robot_localization, like MowBite's lib/utm.ts): x and y are the easting and
northing less the datum's, in the datum's zone. So a map point goes back to latitude and longitude by adding the datum's
easting and northing and turning that back from UTM.
"""

from __future__ import annotations

import math

A = 6378137.0
F = 1 / 298.257223563
E2 = F * (2 - F)
EP2 = E2 / (1 - E2)
K0 = 0.9996


def utm_zone(lat: float, lon: float) -> int:
    # the two irregular areas around norway and svalbard
    if 56 <= lat < 64 and 3 <= lon < 12:
        return 32
    if 72 <= lat < 84:
        for start, end, zone in ((0, 9, 31), (9, 21, 33), (21, 33, 35), (33, 42, 37)):
            if start <= lon < end:
                return zone
    return math.floor((lon + 180) / 6) + 1


def _central(zone: int) -> float:
    return math.radians((zone - 1) * 6 - 180 + 3)


def to_utm(lat: float, lon: float, zone: int) -> tuple[float, float]:
    """Easting and northing in the zone, as MowBite's toUtm."""
    phi = math.radians(lat)
    lam = math.radians(lon)
    sin, cos, tan = math.sin(phi), math.cos(phi), math.tan(phi)
    n_ = A / math.sqrt(1 - E2 * sin * sin)
    t = tan * tan
    c = EP2 * cos * cos
    a = cos * (lam - _central(zone))
    e4, e6 = E2 * E2, E2**3
    m = A * (
        (1 - E2 / 4 - 3 * e4 / 64 - 5 * e6 / 256) * phi
        - (3 * E2 / 8 + 3 * e4 / 32 + 45 * e6 / 1024) * math.sin(2 * phi)
        + (15 * e4 / 256 + 45 * e6 / 1024) * math.sin(4 * phi)
        - (35 * e6 / 3072) * math.sin(6 * phi)
    )
    east = K0 * n_ * (a + (1 - t + c) * a**3 / 6 + (5 - 18 * t + t * t + 72 * c - 58 * EP2) * a**5 / 120) + 500000
    north = K0 * (
        m
        + n_
        * tan
        * (a * a / 2 + (5 - t + 9 * c + 4 * c * c) * a**4 / 24 + (61 - 58 * t + t * t + 600 * c - 330 * EP2) * a**6 / 720)
    )
    if lat < 0:
        north += 10000000
    return east, north


def from_utm(east: float, north: float, zone: int, southern: bool) -> tuple[float, float]:
    """Latitude and longitude of a point in the zone (the inverse of to_utm, Snyder's series)."""
    x = east - 500000
    y = north - 10000000 if southern else north
    m = y / K0
    mu = m / (A * (1 - E2 / 4 - 3 * E2**2 / 64 - 5 * E2**3 / 256))
    e1 = (1 - math.sqrt(1 - E2)) / (1 + math.sqrt(1 - E2))
    phi1 = (
        mu
        + (3 * e1 / 2 - 27 * e1**3 / 32) * math.sin(2 * mu)
        + (21 * e1**2 / 16 - 55 * e1**4 / 32) * math.sin(4 * mu)
        + (151 * e1**3 / 96) * math.sin(6 * mu)
        + (1097 * e1**4 / 512) * math.sin(8 * mu)
    )
    sin, cos, tan = math.sin(phi1), math.cos(phi1), math.tan(phi1)
    n1 = A / math.sqrt(1 - E2 * sin * sin)
    t1 = tan * tan
    c1 = EP2 * cos * cos
    r1 = A * (1 - E2) / (1 - E2 * sin * sin) ** 1.5
    d = x / (n1 * K0)
    lat = phi1 - (n1 * tan / r1) * (
        d * d / 2
        - (5 + 3 * t1 + 10 * c1 - 4 * c1 * c1 - 9 * EP2) * d**4 / 24
        + (61 + 90 * t1 + 298 * c1 + 45 * t1 * t1 - 252 * EP2 - 3 * c1 * c1) * d**6 / 720
    )
    lon = _central(zone) + (
        d - (1 + 2 * t1 + c1) * d**3 / 6 + (5 - 2 * c1 + 28 * t1 - 3 * c1 * c1 + 8 * EP2 + 24 * t1 * t1) * d**5 / 120
    ) / cos
    return math.degrees(lat), math.degrees(lon)


def map_to_latlon(datum: dict[str, float], x: float, y: float) -> tuple[float, float]:
    """A point of the mower's map (metres from the datum, x east, y north) as latitude and longitude."""
    zone = utm_zone(datum["lat"], datum["lon"])
    east, north = to_utm(datum["lat"], datum["lon"], zone)
    return from_utm(east + x, north + y, zone, datum["lat"] < 0)
