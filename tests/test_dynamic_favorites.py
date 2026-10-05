"""User-created HA-local Favorites (washer + dryer) and dryer Favorites.

Real select.py / favorites.py through the real platform setup. The HA Store
is the in-memory harness stand-in, which keeps data per storage key so a new
setup (restart / reload) loads what an earlier one saved.
"""

from __future__ import annotations

import asyncio
from dataclasses import asdict
from typing import Any

import pytest
from whirlpool.dryer import Dryer
from whirlpool.types import ApplianceInfo
from whirlpool.washer import Washer
from whisk_ha_harness import (
    PLATFORM,
    ServiceValidationError,
    Store,
    load_integration_modules,
)

sel, _ = load_integration_modules()

OPS = "Cavity_OpSetOperations"
WFAV = "WhirlpoolWasherFavoriteCycleSelect"
DFAV = "WhirlpoolDryerFavoriteCycleSelect"
SPEC = "WhirlpoolWasherSpecialtyCycleSelect"


@pytest.fixture(autouse=True)
def _clean_store():
    Store.DATA.clear()
    yield
    Store.DATA.clear()


class _Recorder:
    def __init__(self) -> None:
        self.calls: list[dict[str, str]] = []

    async def __call__(self, attributes: dict[str, str]) -> bool:
        self.calls.append(dict(attributes))
        return True


def _data(attrs: dict[str, object]) -> dict[str, Any]:
    return {"attributes": {k: {"value": str(v), "updateTime": "1"} for k, v in attrs.items()}}


def _washer(said: str = "SAIDWASHER", **overrides: object) -> tuple[Washer, _Recorder]:
    attrs: dict[str, object] = {
        "Online": 1,
        "Cavity_CycleStatusMachineState": 0,
        "WashCavity_CycleSetCycleSelect": 24,  # Colors / Normal
        "WashCavity_CycleSetTemperature": 3,  # hot
        "WashCavity_CycleSetSpinSpeed": 3,  # medium
        "WashCavity_CycleSetSoilLevel": 2,  # heavy
        "WashCavity_CycleSetExtraRinseSelect": 1,
        "WashCavity_CycleSetPresoakTimed": 1800,
        "WashCavity_CycleSetFresheningSelect": 1,
        "Cavity_CycleSetSteamEnable": 1,
        "WashCavity_ChangeStatusCycleSelect": 1,
        "WashCavity_ChangeStatusTemperature": 1,
        "WashCavity_ChangeStatusSpinSpeed": 1,
        "WashCavity_ChangeStatusSoilLevel": 1,
        "WashCavity_ChangeStatusExtraRinse": 1,
        "WashCavity_ChangeStatusPresoakTimed": 1,
        "WashCavity_ChangeStatusFreshening": 1,
        "Cavity_ChangeStatusSteamChangeable": 1,
        "XCat_RemoteSetRemoteControlEnable": 0,
        "WashCavity_CycleSetBulkDispense1Enable": 1,
        "WashCavity_CycleSetBulkDispense2Enable": 1,
        "WashCavity_OpSetBulkDispense2Selection": 2,
        "Cavity_CycleSetDownloadAndGo": 0,
        "Cavity_CycleSetSpecialtyCycleId": 0,
        "Cavity_CycleSetCycleName": "None",
    }
    attrs.update(overrides)
    washer = Washer(
        None, None, None,  # type: ignore[arg-type]
        ApplianceInfo(said, "Washer", "API144", "Laundry", "WFW9620HBK3", "T"),
    )
    washer._data_dict = _data(attrs)
    rec = _Recorder()
    washer.send_attributes = rec  # type: ignore[method-assign]
    return washer, rec


