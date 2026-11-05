# Copyright (c) 2026
# License: MIT - see LICENSE for details
"""Shared GPS movement validation for attendance-linked trip features.

Pure functions only - no frappe imports - so the exact same algorithm and
parameters can be mirrored on the mobile client (Dart) and unit-tested
against a single shared fixture file (see tests/fixtures/).

Policy: an attendance trip STARTS immediately at check-in; this validator
gates only the one-time start-odometer REMINDER (and any other ~100 m
displacement decision), never trip creation, route capture or
synchronization.

- A reminder fires only after GENUINE displacement beyond ~100 m from the
  check-in anchor is confirmed. GPS drift and inaccurate fixes must never
  fire it.
- Confirmation requires MOVEMENT_CONFIRM_FIXES distinct qualifying fixes
  within a MOVEMENT_CONFIRM_WINDOW_S rolling window.
- A fix qualifies when it is fresh, accurate enough, not a duplicate
  coordinate, displaced beyond the accuracy budget (100 m + anchor accuracy
  + fix accuracy), and its implied speed is physically plausible.
"""

import math

# --- Policy constants (mirror in Dart: lib/core/gps/movement_validator.dart) ---
MOVEMENT_MIN_DISPLACEMENT_M = 100.0
MOVEMENT_MAX_FIX_ACCURACY_M = 50.0
MOVEMENT_FALLBACK_ACCURACY_M = 50.0
MOVEMENT_CONFIRM_FIXES = 3
MOVEMENT_CONFIRM_WINDOW_S = 30
MOVEMENT_MAX_FIX_AGE_S = 30
MOVEMENT_FUTURE_SKEW_S = 5
MOVEMENT_MAX_SPEED_KMH = 180.0
MOVEMENT_DUPLICATE_EPSILON_M = 1.0

_EARTH_RADIUS_M = 6371000.0


def haversine_m(lat1, lon1, lat2, lon2):
    """Geodesic distance in meters between two WGS84 points."""
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlam = math.radians(lon2 - lon1)
    a = (
        math.sin(dphi / 2.0) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(dlam / 2.0) ** 2
    )
    return 2.0 * _EARTH_RADIUS_M * math.asin(min(1.0, math.sqrt(a)))


def _fix_accuracy(fix):
    value = fix.get("accuracy")
    if value is None:
        return MOVEMENT_FALLBACK_ACCURACY_M
    try:
        return float(value)
    except (TypeError, ValueError):
        return MOVEMENT_FALLBACK_ACCURACY_M


def _valid_coords(lat, lon):
    return (
        lat is not None
        and lon is not None
        and -90.0 <= float(lat) <= 90.0
        and -180.0 <= float(lon) <= 180.0
    )


def evaluate_fix(fix, anchor, now_ms):
    """Classify one GPS fix against the check-in anchor.

    Returns dict(ok, reason, displacement_m, budget_m, age_s, speed_kmh).
    ``reason`` is None when the fix qualifies.
    """
    lat = fix.get("latitude")
    lon = fix.get("longitude")
    ts = fix.get("timestamp")
    if not _valid_coords(lat, lon) or ts is None:
        return {"ok": False, "reason": "malformed", "displacement_m": None}

    age_s = (now_ms - float(ts)) / 1000.0
    if age_s > MOVEMENT_MAX_FIX_AGE_S or age_s < -MOVEMENT_FUTURE_SKEW_S:
        return {"ok": False, "reason": "stale", "displacement_m": None, "age_s": age_s}

    accuracy = _fix_accuracy(fix)
    if accuracy > MOVEMENT_MAX_FIX_ACCURACY_M:
        return {
            "ok": False,
            "reason": "low_accuracy",
            "accuracy_m": accuracy,
            "displacement_m": None,
        }

    displacement = haversine_m(
        float(anchor["latitude"]),
        float(anchor["longitude"]),
        float(lat),
        float(lon),
    )

    # Duplicate / re-delivered coordinates never count as movement.
    if displacement <= MOVEMENT_DUPLICATE_EPSILON_M:
        return {
            "ok": False,
            "reason": "duplicate",
            "displacement_m": displacement,
            "accuracy_m": accuracy,
        }

    budget = (
        MOVEMENT_MIN_DISPLACEMENT_M
        + _fix_accuracy(anchor)
        + accuracy
    )
    if displacement <= budget:
        return {
            "ok": False,
            "reason": "within_budget",
            "displacement_m": displacement,
            "budget_m": budget,
            "accuracy_m": accuracy,
        }

    # Implied speed from the anchor must be physically plausible.
    elapsed_s = max(1.0, (float(ts) - float(anchor["timestamp"])) / 1000.0)
    speed_kmh = (displacement / elapsed_s) * 3.6
    if speed_kmh > MOVEMENT_MAX_SPEED_KMH:
        return {
            "ok": False,
            "reason": "implausible_speed",
            "displacement_m": displacement,
            "speed_kmh": speed_kmh,
            "accuracy_m": accuracy,
        }

    return {
        "ok": True,
        "reason": None,
        "displacement_m": displacement,
        "budget_m": budget,
        "accuracy_m": accuracy,
        "age_s": age_s,
    }


