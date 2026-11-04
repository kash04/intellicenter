"""Read-only IntelliCenter controller alerts.

Active alerts are objects whose type is ``STATUS``. pyintellicenter 0.3.2 does
not model that type. Listing it in the integration's attribute map is enough
for ``PoolModel`` to keep the objects and for the library to subscribe to the
ones it already knows. A later alert is a new object, so it is not in that
subscription until something discovers it. The coordinator re-reads
``GetActiveStatusMessages`` and reconciles the model from that read-only query.

IntelliChlor fault flags (``COMERR``, ``SALTLO``, ``VERYLO``, ``CUTOFF``,
``CLEAN``) are attributes of the chlorinator object, handled with the other
chemistry sensors. No Flow is not one of those flags.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from pyintellicenter import (
    MODE_ATTR,
    NULL_OBJNAM,
    OBJTYP_ATTR,
    PARENT_ATTR,
    SHOMNU_ATTR,
    SINDEX_ATTR,
    SNAME_ATTR,
    SUBTYP_ATTR,
    TIME_ATTR,
    PoolModel,
    PoolObject,
)

from .const import COUNT_ATTR, PARTY_ATTR, STATUS_OBJECT_TYPE

ACTIVE_ALERTS_QUERY = "GetActiveStatusMessages"

# Keys stored on a STATUS object and requested by the attribute map.
STATUS_TRACKED_ATTRIBUTES = frozenset(
    {
        SNAME_ATTR,
        PARENT_ATTR,
        MODE_ATTR,
        COUNT_ATTR,
        PARTY_ATTR,
        SINDEX_ATTR,
        TIME_ATTR,
        SHOMNU_ATTR,
    }
)


@dataclass(frozen=True, slots=True)
class ActiveAlert:
    """One active controller alert, already reduced to display fields."""

    objnam: str
    message: str
    parent: str | None = None
    count: int | None = None
    time: int | None = None
    mode: str | None = None

    def as_dict(self) -> dict[str, Any]:
        """Return the JSON-serializable attributes for this alert."""
        details: dict[str, Any] = {"objnam": self.objnam, "message": self.message}
        if self.parent is not None:
            details["parent"] = self.parent
        if self.count is not None:
            details["count"] = self.count
        if self.time is not None:
            details["time"] = self.time
        if self.mode is not None:
            details["mode"] = self.mode
        return details


def alert_state_attributes(alerts: list[ActiveAlert]) -> dict[str, Any]:
    """Return the shared sensor/binary-sensor attribute payload."""
    return {
        "alerts": [alert.message for alert in alerts],
        "alert_details": [alert.as_dict() for alert in alerts],
    }


def active_alerts(model: PoolModel) -> list[ActiveAlert]:
    """Return the STATUS objects currently in the model, in a stable order."""
    alerts = [_alert_from_object(obj) for obj in model.get_by_type(STATUS_OBJECT_TYPE)]
    alerts.sort(key=lambda alert: (alert.message.casefold(), alert.objnam))
    return alerts


def parse_active_status_response(
    response: Any,
) -> list[tuple[str, dict[str, Any]]] | None:
    """Parse a GetActiveStatusMessages response.

    Returns the alert entries, an empty list when the controller reports none,
    or None when the payload is not a usable alert list. None must not be
    treated as "no alerts": doing so would clear alerts the model already has.
    """
    if not isinstance(response, dict):
        return None
    code = response.get("response")
    if code is not None and str(code) != "200":
        return None
    answer = _answer_list(response)
    if answer is None:
        return None

    entries: dict[str, dict[str, Any]] = {}
    for item in answer:
        parsed = _parse_status_item(item)
        if parsed is not None:
            entries[parsed[0]] = parsed[1]
    if answer and not entries:
        return None
    return list(entries.items())


def apply_status_snapshot(
    model: PoolModel, entries: list[tuple[str, dict[str, Any]]]
) -> dict[str, dict[str, Any] | None]:
    """Make the model's STATUS objects match one active-alert snapshot.

    Additions and changes are attribute dicts. A removed alert is ``None``,
    the same shape the coordinator already uses for deleted equipment.
    Objects of any other type are left alone.
    """
    updates: dict[str, dict[str, Any] | None] = {}
    seen: set[str] = set()
    for objnam, params in entries:
        existing = model[objnam]
        if existing is not None and existing.objtype != STATUS_OBJECT_TYPE:
            continue
        seen.add(objnam)
        if existing is None:
            created = model.add_object(objnam, params)
            if created is not None:
                updates[objnam] = _addition_payload(created)
            continue
        changed = existing.update(params)
        if changed:
            updates[objnam] = changed

    for obj in list(model.get_by_type(STATUS_OBJECT_TYPE)):
        if obj.objnam not in seen:
            model.remove_object(obj.objnam)
            updates[obj.objnam] = None
    return updates


def _answer_list(response: dict[str, Any]) -> list[Any] | None:
    """Return the alert list from either a query answer or an object list."""
    answer = response.get("answer", response.get("objectList"))
    if isinstance(answer, dict):
        nested = answer.get("objectList", answer.get("answer"))
        answer = nested
    if isinstance(answer, list):
        return answer
    return None


def _parse_status_item(item: Any) -> tuple[str, dict[str, Any]] | None:
    """Normalize one flat or ``{objnam, params}`` alert entry."""
    if not isinstance(item, dict):
        return None
    params = item.get("params")
    objnam = item.get("objnam")
    if isinstance(params, dict) and isinstance(objnam, str) and objnam:
        raw: dict[str, Any] = params
    else:
        raw = item
        objnam = item.get("OBJNAM", item.get("objnam"))
        if not isinstance(objnam, str) or not objnam:
            return None

    objtype = raw.get(OBJTYP_ATTR)
    if objtype not in (None, STATUS_OBJECT_TYPE):
        return None

    stored: dict[str, Any] = {OBJTYP_ATTR: STATUS_OBJECT_TYPE}
    for key in STATUS_TRACKED_ATTRIBUTES:
        if key not in raw:
            continue
        value = _usable_value(key, raw[key])
        if value is not None:
            stored[key] = value
    return objnam, stored


def _usable_value(key: str, value: Any) -> Any:
    """Drop empty, echoed, and non-scalar values.

    A key the panel does not actually store is echoed back as the key name.
    Those must not become alert state.
    """
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        return value
    if isinstance(value, str):
        text = value.strip()
        if not text or text == key:
            return None
        return text
    return None


def _addition_payload(obj: PoolObject) -> dict[str, Any]:
    """Return the full attribute set for an object just added to the model."""
    payload = dict(obj.properties)
    payload[OBJTYP_ATTR] = obj.objtype
    if obj.subtype is not None:
        payload[SUBTYP_ATTR] = obj.subtype
    return payload


def _alert_from_object(obj: PoolObject) -> ActiveAlert:
    """Project one STATUS object onto the attributes entities expose."""
    message = obj.sname
    if (
        not isinstance(message, str)
        or not message.strip()
        or message.strip() == SNAME_ATTR
    ):
        message = obj.objnam
    parent = obj[PARENT_ATTR]
    if (
        not isinstance(parent, str)
        or not parent.strip()
        or parent in (PARENT_ATTR, NULL_OBJNAM)
    ):
        parent = None
    mode = obj[MODE_ATTR]
    if not isinstance(mode, str) or not mode.strip() or mode.strip() == MODE_ATTR:
        mode = None
    return ActiveAlert(
        objnam=obj.objnam,
        message=message.strip(),
        parent=parent,
        count=_whole_number(obj[COUNT_ATTR]),
        time=_whole_number(obj[TIME_ATTR]),
        mode=mode.strip() if isinstance(mode, str) else None,
    )


def _whole_number(value: Any) -> int | None:
    """Return an integer count or epoch, ignoring echoed and blank values."""
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value) if value.is_integer() else None
    if isinstance(value, str):
        text = value.strip()
        if text and text.isascii() and text.lstrip("-").isdecimal():
            return int(text)
    return None
