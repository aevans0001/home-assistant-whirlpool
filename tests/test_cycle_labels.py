"""Favorite / Specialty label persistence and invalidation (washer).

Both selectors show the recipe HA last applied while it still describes the
configuration. An HA action that changes a recipe-defining field clears it;
incoming Whirlpool updates never do. Real select.py via the real platform
setup, send_attributes() replaced by a recorder.
"""

from __future__ import annotations

import asyncio
from dataclasses import asdict
from typing import Any

import pytest
from whirlpool.types import ApplianceInfo
from whirlpool.washer import WASH_CYCLE_MATRIX, Washer
from whisk_ha_harness import ServiceValidationError, Store, load_integration_modules

sel, _ = load_integration_modules()

DNG = "Cavity_CycleSetDownloadAndGo"
CYCLE_NAME = "Cavity_CycleSetCycleName"
SPEC = "WhirlpoolWasherSpecialtyCycleSelect"
FAV = "WhirlpoolWasherFavoriteCycleSelect"


@pytest.fixture(autouse=True)
def _sample_stored_favorites():
    """Synthetic previously saved recipes for label behavior tests."""
    Store.DATA.clear()
    recipes = {
        "Example A": sel.favorites.WasherFavorite(
            what="delicates", how="normal", temperature="cool", soil_level="light",
            spin_speed="low", extra_rinse="on", fan_fresh="on", steam="off",
            dispenser_2_enable="enabled", dispenser_2_contents="softener",
        ),
        "Example B": sel.favorites.WasherFavorite(
            what="regular", how="heavy_duty", temperature="warm", soil_level="normal",
            spin_speed="high", extra_rinse="off", fan_fresh="on", steam="off",
            presoak="off", dispenser_2_enable="disabled_next_cycle",
        ),
        "Socks": sel.favorites.STARTER_WASHER_FAVORITES["Socks"],
    }
    Store.DATA[sel.favorites.STORAGE_KEY] = {
        "washer": {"SAIDWFW9620": {name: asdict(recipe) for name, recipe in recipes.items()}}
    }
    yield
    Store.DATA.clear()


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
        "WashCavity_CycleSetBulkDispense1Enable": 1,
        "WashCavity_CycleSetBulkDispense2Enable": 1,
        "WashCavity_OpSetBulkDispense2Selection": 1,
        "WashCavity_OpSetBulkDispense1Concentration": 2,
        "WashCavity_OpSetBulkDispense2Concentration": 2,
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
    info = ApplianceInfo("SAIDWFW9620", "Test", "API144", "Laundry", "WFW9620HBK3", "T")
    washer = Washer(None, None, None, info)  # type: ignore[arg-type]
    washer._data_dict = {"attributes": _attrs(**overrides)}
    rec = _Recorder()
    washer.send_attributes = rec  # type: ignore[method-assign]
    return washer, rec


def _run(coro: Any) -> Any:
    return asyncio.run(coro)


class _Entry:
    def __init__(self, washer: Washer) -> None:
        self.runtime_data = type(
            "M", (), {"washers": [washer], "dryers": [], "ovens": [], "refrigerators": []}
        )()


def _setup(washer: Washer) -> dict[str, Any]:
    added: list = []
    _run(sel.async_setup_entry(None, _Entry(washer), added.extend))
    ents: dict[str, Any] = {}
    for e in added:
        name = type(e).__name__
        if name.startswith("WhirlpoolWasherDispenser") and hasattr(e, "_dispenser"):
            name = f"{name}{e._dispenser}"
        ents[name] = e
    return ents


def _apply(kind: str, option: str, **overrides: object) -> tuple[dict[str, Any], _Recorder]:
    washer, rec = _washer(**overrides)
    ents = _setup(washer)
    _run(ents[kind].async_select_option(option))
    assert ents[kind].current_option == option
    return ents, rec


def _ops(rec: _Recorder) -> list[dict[str, str]]:
    return [c for c in rec.calls if "Cavity_OpSetOperations" in c]


# ---------------------------------------------------------------------------
# Favorite
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("option", ["Example A", "Example B", "Socks"])
def test_favorite_persists_after_apply_and_never_starts(option):
    ents, rec = _apply(FAV, option)
    assert ents[FAV].current_option == option
    assert _ops(rec) == []


