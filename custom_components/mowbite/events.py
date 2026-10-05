"""What an OpenMower event means, the same way the MowBite app reads them (src/lib/events.ts)."""

from __future__ import annotations

import re
from typing import Any

SEVERITY_ERROR = "error"
SEVERITY_WARNING = "warning"
SEVERITY_INFO = "info"

# the event types the event entity fires, everything else (STATE, BLADES, GPS while parked) only feeds the state
EVENT_TYPES = [
    "undocked",
    "area_started",
    "area_skipped",
    "heading_home",
    "docked",
    "job_complete",
    "job_reset",
    "fully_charged",
    "gps_lost",
    "docking_retry",
    "docking_failed",
    "undocking_failed",
    "navigation_error",
    "mow_motor_spinup_failed",
    "emergency",
    "emergency_cleared",
    "booted",
    "shutdown",
]

# why it heads home, from the reason mower_logic gives (mower_logic.cpp): "Manual pause", "Battery voltage critical:
# 23.1 V", "Battery average voltage low: 24.2 V", "Mow motor over temp: 71 °C", "Rain detected"
HOME_PAUSED = "paused"
HOME_BATTERY = "battery"
HOME_HOT = "hot"
HOME_RAIN = "rain"
HOME_OTHER = "other"

_NUMBER = re.compile(r"-?\d+(\.\d+)?")

TEXTS: dict[str, dict[str, str]] = {
    "en": {
        "undocked": "Left the dock",
        "area_started": 'Mowing "{area}"',
        "area_started_unnamed": "Mowing an unnamed area",
        "area_skipped": "Area skipped",
        "home": "Heading home",
        "home_reason": "Heading home: {reason}",
        "home_paused": "Heading home: paused by you",
        "home_battery": "Heading home to charge: battery low",
        "home_battery_v": "Heading home to charge: battery low ({v} V)",
        "home_hot": "Heading home: mow motor too hot",
        "home_hot_t": "Heading home: mow motor too hot ({t} °C)",
        "home_rain": "Heading home: rain",
        "docked": "Docked",
        "job_complete": "All areas done",
        "job_reset": "Interrupted job dropped, the next start begins from the start",
        "fully_charged": "Fully charged",
        "fully_charged_v": "Fully charged ({v} V)",
        "gps_lost": "GPS lost",
        "docking_retry": "Docking retry {n} ({reason})",
        "docking_failed": "Docking failed after {n} tries ({reason})",
        "undocking_failed": "Leaving the dock failed",
        "undocking_failed_reason": "Leaving the dock failed ({reason})",
        "navigation_error": "Navigation error",
        "mow_motor_spinup_failed": "Mow motor didn't start",
        "emergency": "Emergency stop",
        "emergency_code": "Emergency stop (code {code})",
        "emergency_spinup": "Emergency stop: the mow motor didn't start",
        "emergency_cleared": "Emergency cleared",
        "booted": "Mower started",
        "shutdown": "Shut down",
        "reason_path_failed": "couldn't follow the path",
        "reason_approach_failed": "approach failed",
        "reason_dock_failed": "no contact with the charger",
        "reason_no_gps": "no GPS fix",
        "snooze_hour": "Snooze 1 h",
        "snooze_morning": "Until tomorrow morning",
    },
    "de": {
        "undocked": "Dock verlassen",
        "area_started": "Mäht „{area}“",
        "area_started_unnamed": "Mäht eine Fläche ohne Namen",
        "area_skipped": "Fläche übersprungen",
        "home": "Fährt nach Hause",
        "home_reason": "Fährt nach Hause: {reason}",
        "home_paused": "Heimfahrt: von dir pausiert",
        "home_battery": "Zum Laden heim: Akku niedrig",
        "home_battery_v": "Zum Laden heim: Akku niedrig ({v} V)",
        "home_hot": "Heimfahrt: Mähmotor zu heiß",
        "home_hot_t": "Heimfahrt: Mähmotor zu heiß ({t} °C)",
        "home_rain": "Heimfahrt: Regen",
        "docked": "Angedockt",
        "job_complete": "Alle Flächen fertig",
        "job_reset": "Unterbrochener Job verworfen, der nächste Start beginnt von vorne",
        "fully_charged": "Voll geladen",
        "fully_charged_v": "Voll geladen ({v} V)",
        "gps_lost": "GPS verloren",
        "docking_retry": "Andock-Versuch {n} ({reason})",
        "docking_failed": "Andocken nach {n} Versuchen fehlgeschlagen ({reason})",
        "undocking_failed": "Abdocken fehlgeschlagen",
        "undocking_failed_reason": "Abdocken fehlgeschlagen ({reason})",
        "navigation_error": "Navigationsfehler",
        "mow_motor_spinup_failed": "Mähmotor lief nicht an",
        "emergency": "Notaus",
        "emergency_code": "Notaus (Code {code})",
        "emergency_spinup": "Notaus: Mähmotor lief nicht an",
        "emergency_cleared": "Notaus aufgehoben",
        "booted": "Mäher gestartet",
        "shutdown": "Heruntergefahren",
        "reason_path_failed": "konnte dem Weg nicht folgen",
        "reason_approach_failed": "Anfahrt fehlgeschlagen",
        "reason_dock_failed": "kein Kontakt zur Ladestation",
        "reason_no_gps": "kein GPS-Fix",
        "snooze_hour": "1 h pausieren",
        "snooze_morning": "Bis morgen früh",
    },
}


