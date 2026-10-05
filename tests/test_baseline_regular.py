"""Regular-washer recovery baseline: the REAL select.py / button.py code paths.

Proves that the baseline integration uses the proven immediate library
setters directly (no staging, no Send to Washer, no specialty wiring). Run
against the baseline library pin (60e0867) by setting WHISK_LIBRARY_DIR; see
conftest.py.

A real library Washer/Dryer is used. Its send_attributes() is replaced by a
recorder, so nothing ever touches the network, and every request that WOULD
be sent is visible and checked exactly.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import pytest
from whirlpool.dryer import Dryer
from whirlpool.types import ApplianceInfo
from whirlpool.washer import CYCLE_CAPABILITIES, WASH_CYCLE_MATRIX, Washer
from whisk_ha_harness import HomeAssistantError, load_integration_modules

sel, btn = load_integration_modules()

WFW_MODEL = "WFW9620HBK3"
ATTR_OPS = "Cavity_OpSetOperations"
SPECIALTY_CLEAR_KEYS = {
    "Cavity_CycleSetDownloadAndGo",
    "Cavity_CycleSetSpecialtyCycleId",
}
INTEGRATION_DIR = Path(__file__).resolve().parent.parent / "custom_components" / "whirlpool"


def _attrs(**overrides: object) -> dict[str, dict[str, str]]:
    base: dict[str, object] = {
        "Online": 1,
        "Cavity_CycleStatusMachineState": 0,  # Standby
        "WashCavity_CycleSetCycleSelect": 1,  # Regular/Normal
        "WashCavity_CycleSetTemperature": 2,
        "WashCavity_CycleSetSpinSpeed": 5,
        "WashCavity_CycleSetSoilLevel": 1,
        "WashCavity_CycleSetExtraRinseSelect": 0,
        "WashCavity_CycleSetPresoakTimed": 0,
        "WashCavity_CycleSetFresheningSelect": 0,
        "Cavity_CycleSetSteamEnable": 0,
        "WashCavity_ChangeStatusCycleSelect": 1,
        "WashCavity_ChangeStatusTemperature": 1,
        "WashCavity_ChangeStatusSpinSpeed": 1,
        "WashCavity_ChangeStatusSoilLevel": 1,
        "WashCavity_ChangeStatusExtraRinse": 1,
        "WashCavity_ChangeStatusPresoakTimed": 1,
        "WashCavity_ChangeStatusFreshening": 1,
        "Cavity_ChangeStatusSteamChangeable": 1,
        "XCat_RemoteSetRemoteControlEnable": 1,
        "WashCavity_CycleSetBulkDispense1Enable": 1,
    }
    base.update(overrides)
    return {k: {"value": str(v), "updateTime": "1000"} for k, v in base.items()}


class _Recorder:
    def __init__(self) -> None:
        self.calls: list[dict[str, str]] = []

    async def __call__(self, attributes: dict[str, str]) -> bool:
        self.calls.append(dict(attributes))
        return True


def _info(said: str, model: str) -> ApplianceInfo:
    return ApplianceInfo(
        said=said,
        name="Test",
        data_model="API144",
        category="Laundry",
        model_number=model,
        serial_number="TEST",
    )


def _washer(**overrides: object) -> tuple[Washer, _Recorder]:
    washer = Washer(None, None, None, _info("SAIDWFW9620", WFW_MODEL))  # type: ignore[arg-type]
    washer._data_dict = {"attributes": _attrs(**overrides)}
    rec = _Recorder()
    washer.send_attributes = rec  # type: ignore[method-assign]
    return washer, rec


def _run(coro: Any) -> Any:
    return asyncio.run(coro)


def _expected_init(wire: int) -> dict[str, str]:
    """The live-proven destination-only init body (library 32c9be1/60e0867)."""
    return Washer(
        None, None, None, _info("X", WFW_MODEL)
    )._cycle_initialization_payload(  # type: ignore[arg-type]
        wire
    )


def _clean(payload: dict[str, str]) -> None:
    assert ATTR_OPS not in payload
    assert "1003" not in payload.values()
    assert not (SPECIALTY_CLEAR_KEYS & payload.keys())


# ---------------------------------------------------------------------------
# Library under test is the known-good pin
# ---------------------------------------------------------------------------


def test_library_is_pre_specialty_known_good():
    """60e0867 has no specialty/staging builders; its cycle init is private."""
    import whirlpool.washer as w

    assert hasattr(Washer, "_cycle_initialization_payload")
    assert not hasattr(w, "build_cycle_init_payload")
    assert not hasattr(Washer, "set_specialty_cycle")


# ---------------------------------------------------------------------------
# What / How - immediate, exact live-proven body, no specialty-clear keys
# ---------------------------------------------------------------------------


def test_what_selection_sends_exact_cycle_init_immediately():
    washer, rec = _washer()
    _run(sel.WhirlpoolWasherWhatSelect(washer).async_select_option("colors"))
    wire = WASH_CYCLE_MATRIX[("colors", "normal")]
    assert rec.calls == [_expected_init(wire)]
    _clean(rec.calls[0])


def test_how_selection_sends_exact_cycle_init_immediately():
    washer, rec = _washer()
    _run(sel.WhirlpoolWasherHowSelect(washer).async_select_option("quick"))
    wire = WASH_CYCLE_MATRIX[("regular", "quick")]
    assert rec.calls == [_expected_init(wire)]
    _clean(rec.calls[0])


def test_delicates_normal_matches_level_a_official_app_capture():
    """LEVEL A (library 32c9be1): the official app writes exactly this 8-key body."""
    washer, rec = _washer(
        WashCavity_CycleSetCycleSelect=WASH_CYCLE_MATRIX[("delicates", "quick")]
    )
    _run(sel.WhirlpoolWasherHowSelect(washer).async_select_option("normal"))
    assert rec.calls == [
        {
            "WashCavity_CycleSetCycleSelect": "5",
            "WashCavity_CycleSetTemperature": "2",
            "WashCavity_CycleSetSpinSpeed": "2",
            "WashCavity_CycleSetSoilLevel": "1",
            "WashCavity_CycleSetPresoakTimed": "0",
            "WashCavity_CycleSetExtraRinseSelect": "0",
            "WashCavity_CycleSetFresheningSelect": "0",
            "Cavity_CycleSetSteamEnable": "0",
        }
    ]


# ---------------------------------------------------------------------------
# Options - immediate single-attribute writes
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("entity_cls", "option", "attr", "wire"),
    [
        (
            "WhirlpoolWasherTemperatureSelect",
            "hot",
            "WashCavity_CycleSetTemperature",
            "3",
        ),
        (
            "WhirlpoolWasherSpinSpeedSelect",
            "medium",
            "WashCavity_CycleSetSpinSpeed",
            "3",
        ),
        (
            "WhirlpoolWasherSoilLevelSelect",
            "heavy",
            "WashCavity_CycleSetSoilLevel",
            "2",
        ),
        (
            "WhirlpoolWasherExtraRinseSelect",
            "on",
            "WashCavity_CycleSetExtraRinseSelect",
            "1",
        ),
        (
            "WhirlpoolWasherPresoakSelect",
            "30_min",
            "WashCavity_CycleSetPresoakTimed",
            "1800",
        ),
        (
            "WhirlpoolWasherFanFreshSelect",
            "on",
            "WashCavity_CycleSetFresheningSelect",
            None,
        ),
        ("WhirlpoolWasherSteamSelect", "on", "Cavity_CycleSetSteamEnable", None),
    ],
)
def test_option_sends_single_attribute_immediately(entity_cls, option, attr, wire):
    washer, rec = _washer()
    entity = getattr(sel, entity_cls)(washer)
    assert entity.available is True
    _run(entity.async_select_option(option))
    assert len(rec.calls) == 1
    assert list(rec.calls[0]) == [attr]
    if wire is not None:
        assert rec.calls[0][attr] == wire
    _clean(rec.calls[0])


def test_option_refused_when_appliance_says_not_changeable():
    washer, rec = _washer(WashCavity_ChangeStatusTemperature=0)
    entity = sel.WhirlpoolWasherTemperatureSelect(washer)
    assert entity.available is False
    with pytest.raises(HomeAssistantError):
        _run(entity.async_select_option("hot"))
    assert rec.calls == []


# ---------------------------------------------------------------------------
# Utility - immediate, exact init body
# ---------------------------------------------------------------------------


def test_utility_drain_spin_sends_exact_init_immediately():
    washer, rec = _washer()
    _run(
        sel.WhirlpoolWasherUtilityCycleSelect(washer).async_select_option("drain_spin")
    )
    assert rec.calls == [_expected_init(8)]
    assert rec.calls[0]["WashCavity_CycleSetCycleSelect"] == "8"
    _clean(rec.calls[0])


def test_every_matrix_and_utility_init_body_has_no_specialty_clear_keys():
    for wire in {*WASH_CYCLE_MATRIX.values(), 8, 20}:
        body = _expected_init(wire)
        assert body["WashCavity_CycleSetCycleSelect"] == str(wire)
        _clean(body)
        # Clean Washer (20) declares no options, so its body is CycleSelect only.
        cap = CYCLE_CAPABILITIES.get(wire)
        if cap is not None and cap.default_temperature is not None:
            assert "WashCavity_CycleSetTemperature" in body


# ---------------------------------------------------------------------------
# Dispenser (unchanged, still immediate)
# ---------------------------------------------------------------------------


def test_dispenser_enable_still_immediate():
    washer, rec = _washer()
    _run(
        sel.WhirlpoolWasherDispenserEnableSelect(washer, 1).async_select_option(
            "disabled"
        )
    )
    assert len(rec.calls) == 1
    _clean(rec.calls[0])


# ---------------------------------------------------------------------------
# Start / command gate (historically established, unchanged)
# ---------------------------------------------------------------------------


def test_start_blocked_when_remote_control_off():
    washer, rec = _washer(XCat_RemoteSetRemoteControlEnable=0)
    start = btn.WasherCommandButton(washer, btn.WASHER_BUTTONS[0])
    assert start.entity_description.command == "start"
    assert start.available is False
    with pytest.raises(HomeAssistantError) as err:
        _run(start.async_press())
    assert err.value.translation_key == "remote_control_disabled"
    assert rec.calls == []


def test_start_allowed_remote_on_standby_and_sends_op_2_only():
    washer, rec = _washer()
    start = btn.WasherCommandButton(washer, btn.WASHER_BUTTONS[0])
    assert start.available is True
    _run(start.async_press())
    assert rec.calls == [{ATTR_OPS: "2"}]


def test_start_unavailable_while_running_pause_available():
    washer, _ = _washer(Cavity_CycleStatusMachineState=7)
    assert btn.WasherCommandButton(washer, btn.WASHER_BUTTONS[0]).available is False
    assert btn.WasherCommandButton(washer, btn.WASHER_BUTTONS[1]).available is True


# ---------------------------------------------------------------------------
# No staging, no Send to Washer, no specialty wiring
# ---------------------------------------------------------------------------


class _Manager:
    def __init__(self, washer: Washer) -> None:
        self.washers = [washer]
        self.dryers: list = []
        self.ovens: list = []
        self.refrigerators: list = []
        self.aircons: list = []


class _Entry:
    def __init__(self, manager: _Manager) -> None:
        self.runtime_data = manager  # baseline: runtime_data IS the manager


def _setup(module: Any, washer: Washer) -> list:
    added: list = []
    _run(module.async_setup_entry(None, _Entry(_Manager(washer)), added.extend))
    return added


def test_select_platform_wires_no_staging_and_the_specialty_select():
    washer, rec = _washer()
    entities = _setup(sel, washer)
    names = {type(e).__name__ for e in entities}
    assert "WhirlpoolWasherWhatSelect" in names
    assert "WhirlpoolWasherUtilityCycleSelect" in names
    assert "WhirlpoolWasherSpecialtyCycleSelect" in names
    assert not any(hasattr(e, "_staging") for e in entities)
    assert rec.calls == []  # setup sends nothing


def test_button_platform_has_no_send_to_washer():
    washer, _ = _washer()
    entities = _setup(btn, washer)
    names = {type(e).__name__ for e in entities}
    assert names == {"WasherCommandButton"}
    assert not hasattr(btn, "WasherSendButton")


def test_production_sources_have_no_staging_or_1003():
    for name in ("select.py", "button.py", "__init__.py", "specialty.py"):
        text = (INTEGRATION_DIR / name).read_text(encoding="utf-8")
        assert "washer_staging" not in text
        assert "WasherStaging" not in text
        assert "1003" not in text


# ---------------------------------------------------------------------------
# Dryer regression
# ---------------------------------------------------------------------------


def _dryer(remote: int) -> tuple[Dryer, _Recorder]:
    dryer = Dryer(None, None, None, _info("SAIDDRYER", "WED9620HBK2"))  # type: ignore[arg-type]
    dryer._data_dict = {
        "attributes": {
            "Online": {"value": "1", "updateTime": "1"},
            "XCat_RemoteSetRemoteControlEnable": {
                "value": str(remote),
                "updateTime": "1",
            },
        }
    }
    rec = _Recorder()
    dryer.send_attributes = rec  # type: ignore[method-assign]
    return dryer, rec


def test_dryer_select_not_gated_by_remote_enable():
    """Dryer configuration is gated by the dryer's changeability, not Remote Enable.

    This fixture reports no ChangeStatus flags, so the select stays unavailable
    and refuses with invalid_value_set - never remote_control_disabled.
    """
    dryer, rec = _dryer(0)
    entity = sel.WhirlpoolDryerWhatSelect(dryer)
    assert entity.available is False
    with pytest.raises(HomeAssistantError) as err:
        _run(entity.async_select_option("towels"))
    assert err.value.translation_key == "invalid_value_set"
    assert rec.calls == []


def test_dryer_start_remote_gate_unchanged():
    dryer, rec = _dryer(0)
    start = btn.DryerCommandButton(dryer, btn.DRYER_BUTTONS[0])
    assert start.available is False
    assert rec.calls == []
