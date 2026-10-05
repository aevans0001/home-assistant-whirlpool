"""Specialty (Download & Go) on top of the regular-washer LKG baseline.

Runs the REAL select.py / button.py / specialty.py against the library the
baseline manifest pins (60e0867; set WHISK_LIBRARY_DIR, see conftest.py).
send_attributes() is replaced by a recorder, so nothing touches the network.

The expected Specialty bodies are derived straight from the washer DDM
(research/apk-analysis/phase5c_ddm_results.json), so the evidence is the
oracle, not a hand-copied table.
"""

from __future__ import annotations

import asyncio
import importlib
import json
from pathlib import Path
from typing import Any

import pytest
from whirlpool.types import ApplianceInfo
from whirlpool.washer import WASH_CYCLE_MATRIX, Washer
from whisk_ha_harness import (
    PKG_NAME,
    HomeAssistantError,
    ServiceValidationError,
    load_integration_modules,
)

sel, btn = load_integration_modules()
spec = importlib.import_module(f"{PKG_NAME}.specialty")

WFW_MODEL = "WFW9620HBK3"
ATTR_OPS = "Cavity_OpSetOperations"
DNG = "Cavity_CycleSetDownloadAndGo"
SPEC_ID = "Cavity_CycleSetSpecialtyCycleId"
CYCLE_NAME = "Cavity_CycleSetCycleName"
INTEGRATION_DIR = Path(__file__).resolve().parent.parent / "custom_components" / "whirlpool"
LEGACY_ROOT = INTEGRATION_DIR.parent.parent
DDM_FILE = LEGACY_ROOT / "research" / "apk-analysis" / "phase5c_ddm_results.json"

OFFICIAL_ACTIVEWEAR = {
    "WashCavity_CycleSetTemperature": "2",
    "Cavity_CycleSetDownloadAndGo": "1",
    "WashCavity_CycleSetSoilLevel": "2",
    "WashCavity_CycleSetCycleSelect": "1",
    "Cavity_CycleSetCycleName": "Activewear",
    "WashCavity_CycleSetSpinSpeed": "5",
    "Cavity_CycleSetSpecialtyCycleId": "1",
}

# option key -> (CycleName, CycleSelect, Temperature, SpinSpeed, SoilLevel)
EXPECTED_PRESETS = {
    "coats_jackets": ("Jackets", "70", "0", "4", "2"),
    "diapers": ("Diapers", "92", "4", "5", "2"),
    "sleeping_bags": ("SleepingBags", "22", "2", "3", "2"),
    "comforters": ("Comforters", "90", "2", "3", "0"),
    "machine_wash_curtains": ("Curtains", "44", "0", "3", "0"),
    "swimwear": ("Swimwear", "65", "0", "3", "0"),
    "activewear": ("Activewear", "1", "2", "5", "2"),
    "jeans": ("Jeans", "11", "2", "5", "1"),
    "blankets": ("Blankets", "50", "3", "5", "1"),
    "lingerie": ("Lingerie", "70", "1", "2", "0"),
    "business_casual": ("BusinessCasual", "16", "1", "4", "1"),
}
# DDM capability key suffix for each option key.
DDM_KEYS = {
    "coats_jackets": "CoatsJackets",
    "diapers": "Diapers",
    "sleeping_bags": "SleepingBags",
    "comforters": "Comforters",
    "machine_wash_curtains": "MachineWashCurtains",
    "swimwear": "Swimwear",
    "activewear": "Activewear",
    "jeans": "Jeans",
    "blankets": "Blankets",
    "lingerie": "Lingerie",
    "business_casual": "BusinessCasual",
}


def _expected_body(option: str) -> dict[str, str]:
    name, cycle, temp, spin, soil = EXPECTED_PRESETS[option]
    return {
        "Cavity_CycleSetDownloadAndGo": "1",
        "Cavity_CycleSetSpecialtyCycleId": "1",
        "WashCavity_CycleSetCycleSelect": cycle,
        "WashCavity_CycleSetSoilLevel": soil,
        "WashCavity_CycleSetSpinSpeed": spin,
        "WashCavity_CycleSetTemperature": temp,
        "Cavity_CycleSetCycleName": name,
    }