def home_reason(reason: str | None) -> str | None:
    if not reason:
        return None
    if reason == "Manual pause":
        return HOME_PAUSED
    if reason.startswith("Battery"):
        return HOME_BATTERY
    if reason.startswith("Mow motor over temp"):
        return HOME_HOT
    if reason.startswith("Rain"):
        return HOME_RAIN
    return HOME_OTHER


def _number(text: str | None) -> float | None:
    match = _NUMBER.search(text or "")
    return float(match.group()) if match else None


class Texts:
    """The messages in one language, English for everything there's no translation for."""

    def __init__(self, language: str | None) -> None:
        lang = (language or "en").split("-")[0].lower()
        self._texts = TEXTS.get(lang, TEXTS["en"])

    def __call__(self, key: str, **values: Any) -> str:
        return self._texts.get(key, TEXTS["en"][key]).format(**values)

    def reason(self, reason: str | None) -> str:
        if not reason:
            return ""
        key = f"reason_{reason}"
        if key in TEXTS["en"]:
            return self(key)
        return reason.replace("_", " ").lower()


class EventReader:
    """Reads the event stream in order, each event against the state the mower was in when it happened."""

    def __init__(self) -> None:
        self.state: str | None = None
        # the state before the current one: UNDOCKING after DOCKING is backing out for another try at the dock
        self.previous: str | None = None

    def read(self, event: dict[str, Any], texts: Texts, fallback: str | None = None) -> tuple[str, dict[str, Any]] | None:
        """fallback is robot_state's state, for the events before the first STATE event."""
        state = self.state or fallback
        if event.get("type") == "STATE":
            new = event.get("state")
            if isinstance(new, str) and new != state:
                self.previous, self.state = state, new
            elif isinstance(new, str):
                self.state = new
            return None
        if event.get("type") == "UNDOCKED" and state == "UNDOCKING" and self.previous == "DOCKING":
            return None
        return interpret(event, state, texts)


