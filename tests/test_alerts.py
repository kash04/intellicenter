"""Read-only IntelliChlor problem sensors and controller status alerts."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

from homeassistant.components.binary_sensor import BinarySensorDeviceClass
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from pyintellicenter import (
    CHEM_TYPE,
    CIRCUIT_TYPE,
    PARENT_ATTR,
    STATUS_OFF,
    STATUS_ON,
    ICCommandError,
    PoolModel,
    PoolObject,
)
import pytest

from custom_components.intellicenter.alerts import (
    active_alerts,
    alert_state_attributes,
    apply_status_snapshot,
    parse_active_status_response,
)
from custom_components.intellicenter.binary_sensor import (
    AnyAlertBinarySensor,
    ChlorinatorAlertBinarySensor,
    PoolBinarySensor,
    _build_entities as build_binary_sensors,
)
from custom_components.intellicenter.const import (
    CHLORINATOR_PROBLEM_ATTRS,
    CHLORINATOR_SUBTYPE,
    CLEAN_ATTR,
    COMERR_ATTR,
    COUNT_ATTR,
    CUTOFF_ATTR,
    SALTLO_ATTR,
    STATUS_OBJECT_TYPE,
    VERYLO_ATTR,
)
from custom_components.intellicenter.coordinator import (
    DEFAULT_ATTRIBUTES_MAP,
    IntelliCenterCoordinator,
)
from custom_components.intellicenter.sensor import (
    ActiveAlertsSensor,
    _build_entities as build_sensors,
)
from custom_components.intellicenter.switch import _build_entities as build_switches

PARENT = "CHEM1"
ALERT_OBJNAM = "t0001"
ALERT_MESSAGE = "Chlorinator: No Flow"


def _model() -> PoolModel:
    return PoolModel(DEFAULT_ATTRIBUTES_MAP)


def _chlorinator(**flags: str) -> PoolObject:
    return PoolObject(
        PARENT,
        {
            "OBJTYP": CHEM_TYPE,
            "SUBTYP": CHLORINATOR_SUBTYPE,
            "SNAME": "IntelliChlor",
            "SALT": "3200",
            **flags,
        },
    )


def _status_response(*items: dict[str, str]) -> dict[str, object]:
    return {"response": "200", "answer": list(items)}


def test_problem_flags_are_tracked_and_not_manual_priority() -> None:
    """The model must request chlorinator flags and alert rows, not MANOVR."""
    assert set(CHLORINATOR_PROBLEM_ATTRS) <= DEFAULT_ATTRIBUTES_MAP[CHEM_TYPE]
    assert {
        "SNAME",
        "PARENT",
        "MODE",
        "COUNT",
        "PARTY",
        "SINDEX",
        "TIME",
        "SHOMNU",
    } <= DEFAULT_ATTRIBUTES_MAP[STATUS_OBJECT_TYPE]
    assert "MANOVR" not in DEFAULT_ATTRIBUTES_MAP[STATUS_OBJECT_TYPE]
    assert "NOFLO" not in DEFAULT_ATTRIBUTES_MAP[CHEM_TYPE]


def test_parse_accepts_flat_and_nested_alert_entries() -> None:
    """Both query shapes reduce to the same stored alert."""
    flat = _status_response(
        {
            "OBJNAM": ALERT_OBJNAM,
            "OBJTYP": STATUS_OBJECT_TYPE,
            "PARENT": PARENT,
            "SNAME": ALERT_MESSAGE,
            "MODE": "0",
            "COUNT": "2",
            "TIME": "100",
            "SHOMNU": "ON",
            "COUNT_ECHO": "COUNT_ECHO",
        }
    )
    nested = {
        "response": "200",
        "answer": [
            {
                "objnam": ALERT_OBJNAM,
                "params": {
                    "OBJTYP": STATUS_OBJECT_TYPE,
                    "PARENT": PARENT,
                    "SNAME": f"  {ALERT_MESSAGE}  ",
                    "MODE": "0",
                    "COUNT": "COUNT",
                    "TIME": "100",
                },
            }
        ],
    }

    assert parse_active_status_response(flat) == [
        (
            ALERT_OBJNAM,
            {
                "OBJTYP": STATUS_OBJECT_TYPE,
                "PARENT": PARENT,
                "SNAME": ALERT_MESSAGE,
                "MODE": "0",
                "COUNT": "2",
                "TIME": "100",
                "SHOMNU": "ON",
            },
        )
    ]
    parsed_nested = parse_active_status_response(nested)
    assert parsed_nested is not None
    assert parsed_nested[0][0] == ALERT_OBJNAM
    assert "COUNT" not in parsed_nested[0][1]
    assert parsed_nested[0][1]["SNAME"] == ALERT_MESSAGE


@pytest.mark.parametrize(
    "payload",
    [
        None,
        {},
        {"response": "404", "answer": []},
        {"response": "200", "answer": "nope"},
        {"response": "200", "answer": [{"note": "not an alert"}]},
        {"answer": [{"OBJNAM": "t0002", "OBJTYP": "CIRCUIT", "SNAME": "Pump"}]},
    ],
)
def test_parse_rejects_unusable_payloads(payload: object) -> None:
    """An unusable payload must not look like an empty alert list."""
    assert parse_active_status_response(payload) is None


def test_empty_answer_is_an_authoritative_clear() -> None:
    """A successful empty answer means there are no active alerts."""
    assert parse_active_status_response({"response": "200", "answer": []}) == []


def test_snapshot_adds_updates_and_removes_only_status_objects() -> None:
    """Reconciliation changes alert rows and leaves other equipment alone."""
    model = _model()
    circuit = model.add_object(
        "C0001", {"OBJTYP": CIRCUIT_TYPE, "SNAME": "Pool", "STATUS": "ON"}
    )
    assert circuit is not None
    stale = model.add_object(
        "t0009",
        {
            "OBJTYP": STATUS_OBJECT_TYPE,
            "SNAME": "Heater: Check Flow",
            "PARENT": "HTR01",
        },
    )
    assert stale is not None

    added = apply_status_snapshot(
        model,
        [
            (
                ALERT_OBJNAM,
                {
                    "OBJTYP": STATUS_OBJECT_TYPE,
                    "SNAME": ALERT_MESSAGE,
                    "PARENT": PARENT,
                    "COUNT": "1",
                },
            )
        ],
    )
    assert set(added) == {ALERT_OBJNAM, "t0009"}
    assert added["t0009"] is None
    assert model["t0009"] is None
    assert model[ALERT_OBJNAM] is not None
    assert model["C0001"] is circuit

    changed = apply_status_snapshot(
        model,
        [
            (
                ALERT_OBJNAM,
                {
                    "OBJTYP": STATUS_OBJECT_TYPE,
                    "SNAME": ALERT_MESSAGE,
                    "PARENT": PARENT,
                    "COUNT": "3",
                },
            )
        ],
    )
    assert changed == {ALERT_OBJNAM: {"COUNT": "3"}}
    alerts = active_alerts(model)
    assert [alert.message for alert in alerts] == [ALERT_MESSAGE]
    assert alerts[0].as_dict() == {
        "objnam": ALERT_OBJNAM,
        "message": ALERT_MESSAGE,
        "parent": PARENT,
        "count": 3,
    }
    assert alert_state_attributes(alerts)["alerts"] == [ALERT_MESSAGE]


def test_apply_does_not_clobber_a_non_alert_with_the_same_name() -> None:
    """An alert id that collides with equipment must not overwrite that object."""
    model = _model()
    model.add_object("C0001", {"OBJTYP": CIRCUIT_TYPE, "SNAME": "Pool", "STATUS": "ON"})
    updates = apply_status_snapshot(
        model,
        [("C0001", {"OBJTYP": STATUS_OBJECT_TYPE, "SNAME": ALERT_MESSAGE})],
    )
    assert updates == {}
    assert model["C0001"] is not None
    assert model["C0001"].objtype == CIRCUIT_TYPE


def test_missing_message_falls_back_to_the_object_id() -> None:
    """A STATUS row with no usable name is still an active alert."""
    model = _model()
    model.add_object(
        ALERT_OBJNAM,
        {"OBJTYP": STATUS_OBJECT_TYPE, "PARENT": "00000", "SNAME": "SNAME"},
    )
    alert = active_alerts(model)[0]
    assert alert.message == ALERT_OBJNAM
    assert PARENT_ATTR not in alert.as_dict()
    assert "parent" not in alert.as_dict()


def test_chlorinator_problem_sensors_follow_reported_flags(
    mock_coordinator: MagicMock,
) -> None:
    """Create one problem sensor per real ON/OFF flag, and keep salt separate."""
    chlorinator = _chlorinator(
        **{
            COMERR_ATTR: STATUS_ON,
            SALTLO_ATTR: STATUS_OFF,
            VERYLO_ATTR: STATUS_OFF,
            CUTOFF_ATTR: STATUS_OFF,
            CLEAN_ATTR: "CLEAN",
        }
    )
    intellichem = PoolObject(
        "CHEM2",
        {
            "OBJTYP": CHEM_TYPE,
            "SUBTYP": "ICHEM",
            "SNAME": "IntelliChem",
            COMERR_ATTR: STATUS_ON,
        },
    )

    sensors = build_binary_sensors(mock_coordinator, [chlorinator, intellichem])
    by_key = {
        sensor._attribute_key: sensor
        for sensor in sensors
        if sensor._pool_object.objnam == PARENT
    }
    assert set(by_key) == {
        "CHLOR_ALERT",
        COMERR_ATTR,
        SALTLO_ATTR,
        VERYLO_ATTR,
        CUTOFF_ATTR,
    }
    chem_sensors = [
        sensor for sensor in sensors if sensor._pool_object.objnam == "CHEM2"
    ]
    assert chem_sensors
    assert all(
        not isinstance(sensor, ChlorinatorAlertBinarySensor)
        and sensor._attribute_key not in CHLORINATOR_PROBLEM_ATTRS
        for sensor in chem_sensors
    )
    communication = by_key[COMERR_ATTR]
    assert isinstance(communication, PoolBinarySensor)
    assert communication.name == "IntelliChlor (Communication Lost)"
    assert communication.unique_id == f"test_entry_{PARENT}{COMERR_ATTR}"
    assert communication.device_class == BinarySensorDeviceClass.PROBLEM
    assert communication.entity_category == EntityCategory.DIAGNOSTIC
    assert communication.is_on is True
    assert by_key[SALTLO_ATTR].is_on is False

    summary = by_key["CHLOR_ALERT"]
    assert isinstance(summary, ChlorinatorAlertBinarySensor)
    assert summary.name == "IntelliChlor Chlorinator Alert"
    assert summary.is_on is True
    assert summary.extra_state_attributes["active_alerts"] == ["Communication Lost"]
    assert summary.isUpdated({PARENT: {SALTLO_ATTR: STATUS_ON}}) is True
    assert summary.isUpdated({PARENT: {"SALT": "3000"}}) is False


def test_chlorinator_summary_includes_parented_status_alerts(
    mock_coordinator: MagicMock,
) -> None:
    """No Flow is a STATUS row parented to the chlorinator, not a flag."""
    mock_coordinator.model = _model()
    chlorinator = _chlorinator(
        **dict.fromkeys(
            (COMERR_ATTR, SALTLO_ATTR, VERYLO_ATTR, CUTOFF_ATTR, CLEAN_ATTR),
            STATUS_OFF,
        )
    )
    no_flow = "IntelliChlor 1: No Flow"
    mock_coordinator.model.add_object(
        ALERT_OBJNAM,
        {
            "OBJTYP": STATUS_OBJECT_TYPE,
            "SNAME": no_flow,
            "PARENT": PARENT,
        },
    )
    mock_coordinator.model.add_object(
        "t0002",
        {
            "OBJTYP": STATUS_OBJECT_TYPE,
            "SNAME": "Pump: Check",
            "PARENT": "PMP01",
        },
    )

    summary = next(
        sensor
        for sensor in build_binary_sensors(mock_coordinator, [chlorinator])
        if isinstance(sensor, ChlorinatorAlertBinarySensor)
    )
    assert summary.is_on is True
    assert summary.extra_state_attributes["active_alerts"] == [no_flow]
    assert summary.coordinator_update_dependencies() == {
        ALERT_OBJNAM: {"SNAME", "PARENT"},
        "t0002": {"SNAME", "PARENT"},
    }
    assert summary.isUpdated({ALERT_OBJNAM: {"SNAME": no_flow}}) is True
    assert summary.isUpdated({PARENT: {"SALT": "3000"}}) is False

    mock_coordinator.model.remove_object(ALERT_OBJNAM)
    assert summary.is_on is False
    assert summary.extra_state_attributes["active_alerts"] == []

    salt_sensors = [
        sensor
        for sensor in build_sensors(mock_coordinator, [chlorinator])
        if sensor.unique_id.endswith("SALT")
    ]
    assert len(salt_sensors) == 1
    assert salt_sensors[0].native_value == 3200
    assert build_switches(mock_coordinator, [chlorinator]) == []


def test_unreported_chlorinator_flags_create_no_problem_sensors(
    mock_coordinator: MagicMock,
) -> None:
    """Echoed or absent flags are not chlorinator problem entities."""
    chlorinator = _chlorinator(**{COMERR_ATTR: COMERR_ATTR, CLEAN_ATTR: ""})
    assert build_binary_sensors(mock_coordinator, [chlorinator]) == []


def test_status_rows_do_not_become_switches(mock_coordinator: MagicMock) -> None:
    """Alert rows stay diagnostic; they are not controllable equipment."""
    alert = PoolObject(
        ALERT_OBJNAM,
        {
            "OBJTYP": STATUS_OBJECT_TYPE,
            "SNAME": ALERT_MESSAGE,
            "PARENT": PARENT,
            "MANOVR": STATUS_ON,
        },
    )
    assert build_switches(mock_coordinator, [alert]) == []
    assert build_sensors(mock_coordinator, [alert]) == []
    assert build_binary_sensors(mock_coordinator, [alert]) == []


def test_controller_alert_entities_reflect_the_model(
    mock_coordinator: MagicMock,
) -> None:
    """The count sensor and any-alert sensor read the same STATUS objects."""
    mock_coordinator.connected = True
    mock_coordinator.model = _model()
    mock_coordinator.system_info = None
    count = ActiveAlertsSensor(mock_coordinator)
    problem = AnyAlertBinarySensor(mock_coordinator)

    assert count.translation_key == "active_alerts"
    assert problem.translation_key == "any_alert"
    assert count.native_value == 0
    assert problem.is_on is False
    assert count.extra_state_attributes["alerts"] == []
    assert count.device_class is None
    assert problem.device_class == BinarySensorDeviceClass.PROBLEM
    assert count.entity_category == EntityCategory.DIAGNOSTIC
    assert count.unique_id == "test_entry_active_alerts"
    assert problem.unique_id == "test_entry_any_alert"

    mock_coordinator.model.add_object(
        ALERT_OBJNAM,
        {
            "OBJTYP": STATUS_OBJECT_TYPE,
            "SNAME": ALERT_MESSAGE,
            "PARENT": PARENT,
            COUNT_ATTR: "1",
        },
    )
    assert count.native_value == 1
    assert problem.is_on is True
    assert problem.extra_state_attributes["alerts"] == [ALERT_MESSAGE]
    assert problem.extra_state_attributes["alert_details"][0]["parent"] == PARENT

    mock_coordinator.connected = False
    assert count.available is False
    assert problem.available is False


async def test_refresh_replaces_alerts_from_the_read_only_query(
    hass: HomeAssistant,
) -> None:
    """A successful query adds, updates and removes STATUS objects."""
    entry = MagicMock()
    entry.entry_id = "alert_entry"
    coordinator = IntelliCenterCoordinator(hass, entry, host="intellicenter.local")
    coordinator.model.add_object(
        "t0009",
        {"OBJTYP": STATUS_OBJECT_TYPE, "SNAME": "Old alert"},
    )
    coordinator._handler._is_connected = True
    coordinator._controller.send_cmd = AsyncMock(
        return_value=_status_response(
            {
                "OBJNAM": ALERT_OBJNAM,
                "OBJTYP": STATUS_OBJECT_TYPE,
                "SNAME": ALERT_MESSAGE,
                "PARENT": PARENT,
            }
        )
    )

    await coordinator.async_refresh_status_alerts()

    coordinator._controller.send_cmd.assert_awaited_once_with(
        "GetQuery",
        {"queryName": "GetActiveStatusMessages", "arguments": ""},
    )
    assert coordinator.model["t0009"] is None
    assert coordinator.model[ALERT_OBJNAM] is not None
    assert coordinator.model[ALERT_OBJNAM].sname == ALERT_MESSAGE


async def test_refresh_keeps_alerts_when_the_query_is_rejected(
    hass: HomeAssistant,
) -> None:
    """A rejected query must not clear alerts already in the model."""
    entry = MagicMock()
    entry.entry_id = "alert_entry"
    coordinator = IntelliCenterCoordinator(hass, entry, host="intellicenter.local")
    coordinator.model.add_object(
        ALERT_OBJNAM,
        {"OBJTYP": STATUS_OBJECT_TYPE, "SNAME": ALERT_MESSAGE},
    )
    coordinator._handler._is_connected = True
    coordinator._controller.send_cmd = AsyncMock(side_effect=ICCommandError("404"))

    await coordinator.async_refresh_status_alerts()
    await coordinator.async_refresh_status_alerts()

    assert coordinator.model[ALERT_OBJNAM] is not None
    assert coordinator._controller.send_cmd.await_count == 2


async def test_refresh_ignores_an_unusable_payload(hass: HomeAssistant) -> None:
    """A successful but unreadable answer must not clear known alerts."""
    entry = MagicMock()
    entry.entry_id = "alert_entry"
    coordinator = IntelliCenterCoordinator(hass, entry, host="intellicenter.local")
    coordinator.model.add_object(
        ALERT_OBJNAM,
        {"OBJTYP": STATUS_OBJECT_TYPE, "SNAME": ALERT_MESSAGE},
    )
    coordinator._handler._is_connected = True
    coordinator._controller.send_cmd = AsyncMock(
        return_value={"response": "200", "answer": [{"note": "not an alert"}]}
    )

    await coordinator.async_refresh_status_alerts()

    assert coordinator.model[ALERT_OBJNAM] is not None
    assert coordinator.model[ALERT_OBJNAM].sname == ALERT_MESSAGE


async def test_refresh_does_not_query_while_disconnected(hass: HomeAssistant) -> None:
    """No alert command is sent unless the panel connection is up."""
    entry = MagicMock()
    entry.entry_id = "alert_entry"
    coordinator = IntelliCenterCoordinator(hass, entry, host="intellicenter.local")
    coordinator._controller.send_cmd = AsyncMock()

    await coordinator.async_refresh_status_alerts()

    coordinator._controller.send_cmd.assert_not_called()


async def test_alert_refresh_loop_stops_with_the_coordinator(
    hass: HomeAssistant,
) -> None:
    """Stopping the coordinator cancels the background alert reconcile."""
    entry = MagicMock()
    entry.entry_id = "alert_entry"
    coordinator = IntelliCenterCoordinator(hass, entry, host="intellicenter.local")
    with patch.object(coordinator._handler, "start", new_callable=AsyncMock):
        await coordinator.async_start()
    task = coordinator._alert_refresh_task
    assert task is not None
    assert not task.done()

    await coordinator.async_stop()

    assert task.done()
    assert coordinator._alert_refresh_task is None