def test_incoming_updates_do_not_clear_favorite():
    ents, _ = _apply(FAV, "Example B")
    washer = ents[FAV]._appliance
    washer.update_attributes({"WashCavity_CycleSetCycleSelect": "1"}, 2000)
    washer.update_attributes({"WashCavity_CycleSetTemperature": "4", DNG: "1"}, 3000)
    washer.update_attributes({"Cavity_CycleStatusMachineState": "7"}, 4000)
    assert ents[FAV].current_option == "Example B"


@pytest.mark.parametrize(
    ("entity", "option"),
    [
        ("WhirlpoolWasherTemperatureSelect", "hot"),
        ("WhirlpoolWasherSpinSpeedSelect", "medium"),
        ("WhirlpoolWasherSoilLevelSelect", "heavy"),
        ("WhirlpoolWasherExtraRinseSelect", "on"),
        ("WhirlpoolWasherPresoakSelect", "30_min"),
        ("WhirlpoolWasherFanFreshSelect", "off"),
        ("WhirlpoolWasherSteamSelect", "on"),
        ("WhirlpoolWasherDispenserEnableSelect2", "enabled"),
    ],
)
def test_changing_a_recipe_defining_field_clears_favorite(entity, option):
    # Use a cycle where every option entity is available.
    ents, _ = _apply(FAV, "Example B", WashCavity_CycleSetCycleSelect=67)
    _run(ents[entity].async_select_option(option))
    assert ents[FAV].current_option == "none"


@pytest.mark.parametrize(
    ("entity", "option"),
    [
        ("WhirlpoolWasherTemperatureSelect", "warm"),
        ("WhirlpoolWasherSpinSpeedSelect", "high"),
        ("WhirlpoolWasherSoilLevelSelect", "normal"),
        ("WhirlpoolWasherPresoakSelect", "off"),
        ("WhirlpoolWasherFanFreshSelect", "on"),
    ],
)
def test_reselecting_the_recipe_value_keeps_favorite(entity, option):
    ents, _ = _apply(FAV, "Example B", WashCavity_CycleSetCycleSelect=67)
    _run(ents[entity].async_select_option(option))
    assert ents[FAV].current_option == "Example B"


@pytest.mark.parametrize(
    ("entity", "option"),
    [
        ("WhirlpoolWasherDispenserEnableSelect1", "disabled"),
        ("WhirlpoolWasherDispenserConcentrationSelect1", "3x"),
    ],
)
def test_fields_the_recipe_does_not_define_keep_favorite(entity, option):
    ents, _ = _apply(FAV, "Example B", WashCavity_CycleSetCycleSelect=67)
    _run(ents[entity].async_select_option(option))
    assert ents[FAV].current_option == "Example B"


def test_dispenser_2_contents_clears_only_when_recipe_defines_it():
    ents, _ = _apply(FAV, "Example A", WashCavity_CycleSetCycleSelect=5)
    _run(ents["WhirlpoolWasherDispenser2ContentsSelect"].async_select_option("detergent"))
    assert ents[FAV].current_option == "none"


def test_presoak_change_clears_favorite_that_relies_on_cycle_default():
    # Example A does not set Presoak; any Presoak edit changes the recipe.
    ents, _ = _apply(FAV, "Example A", WashCavity_CycleSetCycleSelect=5)
    _run(ents["WhirlpoolWasherPresoakSelect"].async_select_option("off"))
    assert ents[FAV].current_option == "none"


@pytest.mark.parametrize(
    ("entity", "option"),
    [
        ("WhirlpoolWasherWhatSelect", "whites"),
        ("WhirlpoolWasherHowSelect", "quick"),
        ("WhirlpoolWasherUtilityCycleSelect", "drain_spin"),
        (SPEC, "diapers"),
    ],
)
def test_cycle_replacement_clears_favorite(entity, option):
    ents, _ = _apply(FAV, "Example B")
    _run(ents[entity].async_select_option(option))
    assert ents[FAV].current_option == "none"


def test_another_favorite_replaces_favorite():
    ents, _ = _apply(FAV, "Example B")
    _run(ents[FAV].async_select_option("Socks"))
    assert ents[FAV].current_option == "Socks"


