"""Specialty latch, Colors+Cold Wash and Steam capability tests.

Real select.py / button.py / specialty.py with send_attributes() replaced by a
recorder. The Specialty selector is a local latch: it shows the Specialty HA
last applied, starts at None, is never derived from Whirlpool's (possibly
stale) DownloadAndGo/CycleName, and is cleared only by a successful HA action
that replaces the cycle.
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest
from whirlpool.types import ApplianceInfo
from whirlpool.washer import CYCLE_CAPABILITIES, WASH_CYCLE_MATRIX, Washer
from whisk_ha_harness import ServiceValidationError, load_integration_modules

sel, btn = load_integration_modules()

WFW_MODEL = "WFW9620HBK3"
ATTR_OPS = "Cavity_OpSetOperations"
DNG = "Cavity_CycleSetDownloadAndGo"
CYCLE_NAME = "Cavity_CycleSetCycleName"
DISPENSE_1_ENABLE = "WashCavity_CycleSetBulkDispense1Enable"
STALE_CURTAINS = {DNG: 1, "Cavity_CycleSetSpecialtyCycleId": 1, CYCLE_NAME: "Curtains"}


def _attrs(**overrides: object) -> dict[str, dict[str, str]]:
    base: dict[str, object] = {
        "Online": 1,
        "Cavity_CycleStatusMachineState": 0,
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
        DISPENSE_1_ENABLE: 1,
        "WashCavity_CycleSetBulkDispense2Enable": 1,
        "WashCavity_OpSetBulkDispense2Selection": 1,
        DNG: 0,
        "Cavity_CycleSetSpecialtyCycleId": 0,
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


def _washer(**overrides: object) -> tuple[Washer, _Recorder]:
    info = ApplianceInfo(
        said="SAIDWFW9620",
        name="Test",
        data_model="API144",
        category="Laundry",
        model_number=WFW_MODEL,
        serial_number="TEST",
    )
    washer = Washer(None, None, None, info)  # type: ignore[arg-type]
    washer._data_dict = {"attributes": _attrs(**overrides)}
    rec = _Recorder()
    washer.send_attributes = rec  # type: ignore[method-assign]
    return washer, rec


def _run(coro: Any) -> Any:
    return asyncio.run(coro)


class _Manager:
    def __init__(self, washer: Washer) -> None:
        self.washers = [washer]
        self.dryers: list = []
        self.ovens: list = []
        self.refrigerators: list = []
        self.aircons: list = []


class _Entry:
    def __init__(self, washer: Washer) -> None:
        self.runtime_data = _Manager(washer)


def _setup(washer: Washer) -> dict[str, Any]:
    """Run the real select platform setup; return entities by class name."""
    added: list = []
    _run(sel.async_setup_entry(None, _Entry(washer), added.extend))
    return {type(e).__name__: e for e in added}


def _latched(washer: Washer, option: str = "diapers") -> dict[str, Any]:
    ents = _setup(washer)
    _run(ents["WhirlpoolWasherSpecialtyCycleSelect"].async_select_option(option))
    assert ents["WhirlpoolWasherSpecialtyCycleSelect"].current_option == option
    return ents


# ---------------------------------------------------------------------------
# Specialty latch
# ---------------------------------------------------------------------------


def test_startup_is_none_even_with_stale_whirlpool_specialty():
    washer, rec = _washer(**STALE_CURTAINS)
    spec = _setup(washer)["WhirlpoolWasherSpecialtyCycleSelect"]
    assert spec.current_option == "none"
    assert rec.calls == []


def test_reload_starts_at_none_again():
    washer, _ = _washer()
    _latched(washer, "diapers")
    # A reload runs async_setup_entry again with the same appliance object.
    assert _setup(washer)["WhirlpoolWasherSpecialtyCycleSelect"].current_option == "none"


def test_diapers_stays_latched():
    washer, rec = _washer()
    ents = _latched(washer, "diapers")
    assert len(rec.calls) == 1
    assert ents["WhirlpoolWasherSpecialtyCycleSelect"].current_option == "diapers"


def test_another_specialty_replaces_latch():
    washer, rec = _washer()
    ents = _latched(washer, "diapers")
    spec = ents["WhirlpoolWasherSpecialtyCycleSelect"]
    _run(spec.async_select_option("blankets"))
    assert spec.current_option == "blankets"
    assert len(rec.calls) == 2


def test_none_sends_nothing_and_clears():
    washer, rec = _washer()
    ents = _latched(washer)
    spec = ents["WhirlpoolWasherSpecialtyCycleSelect"]
    _run(spec.async_select_option("none"))
    assert spec.current_option == "none"
    assert len(rec.calls) == 1  # only the original Diapers send


def test_failed_specialty_send_does_not_latch():
    washer, rec = _washer(WashCavity_ChangeStatusCycleSelect=0)
    spec = _setup(washer)["WhirlpoolWasherSpecialtyCycleSelect"]
    with pytest.raises(ServiceValidationError):
        _run(spec.async_select_option("diapers"))
    assert spec.current_option == "none"
    assert rec.calls == []


@pytest.mark.parametrize(
    ("entity", "option"),
    [
        ("WhirlpoolWasherWhatSelect", "whites"),
        ("WhirlpoolWasherHowSelect", "quick"),
        ("WhirlpoolWasherUtilityCycleSelect", "drain_spin"),
        ("WhirlpoolWasherFavoriteCycleSelect", "Socks"),
    ],
)
def test_cycle_replacing_action_clears_latch(entity, option):
    washer, rec = _washer()
    ents = _latched(washer)
    _run(ents[entity].async_select_option(option))
    assert ents["WhirlpoolWasherSpecialtyCycleSelect"].current_option == "none"
    expected_fav = option if entity == "WhirlpoolWasherFavoriteCycleSelect" else "none"
    assert ents["WhirlpoolWasherFavoriteCycleSelect"].current_option == expected_fav
    assert len(rec.calls) >= 2


def test_favorite_none_does_not_clear_latch():
    washer, rec = _washer()
    ents = _latched(washer)
    _run(ents["WhirlpoolWasherFavoriteCycleSelect"].async_select_option("none"))
    assert ents["WhirlpoolWasherSpecialtyCycleSelect"].current_option == "diapers"
    assert len(rec.calls) == 1


def test_option_change_clears_specialty_label():
    washer, _ = _washer()
    ents = _latched(washer, "activewear")
    _run(ents["WhirlpoolWasherTemperatureSelect"].async_select_option("hot"))
    assert ents["WhirlpoolWasherSpecialtyCycleSelect"].current_option == "none"


def test_failed_cycle_action_does_not_clear_latch():
    washer, _ = _washer()
    ents = _latched(washer)
    washer._data_dict["attributes"]["WashCavity_ChangeStatusCycleSelect"]["value"] = "0"
    with pytest.raises(ServiceValidationError):
        _run(ents["WhirlpoolWasherUtilityCycleSelect"].async_select_option("drain_spin"))
    assert ents["WhirlpoolWasherSpecialtyCycleSelect"].current_option == "diapers"


def test_incoming_state_updates_do_not_clear_or_set_latch():
    washer, _ = _washer()
    ents = _latched(washer, "diapers")
    spec = ents["WhirlpoolWasherSpecialtyCycleSelect"]
    # Whirlpool reports a different cycle and a stale, different CycleName.
    washer.update_attributes(
        {"WashCavity_CycleSetCycleSelect": "5", DNG: "1", CYCLE_NAME: "Curtains"}, 2000
    )
    assert spec.current_option == "diapers"
    washer.update_attributes({DNG: "0", CYCLE_NAME: "None"}, 3000)
    assert spec.current_option == "diapers"


def test_favorite_replaces_specialty_label():
    washer, _ = _washer()
    ents = _latched(washer)
    fav = ents["WhirlpoolWasherFavoriteCycleSelect"]
    _run(fav.async_select_option("Socks"))
    assert fav.current_option == "Socks"
    assert ents["WhirlpoolWasherSpecialtyCycleSelect"].current_option == "none"


# ---------------------------------------------------------------------------
# Specialty configures only: HA never sends Start
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("remote", [0, 1])
@pytest.mark.parametrize("option", ["diapers", "activewear", "blankets"])
def test_specialty_sends_configuration_only(option, remote):
    washer, rec = _washer(XCat_RemoteSetRemoteControlEnable=remote)
    _latched(washer, option)
    assert len(rec.calls) == 1
    body = rec.calls[0]
    assert ATTR_OPS not in body
    assert list(body)[:2] == [DNG, "Cavity_CycleSetSpecialtyCycleId"]
    assert len(body) == 7


def test_specialty_payload_order_unchanged():
    washer, rec = _washer()
    _latched(washer, "diapers")
    assert rec.calls == [
        {
            "Cavity_CycleSetDownloadAndGo": "1",
            "Cavity_CycleSetSpecialtyCycleId": "1",
            "WashCavity_CycleSetCycleSelect": "92",
            "WashCavity_CycleSetSoilLevel": "2",
            "WashCavity_CycleSetSpinSpeed": "5",
            "WashCavity_CycleSetTemperature": "4",
            "Cavity_CycleSetCycleName": "Diapers",
        }
    ]


# ---------------------------------------------------------------------------
# Capability: Colors + Cold Wash hidden, Steam off only for Cold Wash
# ---------------------------------------------------------------------------


def test_colors_cold_wash_is_offered_and_selectable():
    """Physically validated 2026-09-30: Colors + Cold Wash works and stays."""
    washer, rec = _washer(WashCavity_CycleSetCycleSelect=WASH_CYCLE_MATRIX[("colors", "normal")])
    how = sel.WhirlpoolWasherHowSelect(washer)
    assert "cold_wash" in how.options
    _run(how.async_select_option("cold_wash"))
    assert rec.calls[0]["WashCavity_CycleSetCycleSelect"] == "44"


def test_what_colors_keeps_cold_wash():
    washer, rec = _washer(WashCavity_CycleSetCycleSelect=WASH_CYCLE_MATRIX[("regular", "cold_wash")])
    _run(sel.WhirlpoolWasherWhatSelect(washer).async_select_option("colors"))
    assert rec.calls[0]["WashCavity_CycleSetCycleSelect"] == "44"


def test_bulky_sanitize_still_hidden():
    washer, rec = _washer(WashCavity_CycleSetCycleSelect=WASH_CYCLE_MATRIX[("bulky", "normal")])
    how = sel.WhirlpoolWasherHowSelect(washer)
    assert "sanitize" not in how.options
    with pytest.raises(ServiceValidationError):
        _run(how.async_select_option("sanitize"))
    assert rec.calls == []


def test_reported_44_still_displays():
    # Curtains' base cycle is 44; if the washer reports it, show it truthfully.
    washer, _ = _washer(WashCavity_CycleSetCycleSelect=44)
    how = sel.WhirlpoolWasherHowSelect(washer)
    assert how.current_option == "cold_wash"
    assert "cold_wash" in how.options


def test_other_cold_wash_pairs_still_selectable():
    for what in ("regular", "whites", "towels", "delicates", "bulky"):
        washer, rec = _washer(WashCavity_CycleSetCycleSelect=WASH_CYCLE_MATRIX[(what, "normal")])
        assert "cold_wash" in sel.WhirlpoolWasherHowSelect(washer).options
        _run(sel.WhirlpoolWasherHowSelect(washer).async_select_option("cold_wash"))
        assert rec.calls[0]["WashCavity_CycleSetCycleSelect"] == str(
            WASH_CYCLE_MATRIX[(what, "cold_wash")]
        )


@pytest.mark.parametrize(("what", "how"), sorted(WASH_CYCLE_MATRIX))
def test_steam_available_for_every_how_except_cold_wash(what, how):
    wire = WASH_CYCLE_MATRIX[(what, how)]
    assert bool(CYCLE_CAPABILITIES[wire].steam) is (how != "cold_wash")
    washer, _ = _washer(WashCavity_CycleSetCycleSelect=wire)
    assert sel.WhirlpoolWasherSteamSelect(washer).available is (how != "cold_wash")


# ---------------------------------------------------------------------------
# Regression: stale Specialty never hides normal controls
# ---------------------------------------------------------------------------


def test_stale_specialty_does_not_hide_normal_controls():
    washer, _ = _washer(WashCavity_CycleSetCycleSelect=5, **STALE_CURTAINS)
    ents = _setup(washer)
    assert ents["WhirlpoolWasherWhatSelect"].current_option == "delicates"
    assert ents["WhirlpoolWasherHowSelect"].current_option == "normal"
    for name in (
        "WhirlpoolWasherTemperatureSelect",
        "WhirlpoolWasherSpinSpeedSelect",
        "WhirlpoolWasherSoilLevelSelect",
        "WhirlpoolWasherExtraRinseSelect",
        "WhirlpoolWasherPresoakSelect",
        "WhirlpoolWasherFanFreshSelect",
        "WhirlpoolWasherSteamSelect",
    ):
        assert ents[name].available is True, name


def test_favorites_never_touch_dispenser_1_or_start():
    washer, rec = _washer()
    ents = _latched(washer)
    _run(ents["WhirlpoolWasherFavoriteCycleSelect"].async_select_option("Socks"))
    for body in rec.calls:
        assert ATTR_OPS not in body
        assert DISPENSE_1_ENABLE not in body