def _attrs(**overrides: object) -> dict[str, dict[str, str]]:
    base: dict[str, object] = {
        "Online": 1,
        "Cavity_CycleStatusMachineState": 0,  # Standby
        "WashCavity_CycleSetCycleSelect": 1,
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
        # Idle Specialty state, exactly as the live captures read it.
        DNG: 0,
        SPEC_ID: 0,
        CYCLE_NAME: "None",
    }
    base.update(overrides)
    return {k: {"value": str(v), "updateTime": "1000"} for k, v in base.items()}


class _Recorder:
    def __init__(self) -> None:
        self.calls: list[dict[str, str]] = []

    async def __call__(self, attributes: dict[str, str]) -> bool:
        self.calls.append(dict(attributes))
        return True


def _washer(model: str = WFW_MODEL, **overrides: object) -> tuple[Washer, _Recorder]:
    info = ApplianceInfo(
        said="SAIDWFW9620",
        name="Test",
        data_model="API144",
        category="Laundry",
        model_number=model,
        serial_number="TEST",
    )
    washer = Washer(None, None, None, info)  # type: ignore[arg-type]
    washer._data_dict = {"attributes": _attrs(**overrides)}
    rec = _Recorder()
    washer.send_attributes = rec  # type: ignore[method-assign]
    return washer, rec


def _active(option: str) -> dict[str, object]:
    name, cycle, temp, spin, soil = EXPECTED_PRESETS[option]
    return {
        DNG: 1,
        SPEC_ID: 1,
        CYCLE_NAME: name,
        "WashCavity_CycleSetCycleSelect": cycle,
        "WashCavity_CycleSetTemperature": temp,
        "WashCavity_CycleSetSpinSpeed": spin,
        "WashCavity_CycleSetSoilLevel": soil,
    }


def _run(coro: Any) -> Any:
    return asyncio.run(coro)


def _init(wire: int) -> dict[str, str]:
    return Washer(
        None, None, None, ApplianceInfo("X", "X", "API144", "Laundry", WFW_MODEL, "X")
    )._cycle_initialization_payload(wire)  # type: ignore[arg-type]


def _no_specialty_keys(body: dict[str, str]) -> None:
    assert ATTR_OPS not in body
    assert "1003" not in body.values()
    assert not ({DNG, SPEC_ID, CYCLE_NAME} & body.keys())


# ---------------------------------------------------------------------------
# Evidence: the DDM is the oracle
# ---------------------------------------------------------------------------


def _ddm_washer() -> dict[str, Any]:
    if not DDM_FILE.is_file():
        pytest.skip("Private model DDM evidence is not distributed")
    data = json.loads(DDM_FILE.read_text(encoding="utf-8"))
    # Select by DDM type, never by a household appliance identifier.
    washers = [
        item for item in data["response"].values()
        if "WASHER" in item["dataModel"]["id"]
    ]
    assert len(washers) == 1
    return washers[0]


def _ddm_enum_to_wire(ddm: dict[str, Any]) -> dict[str, dict[str, str]]:
    out: dict[str, dict[str, str]] = {}
    for attr in ddm["dataModel"]["attributes"]:
        if attr.get("EnumValues"):
            out[attr["M2MAttributeName"]] = {
                v: k for k, v in attr["EnumValues"].items()
            }
    return out


def _ddm_body(option: str) -> dict[str, str]:
    ddm = _ddm_washer()
    enums = _ddm_enum_to_wire(ddm)
    cap = ddm["personality"]["capability"][0]["Capability"]["WashCavity"]
    entry = cap["CapabilityData"][f"Cavity_CycleSetCycleName{DDM_KEYS[option]}"]
    assert entry["Required"] == {}

    body: dict[str, str] = {}
    for attr, value in entry["NonEditable"].items():
        body[attr] = enums[attr][value] if attr in enums else str(value)
    return body


def test_ddm_names_only_cycle_set_temperature():
    if not DDM_FILE.is_file():
        pytest.skip("Private model DDM evidence is not distributed")
    text = DDM_FILE.read_text(encoding="utf-8")
    assert "WashCavity_CycleSetWashTemperature" not in text
    ddm = _ddm_washer()
    names = {a["M2MAttributeName"] for a in ddm["dataModel"]["attributes"]}
    assert "WashCavity_CycleSetTemperature" in names


def test_official_activewear_is_exactly_the_ddm_nonEditable_block():
    assert _ddm_body("activewear") == OFFICIAL_ACTIVEWEAR