def _dryer(remote: int = 0, **overrides: object) -> tuple[Dryer, _Recorder]:
    attrs: dict[str, object] = {
        "Online": 1,
        "XCat_RemoteSetRemoteControlEnable": remote,
        "Cavity_CycleStatusMachineState": 0,
        "DryCavity_CycleSetCycleSelect": 1,  # Regular / Normal
        "DryCavity_CycleSetTemperature": 8,  # hot_mid
        "DryCavity_CycleSetDryness": 4,  # normal
        "DryCavity_CycleSetWrinkleShield": 1,  # on
        "DryCavity_CycleSetStaticGuardEnable": 1,
        "DryCavity_CycleSetEcoBoostEnable": 0,
        "DryCavity_CycleSetManualDryTime": 0,
        "DrySys_OpSetDampNotificationToneVolume": 2,
        "DryCavity_ChangeStatusCycleSelect": 1,
        "DryCavity_ChangeStatusDryness": 1,
        "DryCavity_ChangeStatusManualDryTime": 1,
        "DryCavity_ChangeStatusStaticGuard": 1,
        "DryCavity_ChangeStatusEcoBoost": 1,
        "DryCavity_ChangeStatusTemperature": 1,
        "DryCavity_ChangeStatusWrinkleShield": 1,
    }
    attrs.update(overrides)
    dryer = Dryer(
        None, None, None,  # type: ignore[arg-type]
        ApplianceInfo("SAIDDRYER", "Dryer", "API144", "Laundry", "WED9620HBK2", "T"),
    )
    dryer._data_dict = _data(attrs)
    rec = _Recorder()
    dryer.send_attributes = rec  # type: ignore[method-assign]
    return dryer, rec


def _run(coro: Any) -> Any:
    return asyncio.run(coro)


def _setup(washer: Washer | None = None, dryer: Dryer | None = None) -> dict[str, Any]:
    manager = type(
        "M",
        (),
        {
            "washers": [washer] if washer else [],
            "dryers": [dryer] if dryer else [],
            "ovens": [],
            "refrigerators": [],
        },
    )()
    added: list = []
    _run(sel.async_setup_entry(None, type("E", (), {"runtime_data": manager})(), added.extend))
    return {type(e).__name__: e for e in added}


def _set(appliance: Any, **attrs: object) -> None:
    for key, value in attrs.items():
        appliance._data_dict["attributes"][key]["value"] = str(value)


# ---------------------------------------------------------------------------
# Naming: HA entity services
# ---------------------------------------------------------------------------


def test_save_and_delete_are_registered_entity_services_with_required_name():
    washer, _ = _washer()
    _setup(washer)
    assert set(PLATFORM.services) == {"save_favorite", "delete_favorite"}
    for schema, _func in PLATFORM.services.values():
        assert [str(k) for k in schema] == ["name"]


def test_service_handler_saves_through_the_targeted_favorite_select():
    washer, rec = _washer()
    ents = _setup(washer)
    _schema, handler = PLATFORM.services["save_favorite"]
    call = type("Call", (), {"data": {"name": "Gym Clothes"}})()
    _run(handler(ents[WFAV], call))
    assert "Gym Clothes" in ents[WFAV].options
    assert rec.calls == []  # saving sends nothing to the washer


def test_service_refuses_a_non_favorite_select():
    washer, _ = _washer()
    ents = _setup(washer)
    _schema, handler = PLATFORM.services["save_favorite"]
    call = type("Call", (), {"data": {"name": "X"}})()
    with pytest.raises(ServiceValidationError) as err:
        _run(handler(ents["WhirlpoolWasherWhatSelect"], call))
    assert err.value.translation_key == "not_a_favorite_select"


# ---------------------------------------------------------------------------
# Washer
# ---------------------------------------------------------------------------


def test_fresh_washer_gets_only_optional_socks_starter():
    washer, _ = _washer()
    fav = _setup(washer)[WFAV]
    assert fav.options == ["none", "Socks"]
    assert fav._recipe("Socks").how == "sanitize"