def test_favorite_none_clears_label_and_sends_nothing():
    ents, rec = _apply(FAV, "Example B")
    sent = len(rec.calls)
    _run(ents[FAV].async_select_option("none"))
    assert ents[FAV].current_option == "none"
    assert len(rec.calls) == sent


def test_failed_option_write_keeps_favorite():
    ents, _ = _apply(FAV, "Example B", WashCavity_CycleSetCycleSelect=67)
    washer = ents[FAV]._appliance
    washer._data_dict["attributes"]["WashCavity_ChangeStatusTemperature"]["value"] = "0"
    with pytest.raises(ServiceValidationError):
        _run(ents["WhirlpoolWasherTemperatureSelect"].async_select_option("hot"))
    assert ents[FAV].current_option == "Example B"


# ---------------------------------------------------------------------------
# Specialty
# ---------------------------------------------------------------------------


def test_specialty_starts_none_even_with_stale_whirlpool_values():
    washer, _ = _washer(**{DNG: 1, CYCLE_NAME: "Diapers", "WashCavity_CycleSetCycleSelect": 92})
    assert _setup(washer)[SPEC].current_option == "none"


def test_diapers_persists_through_incoming_updates():
    ents, rec = _apply(SPEC, "diapers")
    washer = ents[SPEC]._appliance
    washer.update_attributes({"WashCavity_CycleSetCycleSelect": "92", DNG: "1"}, 2000)
    washer.update_attributes({DNG: "0", CYCLE_NAME: "None"}, 3000)
    washer.update_attributes({"Cavity_ChangeStatusSteamChangeable": "1"}, 4000)
    assert ents[SPEC].current_option == "diapers"
    assert _ops(rec) == []


@pytest.mark.parametrize(
    ("entity", "option"),
    [
        ("WhirlpoolWasherTemperatureSelect", "cold"),
        ("WhirlpoolWasherSpinSpeedSelect", "medium"),
        ("WhirlpoolWasherSoilLevelSelect", "light"),
        ("WhirlpoolWasherExtraRinseSelect", "on"),
        ("WhirlpoolWasherPresoakSelect", "30_min"),
        ("WhirlpoolWasherFanFreshSelect", "on"),
        ("WhirlpoolWasherSteamSelect", "on"),
        ("WhirlpoolWasherWhatSelect", "whites"),
        ("WhirlpoolWasherHowSelect", "quick"),
        ("WhirlpoolWasherUtilityCycleSelect", "drain_spin"),
        (FAV, "Example B"),
    ],
)
def test_defining_change_clears_activewear(entity, option):
    # Activewear's base is Regular/Normal (1), so all option entities apply.
    ents, _ = _apply(SPEC, "activewear")
    _run(ents[entity].async_select_option(option))
    assert ents[SPEC].current_option == "none"


def test_reselecting_preset_value_keeps_specialty():
    ents, _ = _apply(SPEC, "activewear")  # Warm / ExtraHigh / Heavy
    _run(ents["WhirlpoolWasherTemperatureSelect"].async_select_option("warm"))
    _run(ents["WhirlpoolWasherSoilLevelSelect"].async_select_option("heavy"))
    assert ents[SPEC].current_option == "activewear"


def test_dispenser_change_keeps_specialty():
    ents, _ = _apply(SPEC, "activewear")
    _run(ents["WhirlpoolWasherDispenserEnableSelect2"].async_select_option("disabled"))
    assert ents[SPEC].current_option == "activewear"


def test_another_specialty_replaces():
    ents, _ = _apply(SPEC, "diapers")
    _run(ents[SPEC].async_select_option("blankets"))
    assert ents[SPEC].current_option == "blankets"
    assert ents[FAV].current_option == "none"


def test_reload_resets_both_labels():
    ents, _ = _apply(SPEC, "diapers")
    fresh = _setup(ents[SPEC]._appliance)
    assert fresh[SPEC].current_option == "none"
    assert fresh[FAV].current_option == "none"


# ---------------------------------------------------------------------------
# Colors + Cold Wash: hidden in the normal selects; cycle 44 still usable
# ---------------------------------------------------------------------------


def test_curtains_specialty_still_sends_cycle_44():
    _, rec = _apply(SPEC, "machine_wash_curtains")
    assert rec.calls[0]["WashCavity_CycleSetCycleSelect"] == "44"
    assert WASH_CYCLE_MATRIX[("colors", "cold_wash")] == 44  # library untouched