@pytest.mark.parametrize("option", list(EXPECTED_PRESETS))
def test_candidate_payload_equals_ddm_field_for_field_and_order(option):
    body = spec.build_specialty_payload(option)
    assert body == _ddm_body(option)
    assert body == _expected_body(option)
    assert len(body) == 7
    assert all(isinstance(v, str) for v in body.values())
    assert ATTR_OPS not in body
    assert "1003" not in body.values()
    assert "WashCavity_CycleSetWashTemperature" not in body


def test_ddm_default_and_alphabetical_select_options():
    cap = _ddm_washer()["personality"]["capability"][0]["Capability"]["WashCavity"]
    dng = cap["SetDownloadAndGo"]
    assert dng["Default"] == "Cavity_CycleSetCycleNameActivewear"

    ddm_presets = {
        k.removeprefix("Cavity_CycleSetCycleName") for k in dng if k != "Default"
    }
    assert ddm_presets == {DDM_KEYS[o] for o in EXPECTED_PRESETS}
    assert set(spec.SPECIALTY_PRESETS) == set(EXPECTED_PRESETS)

    assert sel.WhirlpoolWasherSpecialtyCycleSelect(_washer()[0]).options == [
        "none",
        "activewear",
        "blankets",
        "business_casual",
        "coats_jackets",
        "comforters",
        "diapers",
        "jeans",
        "lingerie",
        "machine_wash_curtains",
        "sleeping_bags",
        "swimwear",
    ]


# ---------------------------------------------------------------------------
# Immediate send in either Remote Control mode; never Start
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("remote", [0, 1])
@pytest.mark.parametrize("option", list(EXPECTED_PRESETS))
def test_specialty_sends_exact_seven_keys_immediately(option, remote):
    washer, rec = _washer(XCat_RemoteSetRemoteControlEnable=remote)
    entity = sel.WhirlpoolWasherSpecialtyCycleSelect(washer)
    assert entity.available is True
    _run(entity.async_select_option(option))
    assert rec.calls == [_expected_body(option)]
    assert list(rec.calls[0]) == list(_expected_body(option))
    assert entity.current_option == option  # latched, not reset


def test_specialty_none_is_a_noop():
    washer, rec = _washer()
    entity = sel.WhirlpoolWasherSpecialtyCycleSelect(washer)
    assert entity.current_option == "none"
    _run(entity.async_select_option("none"))
    assert entity.current_option == "none"
    assert rec.calls == []


def test_activewear_remote_off_is_official_body_only():
    washer, rec = _washer(XCat_RemoteSetRemoteControlEnable=0)
    _run(
        sel.WhirlpoolWasherSpecialtyCycleSelect(washer).async_select_option(
            "activewear"
        )
    )
    assert rec.calls == [OFFICIAL_ACTIVEWEAR]


@pytest.mark.parametrize("remote", [0, 1])
def test_specialty_never_starts(remote):
    washer, rec = _washer(XCat_RemoteSetRemoteControlEnable=remote)
    _run(sel.WhirlpoolWasherSpecialtyCycleSelect(washer).async_select_option("jeans"))
    assert len(rec.calls) == 1
    assert ATTR_OPS not in rec.calls[0]
    assert not any("OpSet" in key for key in rec.calls[0])


def test_start_gate_unchanged_while_specialty_active():
    washer, rec = _washer(XCat_RemoteSetRemoteControlEnable=0, **_active("activewear"))
    start = btn.WasherCommandButton(washer, btn.WASHER_BUTTONS[0])
    assert start.available is False
    with pytest.raises(HomeAssistantError):
        _run(start.async_press())
    assert rec.calls == []

    washer, rec = _washer(**_active("activewear"))
    start = btn.WasherCommandButton(washer, btn.WASHER_BUTTONS[0])
    assert start.available is True
    _run(start.async_press())
    assert rec.calls == [{ATTR_OPS: "2"}]


def test_refused_when_cycle_not_changeable():
    washer, rec = _washer(WashCavity_ChangeStatusCycleSelect=0)
    entity = sel.WhirlpoolWasherSpecialtyCycleSelect(washer)
    assert entity.available is False
    with pytest.raises(ServiceValidationError):
        _run(entity.async_select_option("activewear"))
    assert rec.calls == []