def test_save_captures_supported_current_configuration():
    washer, rec = _washer()
    fav = _setup(washer)[WFAV]
    _run(fav.async_save_favorite("  Gym   Clothes "))
    assert fav.options == ["none", "Socks", "Gym Clothes"]
    recipe = fav._recipe("Gym Clothes")
    assert (recipe.what, recipe.how) == ("colors", "normal")
    assert recipe.temperature == "hot"
    assert recipe.spin_speed == "medium"
    assert recipe.soil_level == "heavy"
    assert recipe.extra_rinse == "on"
    assert recipe.presoak == "30_min"
    assert recipe.fan_fresh == "on"
    assert recipe.steam == "on"
    assert recipe.dispenser_1_enable == "enabled"
    assert recipe.dispenser_2_enable == "enabled"
    assert recipe.dispenser_2_contents == "softener"
    assert fav.current_option == "Gym Clothes"  # current config IS this favorite
    assert rec.calls == []


def test_unsupported_fields_are_not_invented():
    # Whites / Sanitize (92): no Presoak, temperature locked to Extra Hot.
    washer, _ = _washer(
        WashCavity_CycleSetCycleSelect=92,
        WashCavity_CycleSetTemperature=4,
        WashCavity_CycleSetBulkDispense2Enable=2,
    )
    fav = _setup(washer)[WFAV]
    _run(fav.async_save_favorite("Sani"))
    recipe = fav._recipe("Sani")
    assert recipe.presoak is None
    assert recipe.temperature == "extra_hot"
    assert recipe.dispenser_2_enable == "disabled_next_cycle"
    assert recipe.dispenser_2_contents is None  # dispenser 2 is not enabled


def test_cold_wash_does_not_capture_steam():
    washer, _ = _washer(WashCavity_CycleSetCycleSelect=44)  # Colors / Cold Wash
    fav = _setup(washer)[WFAV]
    _run(fav.async_save_favorite("Cold"))
    assert fav._recipe("Cold").steam is None
    assert (fav._recipe("Cold").what, fav._recipe("Cold").how) == ("colors", "cold_wash")


def test_value_illegal_for_the_cycle_is_not_captured():
    # Sanitize reporting a stale non-Extra-Hot temperature: do not store it.
    washer, _ = _washer(WashCavity_CycleSetCycleSelect=92, WashCavity_CycleSetTemperature=0)
    fav = _setup(washer)[WFAV]
    _run(fav.async_save_favorite("Odd"))
    assert fav._recipe("Odd").temperature is None


def test_saved_favorite_survives_storage_reload():
    washer, _ = _washer()
    _run(_setup(washer)[WFAV].async_save_favorite("Gym Clothes"))
    reloaded = _setup(washer)[WFAV]  # new FavoriteStore, same storage key
    assert "Gym Clothes" in reloaded.options
    assert reloaded.current_option == "none"  # labels start at None on reload
    assert reloaded._recipe("Gym Clothes").temperature == "hot"


def test_selecting_saved_favorite_sends_one_combined_recipe_then_dispensers():
    washer, _ = _washer()
    _run(_setup(washer)[WFAV].async_save_favorite("Gym Clothes"))
    washer2, rec = _washer(WashCavity_CycleSetCycleSelect=1)
    fav = _setup(washer2)[WFAV]
    _run(fav.async_select_option("Gym Clothes"))
    assert rec.calls == [
        {
            "WashCavity_CycleSetCycleSelect": "24",
            "WashCavity_CycleSetTemperature": "3",
            "WashCavity_CycleSetSpinSpeed": "3",
            "WashCavity_CycleSetSoilLevel": "2",
            "WashCavity_CycleSetPresoakTimed": "1800",
            "WashCavity_CycleSetExtraRinseSelect": "1",
            "WashCavity_CycleSetFresheningSelect": "1",
            "Cavity_CycleSetSteamEnable": "1",
        },
        {"WashCavity_CycleSetBulkDispense1Enable": "1"},
        {"WashCavity_OpSetBulkDispense2Selection": "2"},
        {"WashCavity_CycleSetBulkDispense2Enable": "1"},
    ]
    assert all(OPS not in c for c in rec.calls)
    assert fav.current_option == "Gym Clothes"