def interpret(event: dict[str, Any], state: str | None, texts: Texts) -> tuple[str, dict[str, Any]] | None:
    """The event entity's type and attributes for an OpenMower event, None when it's nothing to fire.

    state is what the mower was doing when it happened: gps is switched off on purpose outside of mowing, so losing
    it only counts while mowing.
    """
    kind = event.get("type")
    reason = event.get("reason") if isinstance(event.get("reason"), str) else None
    attempts = event.get("attempts")

    def fire(event_type: str, severity: str, message: str, **extra: Any) -> tuple[str, dict[str, Any]]:
        attrs = {"severity": severity, "message": message}
        attrs.update({k: v for k, v in extra.items() if v is not None})
        return event_type, attrs

    match kind:
        case "UNDOCKED":
            return fire("undocked", SEVERITY_INFO, texts("undocked"))
        case "AREA":
            area = event.get("area_name") or None
            message = texts("area_started", area=area) if area else texts("area_started_unnamed")
            return fire("area_started", SEVERITY_INFO, message, area_name=area)
        case "AREA_SKIPPED":
            return fire("area_skipped", SEVERITY_INFO, texts("area_skipped"))
        case "DOCKING":
            why = home_reason(reason)
            value = _number(reason)
            if why == HOME_PAUSED:
                message = texts("home_paused")
            elif why == HOME_BATTERY:
                message = texts("home_battery_v", v=f"{value:.1f}") if value is not None else texts("home_battery")
            elif why == HOME_HOT:
                message = texts("home_hot_t", t=round(value)) if value is not None else texts("home_hot")
            elif why == HOME_RAIN:
                message = texts("home_rain")
            elif reason:
                message = texts("home_reason", reason=texts.reason(reason))
            else:
                message = texts("home")
            return fire(
                "heading_home",
                SEVERITY_INFO,
                message,
                reason=why,
                details=reason,
                battery_voltage=value if why == HOME_BATTERY else None,
                temperature=value if why == HOME_HOT else None,
            )
        case "DOCKED":
            return fire("docked", SEVERITY_INFO, texts("docked"))
        case "JOB_COMPLETE":
            return fire("job_complete", SEVERITY_INFO, texts("job_complete"))
        case "JOB_RESET":
            return fire("job_reset", SEVERITY_INFO, texts("job_reset"))
        case "FULLY_CHARGED":
            volts = event.get("battery_voltage")
            if isinstance(volts, (int, float)):
                return fire("fully_charged", SEVERITY_INFO, texts("fully_charged_v", v=f"{volts:.1f}"), battery_voltage=volts)
            return fire("fully_charged", SEVERITY_INFO, texts("fully_charged"))
        case "GPS":
            if event.get("available") or state != "MOWING":
                return None
            return fire("gps_lost", SEVERITY_WARNING, texts("gps_lost"))
        case "DOCKING_RETRY":
            message = texts("docking_retry", n=attempts if attempts is not None else "", reason=texts.reason(reason))
            return fire("docking_retry", SEVERITY_WARNING, message.replace("  ", " "), reason=reason, attempts=attempts)
        case "DOCKING_FAILED":
            message = texts("docking_failed", n=attempts if attempts is not None else "?", reason=texts.reason(reason))
            return fire("docking_failed", SEVERITY_ERROR, message, reason=reason, attempts=attempts)
        case "UNDOCKING_FAILED":
            message = (
                texts("undocking_failed_reason", reason=texts.reason(reason)) if reason else texts("undocking_failed")
            )
            return fire("undocking_failed", SEVERITY_ERROR, message, reason=reason)
        case "NAVIGATION_ERROR":
            return fire("navigation_error", SEVERITY_ERROR, texts("navigation_error"))
        case "MOW_MOTOR_SPINUP_FAILED":
            return fire("mow_motor_spinup_failed", SEVERITY_ERROR, texts("mow_motor_spinup_failed"))
        case "EMERGENCY":
            if not event.get("emergency"):
                return fire("emergency_cleared", SEVERITY_INFO, texts("emergency_cleared"))
            if reason and reason != "0":
                return fire("emergency", SEVERITY_ERROR, texts("emergency_code", code=reason), reason=reason)
            return fire("emergency", SEVERITY_ERROR, texts("emergency"))
        case "BOOTED":
            return fire("booted", SEVERITY_INFO, texts("booted"))
        case "SHUTDOWN":
            return fire("shutdown", SEVERITY_INFO, texts("shutdown"))
    return None