def test_unknown_option_raises_and_sends_nothing():
    washer, rec = _washer()
    with pytest.raises(ServiceValidationError):
        _run(
            sel.WhirlpoolWasherSpecialtyCycleSelect(washer).async_select_option(
                "towels"
            )
        )
    assert rec.calls == []


def test_other_model_gets_no_entity_and_sends_nothing():
    washer, rec = _washer(model="WTW5000DW1")
    assert spec.is_specialty_model_supported(washer) is False
    assert _run(spec.set_specialty_cycle(washer, "activewear")) is False
    assert rec.calls == []


def test_missing_specialty_attributes_unavailable():
    washer, rec = _washer()
    del washer._data_dict["attributes"][DNG]
    assert sel.WhirlpoolWasherSpecialtyCycleSelect(washer).available is False
    assert _run(spec.set_specialty_cycle(washer, "activewear")) is False
    assert rec.calls == []


# ---------------------------------------------------------------------------
# Reverse state: CycleName, never CycleSelect
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("option", list(EXPECTED_PRESETS))
def test_reverse_state_decodes_every_preset(option):
    washer, _ = _washer(**_active(option))
    assert spec.get_specialty_cycle(washer) == option
    assert sel.WhirlpoolWasherSpecialtyCycleSelect(washer).current_option == "none"


def test_cycle_select_70_is_split_by_cycle_name():
    jackets, _ = _washer(**_active("coats_jackets"))
    lingerie, _ = _washer(**_active("lingerie"))
    assert jackets._get_attribute("WashCavity_CycleSetCycleSelect") == "70"
    assert lingerie._get_attribute("WashCavity_CycleSetCycleSelect") == "70"
    assert spec.get_specialty_cycle(jackets) == "coats_jackets"
    assert spec.get_specialty_cycle(lingerie) == "lingerie"


@pytest.mark.parametrize(
    ("option", "wire_name"),
    [
        ("coats_jackets", "Jackets"),
        ("machine_wash_curtains", "Curtains"),
        ("sleeping_bags", "SleepingBags"),
        ("business_casual", "BusinessCasual"),
    ],
)
def test_wire_cycle_names_that_differ_from_labels(option, wire_name):
    assert spec.build_specialty_payload(option)[CYCLE_NAME] == wire_name
    washer, _ = _washer(**_active(option))
    assert spec.get_specialty_cycle(washer) == option


def test_idle_reads_none():
    washer, _ = _washer()  # DnG=0, SpecialtyCycleId=0, CycleName="None"
    assert spec.is_specialty_cycle_active(washer) is False
    assert sel.WhirlpoolWasherSpecialtyCycleSelect(washer).current_option == "none"


def test_dng_zero_with_stale_name_reads_none():
    washer, _ = _washer(**{DNG: 0, CYCLE_NAME: "Activewear"})
    assert spec.get_specialty_cycle(washer) is None


def test_unknown_cycle_name_reads_none():
    washer, _ = _washer(**{DNG: 1, SPEC_ID: 1, CYCLE_NAME: "Pillows"})
    assert spec.get_specialty_cycle(washer) is None


# ---------------------------------------------------------------------------
# Stale Specialty attributes must not hide the current CycleSelect and options
# ---------------------------------------------------------------------------

OPTION_ENTITIES = [
    ("WhirlpoolWasherTemperatureSelect", "hot"),
    ("WhirlpoolWasherSpinSpeedSelect", "medium"),
    ("WhirlpoolWasherSoilLevelSelect", "heavy"),
    ("WhirlpoolWasherExtraRinseSelect", "on"),
    ("WhirlpoolWasherPresoakSelect", "30_min"),
    ("WhirlpoolWasherFanFreshSelect", "on"),
    ("WhirlpoolWasherSteamSelect", "on"),
]


@pytest.mark.parametrize(("entity_cls", "option"), OPTION_ENTITIES)
def test_stale_specialty_marker_does_not_hide_supported_option(entity_cls, option):
    washer, _ = _washer(
        **{**_active("machine_wash_curtains"), "WashCavity_CycleSetCycleSelect": 5}
    )
    entity = getattr(sel, entity_cls)(washer)
    assert entity.available is True


@pytest.mark.parametrize(("entity_cls", "option"), OPTION_ENTITIES)
def test_options_available_again_when_idle(entity_cls, option):
    washer, _ = _washer()
    assert getattr(sel, entity_cls)(washer).available is True