def test_duplicate_name_replaces_the_user_favorite_case_insensitively():
    washer, _ = _washer()
    fav = _setup(washer)[WFAV]
    _run(fav.async_save_favorite("Gym Clothes"))
    _set(washer, WashCavity_CycleSetTemperature=0)  # now cold
    _run(fav.async_save_favorite("gym clothes"))
    user = [o for o in fav.options if o.casefold() == "gym clothes"]
    assert user == ["gym clothes"]  # one entry, newest spelling
    assert fav._recipe("gym clothes").temperature == "cold"


def test_starter_name_can_be_replaced_case_insensitively():
    washer, _ = _washer()
    fav = _setup(washer)[WFAV]
    _run(fav.async_save_favorite("socks"))
    assert fav.options == ["none", "socks"]
    assert fav._recipe("socks").what == "colors"


@pytest.mark.parametrize("name", ["", "   ", "none", "None", "x" * 51])
def test_invalid_names_are_refused(name):
    washer, _ = _washer()
    fav = _setup(washer)[WFAV]
    with pytest.raises(ServiceValidationError) as err:
        _run(fav.async_save_favorite(name))
    assert err.value.translation_key == "favorite_name_invalid"


def test_utility_cycle_cannot_be_saved():
    washer, _ = _washer(WashCavity_CycleSetCycleSelect=8)  # Drain & Spin
    fav = _setup(washer)[WFAV]
    with pytest.raises(ServiceValidationError) as err:
        _run(fav.async_save_favorite("Drain"))
    assert err.value.translation_key == "favorite_unsupported_cycle"


def test_specialty_cannot_be_saved_as_favorite():
    washer, _ = _washer()
    ents = _setup(washer)
    _run(ents[SPEC].async_select_option("diapers"))
    with pytest.raises(ServiceValidationError) as err:
        _run(ents[WFAV].async_save_favorite("Diapers Fav"))
    assert err.value.translation_key == "favorite_unsupported_cycle"


def test_saved_favorite_label_invalidates():
    washer, _ = _washer()
    ents = _setup(washer)
    _run(ents[WFAV].async_save_favorite("Gym Clothes"))
    _run(ents["WhirlpoolWasherTemperatureSelect"].async_select_option("hot"))  # recipe value
    assert ents[WFAV].current_option == "Gym Clothes"
    _run(ents["WhirlpoolWasherTemperatureSelect"].async_select_option("cold"))
    assert ents[WFAV].current_option == "none"


def test_delete_user_and_starter_favorites_persists():
    washer, _ = _washer()
    fav = _setup(washer)[WFAV]
    _run(fav.async_save_favorite("Gym Clothes"))
    _run(fav.async_delete_favorite("GYM CLOTHES"))
    _run(fav.async_delete_favorite("sOcKs"))
    assert fav.options == ["none"]
    assert _setup(washer)[WFAV].options == ["none"]
    assert fav.current_option == "none"
    with pytest.raises(ServiceValidationError) as err:
        _run(fav.async_delete_favorite("nope"))
    assert err.value.translation_key == "favorite_not_found"


def test_existing_v1_favorites_survive_and_are_deletable_without_starter_reseed():
    """Previously stored recipes stay intact and no missing-name seed runs."""
    washer_recipe = sel.favorites.WasherFavorite(what="colors", how="normal")
    dryer_recipe = sel.favorites.DryerFavorite(what="regular", how="normal")
    Store.DATA[sel.favorites.STORAGE_KEY] = {
        "washer": {"SAIDWASHER": {"Archived Wash": asdict(washer_recipe)}},
        "dryer": {"SAIDDRYER": {"Archived Dry": asdict(dryer_recipe)}},
    }
    washer, _ = _washer()
    dryer, _ = _dryer()
    ents = _setup(washer, dryer)
    assert ents[WFAV].options == ["none", "Archived Wash"]
    assert ents[DFAV].options == ["none", "Archived Dry"]
    _run(ents[WFAV].async_delete_favorite("archived wash"))
    _run(ents[DFAV].async_delete_favorite("ARCHIVED DRY"))
    reloaded = _setup(washer, dryer)
    assert reloaded[WFAV].options == ["none"]
    assert reloaded[DFAV].options == ["none"]


