"""Reading OpenMower events."""

from __future__ import annotations

import pytest

from custom_components.mowbite.events import EVENT_TYPES, EventReader, Texts, interpret

EN = Texts("en")
DE = Texts("de")


def _read(events: list[dict], fallback: str | None = None) -> list[str]:
    reader = EventReader()
    fired = [reader.read(e, EN, fallback) for e in events]
    return [f[0] for f in fired if f]


def test_reader_judges_by_the_state_events() -> None:
    gps_lost = {"type": "GPS", "available": False}
    assert _read([{"type": "STATE", "state": "MOWING"}, gps_lost]) == ["gps_lost"]
    assert _read([{"type": "STATE", "state": "DOCKING"}, gps_lost]) == []
    # before the first STATE event robot_state's state counts
    assert _read([gps_lost], fallback="MOWING") == ["gps_lost"]
    assert _read([{"type": "STATE", "state": "DOCKING"}, gps_lost], fallback="MOWING") == []


def test_reader_leaving_the_dock() -> None:
    undock = [{"type": "STATE", "state": "UNDOCKING"}, {"type": "UNDOCKED"}]
    assert _read([{"type": "STATE", "state": "IDLE"}, *undock]) == ["undocked"]
    assert _read(undock, fallback="IDLE") == ["undocked"]
    # a docking retry backs out of the dock, that's not leaving to mow
    retry = [
        {"type": "STATE", "state": "DOCKING"},
        {"type": "DOCKING_RETRY", "reason": "dock_failed", "attempts": 1},
        *undock,
        {"type": "STATE", "state": "DOCKING"},
        {"type": "DOCKED"},
    ]
    assert _read(retry) == ["docking_retry", "docked"]


@pytest.mark.parametrize(
    ("reason", "why", "message", "extra"),
    [
        ("Manual pause", "paused", "Heading home: paused by you", {}),
        ("Battery average voltage low: 24.23 V", "battery", "Heading home to charge: battery low (24.2 V)", {"battery_voltage": 24.23}),
        ("Battery voltage critical", "battery", "Heading home to charge: battery low", {}),
        ("Mow motor over temp: 71.4 °C", "hot", "Heading home: mow motor too hot (71 °C)", {"temperature": 71.4}),
        ("Rain detected", "rain", "Heading home: rain", {}),
        ("something_new", "other", "Heading home: something new", {}),
    ],
)
def test_heading_home(reason: str, why: str, message: str, extra: dict) -> None:
    event_type, attrs = interpret({"type": "DOCKING", "reason": reason}, "MOWING", EN)
    assert event_type == "heading_home"
    assert attrs == {"severity": "info", "message": message, "reason": why, "details": reason, **extra}


def test_heading_home_without_reason() -> None:
    assert interpret({"type": "DOCKING"}, "MOWING", EN) == ("heading_home", {"severity": "info", "message": "Heading home"})


def test_gps_lost_only_counts_while_mowing() -> None:
    assert interpret({"type": "GPS", "available": False}, "MOWING", EN) == (
        "gps_lost",
        {"severity": "warning", "message": "GPS lost"},
    )
    assert interpret({"type": "GPS", "available": False}, "DOCKING", EN) is None
    assert interpret({"type": "GPS", "available": True}, "MOWING", EN) is None


def test_docking() -> None:
    assert interpret({"type": "DOCKING_RETRY", "reason": "dock_failed", "attempts": 3}, "DOCKING", EN) == (
        "docking_retry",
        {"severity": "warning", "message": "Docking retry 3 (no contact with the charger)", "reason": "dock_failed", "attempts": 3},
    )
    assert interpret({"type": "DOCKING_FAILED", "reason": "approach_failed", "attempts": 5}, "DOCKING", DE) == (
        "docking_failed",
        {
            "severity": "error",
            "message": "Andocken nach 5 Versuchen fehlgeschlagen (Anfahrt fehlgeschlagen)",
            "reason": "approach_failed",
            "attempts": 5,
        },
    )
    assert interpret({"type": "UNDOCKING_FAILED", "reason": "no_gps"}, "UNDOCKING", DE)[1]["message"] == (
        "Abdocken fehlgeschlagen (kein GPS-Fix)"
    )


def test_emergency() -> None:
    assert interpret({"type": "EMERGENCY", "emergency": True, "reason": "0"}, "MOWING", EN) == (
        "emergency",
        {"severity": "error", "message": "Emergency stop"},
    )
    assert interpret({"type": "EMERGENCY", "emergency": True, "reason": "4"}, "MOWING", EN)[1]["message"] == (
        "Emergency stop (code 4)"
    )
    assert interpret({"type": "EMERGENCY", "emergency": False}, "IDLE", EN)[0] == "emergency_cleared"


def test_area() -> None:
    assert interpret({"type": "AREA", "area_name": "Vorgarten"}, "MOWING", DE) == (
        "area_started",
        {"severity": "info", "message": "Mäht „Vorgarten“", "area_name": "Vorgarten"},
    )
    assert interpret({"type": "AREA", "area_name": ""}, "MOWING", EN)[1] == {
        "severity": "info",
        "message": "Mowing an unnamed area",
    }


def test_fully_charged() -> None:
    assert interpret({"type": "FULLY_CHARGED", "battery_voltage": 28.71}, "IDLE", EN)[1] == {
        "severity": "info",
        "message": "Fully charged (28.7 V)",
        "battery_voltage": 28.71,
    }


@pytest.mark.parametrize("kind", ["STATE", "BLADES", "SOMETHING_NEW"])
def test_not_fired(kind: str) -> None:
    assert interpret({"type": kind, "state": "MOWING", "enabled": True}, "IDLE", EN) is None


def test_every_type_fired_is_declared() -> None:
    events = [
        {"type": t}
        for t in (
            "UNDOCKED",
            "AREA",
            "AREA_SKIPPED",
            "DOCKING",
            "DOCKED",
            "JOB_COMPLETE",
            "JOB_RESET",
            "FULLY_CHARGED",
            "DOCKING_RETRY",
            "DOCKING_FAILED",
            "UNDOCKING_FAILED",
            "NAVIGATION_ERROR",
            "MOW_MOTOR_SPINUP_FAILED",
            "BOOTED",
            "SHUTDOWN",
        )
    ]
    events += [{"type": "GPS", "available": False}, {"type": "EMERGENCY", "emergency": True}, {"type": "EMERGENCY"}]
    fired = {interpret(e, "MOWING", EN)[0] for e in events}
    assert fired == set(EVENT_TYPES)


def test_unknown_language_falls_back_to_english() -> None:
    assert interpret({"type": "DOCKED"}, None, Texts("et"))[1]["message"] == "Docked"
    assert interpret({"type": "DOCKED"}, None, Texts("de-CH"))[1]["message"] == "Angedockt"