@pytest.mark.parametrize(
    ("cycle_select", "what", "how"),
    [
        (5, "delicates", "normal"),
        (67, "delicates", "heavy_duty"),
        (92, "whites", "sanitize"),
    ],
)
def test_stale_specialty_marker_does_not_hide_current_cycle(cycle_select, what, how):
    washer, _ = _washer(
        **{
            **_active("machine_wash_curtains"),
            "WashCavity_CycleSetCycleSelect": cycle_select,
        }
    )
    assert sel.WhirlpoolWasherWhatSelect(washer).current_option == what
    assert sel.WhirlpoolWasherHowSelect(washer).current_option == how
    assert sel.WhirlpoolWasherUtilityCycleSelect(washer).current_option is None


def test_sanitize_presoak_unavailable_for_cycle_capability_not_stale_specialty():
    washer, _ = _washer(
        **{**_active("machine_wash_curtains"), "WashCavity_CycleSetCycleSelect": 92}
    )
    assert washer.cycle_supports_presoak() is False
    assert sel.WhirlpoolWasherPresoakSelect(washer).available is False


def test_what_colors_from_specialty_preserves_current_how():
    washer, rec = _washer(**_active("lingerie"))
    _run(sel.WhirlpoolWasherWhatSelect(washer).async_select_option("colors"))
    wire = WASH_CYCLE_MATRIX[("colors", "wrinkle_control")]
    assert rec.calls == [_init(wire)]
    _no_specialty_keys(rec.calls[0])


def test_how_from_specialty_sends_lkg_regular_body():
    washer, rec = _washer(**_active("activewear"))
    _run(sel.WhirlpoolWasherHowSelect(washer).async_select_option("quick"))
    assert rec.calls == [_init(WASH_CYCLE_MATRIX[("regular", "quick")])]
    _no_specialty_keys(rec.calls[0])


def test_utility_from_specialty_sends_lkg_body():
    washer, rec = _washer(**_active("activewear"))
    _run(
        sel.WhirlpoolWasherUtilityCycleSelect(washer).async_select_option("drain_spin")
    )
    assert rec.calls == [_init(8)]
    _no_specialty_keys(rec.calls[0])


def test_temperature_hot_after_leaving_specialty_is_single_attribute():
    washer, rec = _washer(
        WashCavity_CycleSetCycleSelect=WASH_CYCLE_MATRIX[("colors", "normal")]
    )
    _run(sel.WhirlpoolWasherTemperatureSelect(washer).async_select_option("hot"))
    assert rec.calls == [{"WashCavity_CycleSetTemperature": "3"}]


# ---------------------------------------------------------------------------
# Regular / utility / dispenser unchanged when Specialty is idle
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("what", "how"), sorted(set(WASH_CYCLE_MATRIX) - sel.HIDDEN_WASH_PAIRS)
)
def test_every_regular_selection_body_is_lkg_and_has_no_specialty_keys(what, how):
    washer, rec = _washer(
        WashCavity_CycleSetCycleSelect=WASH_CYCLE_MATRIX[(what, "normal")]
    )
    _run(sel.WhirlpoolWasherHowSelect(washer).async_select_option(how))
    assert rec.calls == [_init(WASH_CYCLE_MATRIX[(what, how)])]
    _no_specialty_keys(rec.calls[0])


@pytest.mark.parametrize("utility", ["drain_spin", "clean_washer"])
def test_utility_bodies_have_no_specialty_keys(utility):
    washer, rec = _washer()
    _run(sel.WhirlpoolWasherUtilityCycleSelect(washer).async_select_option(utility))
    assert rec.calls == [_init({"drain_spin": 8, "clean_washer": 20}[utility])]
    _no_specialty_keys(rec.calls[0])


def test_dispenser_unchanged_while_specialty_active():
    washer, rec = _washer(**_active("activewear"))
    _run(
        sel.WhirlpoolWasherDispenserEnableSelect(washer, 1).async_select_option(
            "disabled"
        )
    )
    assert len(rec.calls) == 1
    _no_specialty_keys(rec.calls[0])


def test_specialty_source_has_no_operation_or_1003():
    text = (INTEGRATION_DIR / "specialty.py").read_text(encoding="utf-8")
    assert "1003" not in text
    assert 'OpSetOperations"' not in text
    assert "ATTR_OPS" not in text