def test_existing_empty_storage_is_not_mistaken_for_fresh_install():
    Store.DATA[sel.favorites.STORAGE_KEY] = {}
    washer, _ = _washer()
    assert _setup(washer)[WFAV].options == ["none"]


def test_favorites_are_per_appliance():
    washer_a, _ = _washer("SAID_A")
    washer_b, _ = _washer("SAID_B")
    _run(_setup(washer_a)[WFAV].async_save_favorite("Only A"))
    assert "Only A" not in _setup(washer_b)[WFAV].options
    assert "Only A" in _setup(washer_a)[WFAV].options


# ---------------------------------------------------------------------------
# Dryer
# ---------------------------------------------------------------------------


def _stored_archived_dryer() -> None:
    """Stand in for a recipe imported by an offline legacy-store migration."""
    recipe = sel.favorites.DryerFavorite(
        what="delicates", how="normal", temperature="warm_mid", dryness="more",
        wrinkle_shield="off", static_guard="off", damp_signal="off",
    )
    Store.DATA[sel.favorites.STORAGE_KEY] = {
        "dryer": {"SAIDDRYER": {"Archived Cycle": asdict(recipe)}}
    }


def test_archived_dryer_recipe_is_loaded():
    _stored_archived_dryer()
    dryer, _ = _dryer()
    recipe = _setup(dryer=dryer)[DFAV]._recipe("Archived Cycle")
    assert (recipe.what, recipe.how) == ("delicates", "normal")
    assert recipe.temperature == "warm_mid"  # Medium
    assert recipe.dryness == "more"
    assert recipe.wrinkle_shield == "off"
    assert recipe.static_guard == "off"
    assert recipe.damp_signal == "off"
    assert recipe.eco_boost is None and recipe.manual_dry_time is None


@pytest.mark.parametrize("remote", [0, 1])
def test_archived_dryer_recipe_sends_exact_dryer_writes(remote):
    _stored_archived_dryer()
    dryer, rec = _dryer(remote)
    fav = _setup(dryer=dryer)[DFAV]
    assert fav.options == ["none", "Archived Cycle"]
    assert fav.available is True  # not gated by Remote Enable
    _run(fav.async_select_option("Archived Cycle"))
    assert rec.calls == [
        {"DryCavity_CycleSetCycleSelect": "4"},
        {"DryCavity_CycleSetTemperature": "5"},
        {"DryCavity_CycleSetDryness": "7"},
        {"DryCavity_CycleSetWrinkleShield": "0"},
        {"DryCavity_CycleSetStaticGuardEnable": "0"},
        {"DrySys_OpSetDampNotificationToneVolume": "0"},
    ]
    assert all(OPS not in c for c in rec.calls)
    assert fav.current_option == "Archived Cycle"


def test_dryer_capture_records_current_supported_settings():
    dryer, rec = _dryer()
    fav = _setup(dryer=dryer)[DFAV]
    _run(fav.async_save_favorite("Work Shirts"))
    recipe = fav._recipe("Work Shirts")
    assert (recipe.what, recipe.how) == ("regular", "normal")
    assert recipe.temperature == "hot_mid"
    assert recipe.dryness == "normal"
    assert recipe.wrinkle_shield == "on"
    assert recipe.static_guard == "on"
    assert recipe.eco_boost == "off"
    assert recipe.damp_signal == "medium"
    assert recipe.manual_dry_time is None  # Regular/Normal has no manual dry time
    assert rec.calls == []
    assert fav.current_option == "Work Shirts"


def test_dryer_capture_skips_settings_the_dryer_says_are_not_changeable():
    dryer, _ = _dryer(DryCavity_ChangeStatusDryness=0, DryCavity_ChangeStatusEcoBoost=0)
    fav = _setup(dryer=dryer)[DFAV]
    _run(fav.async_save_favorite("Partial"))
    recipe = fav._recipe("Partial")
    assert recipe.dryness is None and recipe.eco_boost is None
    assert recipe.temperature == "hot_mid"


