"""Original odometer evidence and canonical kilometre values.

Existing start/end_odometer fields always contain KM. New evidence must
include its original value and an explicit unit; historical KM-only payloads
remain compatible. Never trust a client-supplied converted value.
"""
from decimal import Decimal, InvalidOperation

MILES_TO_KM = Decimal("1.609344")
MAX_ORIGINAL = Decimal("9999999")


def kilometres(original, unit):
    if unit not in ("km", "mi"):
        raise ValueError("Confirm the odometer unit (KM or Miles).")
    try:
        if isinstance(original, bool):
            raise ValueError
        value = Decimal(str(original))
        if not value.is_finite() or value < 0 or value > MAX_ORIGINAL:
            raise ValueError
    except (InvalidOperation, ValueError, TypeError):
        raise ValueError("Enter a valid non-negative odometer reading.") from None
    return value * MILES_TO_KM if unit == "mi" else value


def normalize_odometer_fields(data):
    """Mutate a snake-case journey payload; validate before distance/claims."""
    for phase in ("start", "end"):
        original_key = f"{phase}_odometer_original"
        unit_key = f"{phase}_odometer_unit"
        canonical_key = f"{phase}_odometer"
        if original_key in data or unit_key in data:
            original, unit = data.get(original_key), data.get(unit_key)
            if original is None:
                if unit is not None or data.get(canonical_key) is not None:
                    raise ValueError("The original odometer reading is required.")
                continue
            value = kilometres(original, unit)
            data[original_key] = float(Decimal(str(original)))
            data[canonical_key] = float(value)
        elif data.get(canonical_key) is not None:
            # Historical contracts explicitly used kilometre-only fields.
            value = kilometres(data[canonical_key], "km")
            data[canonical_key] = float(value)
    start, end = data.get("start_odometer"), data.get("end_odometer")
    if start is not None and end is not None:
        delta = Decimal(str(end)) - Decimal(str(start))
        if delta < 0:
            raise ValueError("End odometer cannot be below start odometer (in KM).")
        data["calculated_odometer_distance"] = float(delta)
    return data
