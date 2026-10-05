"""HA-local washer Favorite recipe tests.

Exercises the real Favorite Cycle select and real Washer recipe/dispenser
setters with send_attributes() replaced by a recorder. Nothing touches the
network and Favorites never Start the washer.
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest
from whirlpool.types import ApplianceInfo
from whirlpool.washer import Washer
from whisk_ha_harness import ServiceValidationError, Store, load_integration_modules

sel, _ = load_integration_modules()

WFW_MODEL = "WFW9620HBK3"
ATTR_OPS = "Cavity_OpSetOperations"
DISPENSE_1_ENABLE = "WashCavity_CycleSetBulkDispense1Enable"
DISPENSE_2_ENABLE = "WashCavity_CycleSetBulkDispense2Enable"
DISPENSE_2_SELECTION = "WashCavity_OpSetBulkDispense2Selection"


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
        DISPENSE_2_ENABLE: 1,
        DISPENSE_2_SELECTION: 1,
    }
    base.update(overrides)
    return {
        key: {"value": str(value), "updateTime": "1000"}
        for key, value in base.items()
    }


class _Recorder:
    def __init__(self) -> None:
        self.calls: list[dict[str, str]] = []

    async def __call__(self, attributes: dict[str, str]) -> bool:
        self.calls.append(dict(attributes))
        return True


def _washer(
    model: str = WFW_MODEL,
    **overrides: object,
) -> tuple[Washer, _Recorder]:
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


def _run(coro: Any) -> Any:
    return asyncio.run(coro)


def _favorite(washer: Washer):
    Store.DATA.clear()
    store = sel.favorites.FavoriteStore(None)
    _run(store.async_load())
    _run(store.async_initialize_appliance("washer", washer.said))
    return sel.WhirlpoolWasherFavoriteCycleSelect(washer, store=store)


def test_favorite_options_and_idle_state():
    washer, rec = _washer()
    entity = _favorite(washer)

    assert entity.options == ["none", "Socks"]
    assert entity.current_option == "none"
    assert entity.available is True
    assert rec.calls == []


def test_none_is_noop():
    washer, rec = _washer()
    entity = _favorite(washer)

    _run(entity.async_select_option("none"))

    assert entity.current_option == "none"
    assert rec.calls == []


@pytest.mark.parametrize("remote", [0, 1])
def test_socks_exact_recipe_and_omits_presoak(remote):
    washer, rec = _washer(XCat_RemoteSetRemoteControlEnable=remote)
    entity = _favorite(washer)

    _run(entity.async_select_option("Socks"))

    assert rec.calls == [
        {
            "WashCavity_CycleSetCycleSelect": "92",
            "WashCavity_CycleSetTemperature": "4",
            "WashCavity_CycleSetSpinSpeed": "5",
            "WashCavity_CycleSetSoilLevel": "2",
            "WashCavity_CycleSetExtraRinseSelect": "0",
            "WashCavity_CycleSetFresheningSelect": "1",
            "Cavity_CycleSetSteamEnable": "1",
        },
        {DISPENSE_2_SELECTION: "2"},
        {DISPENSE_2_ENABLE: "1"},
    ]
    assert "WashCavity_CycleSetPresoakTimed" not in rec.calls[0]
    assert entity.current_option == "Socks"  # stays while the recipe holds


def test_favorites_never_start():
    washer, rec = _washer()
    entity = _favorite(washer)

    _run(entity.async_select_option("Socks"))

    # Favorites configure the cycle and dispenser only. The verified
    # Dispenser 2 Selection attribute itself contains "OpSet", so the
    # Start/operations attribute must be checked specifically.
    assert not any(ATTR_OPS in call for call in rec.calls)


def test_favorites_never_touch_dispenser_1():
    washer, rec = _washer()
    entity = _favorite(washer)

    _run(entity.async_select_option("Socks"))

    assert not any(DISPENSE_1_ENABLE in call for call in rec.calls)


def test_unknown_favorite_refused_and_sends_nothing():
    washer, rec = _washer()
    entity = _favorite(washer)

    with pytest.raises(ServiceValidationError):
        _run(entity.async_select_option("not_a_favorite"))

    assert rec.calls == []
    assert entity.current_option == "none"


def test_favorite_refused_when_cycle_not_changeable():
    washer, rec = _washer(WashCavity_ChangeStatusCycleSelect=0)
    entity = _favorite(washer)

    assert entity.available is False

    with pytest.raises(ServiceValidationError):
        _run(entity.async_select_option("Socks"))

    assert rec.calls == []
    assert entity.current_option == "none"


def test_other_model_gets_no_favorite_entity():
    washer, rec = _washer(model="WTW5000DW1")

    class _Manager:
        washers = [washer]
        dryers = []
        ovens = []
        refrigerators = []
        aircons = []

    class _Entry:
        runtime_data = _Manager()

    added: list = []
    _run(sel.async_setup_entry(None, _Entry(), added.extend))

    assert "WhirlpoolWasherFavoriteCycleSelect" not in {
        type(entity).__name__ for entity in added
    }
    assert rec.calls == []