def test_dryer_manual_dry_time_captured_only_for_timed_cycles_and_applied():
    # Regular / Timed Dry is wire 11; 60 min = 3600 s.
    dryer, _ = _dryer(DryCavity_CycleSetCycleSelect=11, DryCavity_CycleSetManualDryTime=3600)
    fav = _setup(dryer=dryer)[DFAV]
    _run(fav.async_save_favorite("Timed"))
    assert fav._recipe("Timed").manual_dry_time == "60"
    dryer2, rec = _dryer()
    _run(_setup(dryer=dryer2)[DFAV].async_select_option("Timed"))
    assert rec.calls[0] == {"DryCavity_CycleSetCycleSelect": "11"}
    assert rec.calls[-1] == {"DryCavity_CycleSetManualDryTime": "3600"}


def test_dryer_favorite_survives_storage_reload():
    dryer, _ = _dryer()
    _run(_setup(dryer=dryer)[DFAV].async_save_favorite("Work Shirts"))
    reloaded = _setup(dryer=dryer)[DFAV]
    assert reloaded.options == ["none", "Work Shirts"]
    assert reloaded.current_option == "none"


def test_dryer_label_invalidation():
    _stored_archived_dryer()
    dryer, _ = _dryer()
    ents = _setup(dryer=dryer)
    fav = ents[DFAV]
    _run(fav.async_select_option("Archived Cycle"))
    _run(ents["WhirlpoolDryerTemperatureSelect"].async_select_option("warm_mid"))  # recipe value
    assert fav.current_option == "Archived Cycle"
    _run(ents["WhirlpoolDryerEcoBoostSelect"].async_select_option("on"))  # not in recipe
    assert fav.current_option == "none"

    _run(fav.async_select_option("Archived Cycle"))
    _run(ents["WhirlpoolDryerDrynessSelect"].async_select_option("less"))
    assert fav.current_option == "none"

    _run(fav.async_select_option("Archived Cycle"))
    _run(ents["WhirlpoolDryerWhatSelect"].async_select_option("towels"))
    assert fav.current_option == "none"

    _run(fav.async_select_option("Archived Cycle"))
    _run(ents["WhirlpoolDryerUtilityCycleSelect"].async_select_option("steam_refresh"))
    assert fav.current_option == "none"


def test_dryer_incoming_updates_do_not_clear_favorite():
    _stored_archived_dryer()
    dryer, _ = _dryer()
    fav = _setup(dryer=dryer)[DFAV]
    _run(fav.async_select_option("Archived Cycle"))
    dryer.update_attributes({"DryCavity_CycleSetTemperature": "8"}, 2000)
    dryer.update_attributes({"Cavity_CycleStatusMachineState": "7"}, 3000)
    assert fav.current_option == "Archived Cycle"


def test_dryer_favorite_refused_when_cycle_not_changeable():
    _stored_archived_dryer()
    dryer, rec = _dryer(DryCavity_ChangeStatusCycleSelect=0)
    fav = _setup(dryer=dryer)[DFAV]
    assert fav.available is False
    with pytest.raises(ServiceValidationError):
        _run(fav.async_select_option("Archived Cycle"))
    assert rec.calls == []


def test_dryer_config_still_not_gated_by_remote_enable():
    dryer, _ = _dryer(remote=0)
    ents = _setup(dryer=dryer)
    for name in ("WhirlpoolDryerWhatSelect", "WhirlpoolDryerTemperatureSelect", DFAV):
        assert ents[name].available is True, name


def test_washer_and_dryer_favorites_do_not_mix():
    washer, _ = _washer()
    dryer, _ = _dryer()
    ents = _setup(washer, dryer)
    _run(ents[WFAV].async_save_favorite("Shared Name"))
    assert "Shared Name" not in ents[DFAV].options
    assert ents[DFAV].options == ["none"]