def evaluate_movement(anchor, fixes, now_ms=None):
    """Evaluate a fix stream for confirmed genuine movement.

    Args:
        anchor: dict(latitude, longitude, accuracy?, timestamp) - the
            successful check-in position (epoch milliseconds).
        fixes: list of dicts(latitude, longitude, accuracy?, timestamp).
        now_ms: evaluation clock; defaults to the newest fix timestamp so
            offline replays judge freshness relative to capture time, not
            server receive time.

    Returns dict with:
        status: 'confirmed' | 'insufficient'
        confirmed_at_ms: timestamp of the confirming fix (None otherwise)
        qualifying: the qualifying fix timestamps
        reasons: per-fix rejection reasons (index -> reason)
        max_displacement_m: largest anchor displacement observed
    """
    if now_ms is None:
        now_ms = max(
            [float(anchor["timestamp"])]
            + [float(f["timestamp"]) for f in fixes if f.get("timestamp") is not None]
        )

    reasons = {}
    qualifying = []
    max_displacement = 0.0
    seen_coords = [
        (float(anchor["latitude"]), float(anchor["longitude"]))
    ]

    for index, fix in enumerate(fixes):
        verdict = evaluate_fix(fix, anchor, now_ms)
        if verdict.get("displacement_m") is not None:
            max_displacement = max(max_displacement, verdict["displacement_m"])
        if not verdict["ok"]:
            reasons[index] = verdict["reason"]
            continue

        lat = float(fix["latitude"])
        lon = float(fix["longitude"])
        # Distinct-fix rule: the same coordinates re-delivered by the OS
        # must not inflate the confirmation count.
        if any(
            haversine_m(lat, lon, prev_lat, prev_lon) <= MOVEMENT_DUPLICATE_EPSILON_M
            for prev_lat, prev_lon in seen_coords
        ):
            reasons[index] = "duplicate"
            continue
        seen_coords.append((lat, lon))
        qualifying.append(float(fix["timestamp"]))

    if len(qualifying) < MOVEMENT_CONFIRM_FIXES:
        return {
            "status": "insufficient",
            "confirmed_at_ms": None,
            "qualifying": qualifying,
            "reasons": reasons,
            "max_displacement_m": max_displacement,
        }

    # Confirmation: the last CONFIRM_FIXES distinct qualifying fixes must
    # sit inside one CONFIRM_WINDOW_S rolling window.
    window_ms = MOVEMENT_CONFIRM_WINDOW_S * 1000.0
    recent = qualifying[-MOVEMENT_CONFIRM_FIXES:]
    if recent[-1] - recent[0] > window_ms:
        return {
            "status": "insufficient",
            "confirmed_at_ms": None,
            "qualifying": qualifying,
            "reasons": reasons,
            "max_displacement_m": max_displacement,
        }

    return {
        "status": "confirmed",
        "confirmed_at_ms": recent[-1],
        "qualifying": qualifying,
        "reasons": reasons,
        "max_displacement_m": max_displacement,
    }
