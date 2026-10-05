"""Dryer configuration vs operation gating.

Configuration selects are gated by the awake dryer's own changeability flags,
not by Remote Enable. Start/Pause/Resume/Cancel keep their Remote Enable and
machine-state rules (button.py, unchanged).
"""

from __future__ import annotations

import asyncio
import inspect
from typing import Any

import pytest
from whirlpool.dryer import Dryer
from whirlpool.types import ApplianceInfo
from whisk_ha_harness import HomeAssistantError, load_integration_modules

sel, btn = load_integration_modules()

CONFIG_SELECTS = [
    "WhirlpoolDryerWhatSelect",
    "WhirlpoolDryerHowSelect",
    "WhirlpoolDryerUtilityCycleSelect",
    "WhirlpoolDryerDrynessSelect",
    "WhirlpoolDryerTemperatureSelect",
    "WhirlpoolDryerStaticGuardSelect",
    "WhirlpoolDryerEcoBoostSelect",
    "WhirlpoolDryerWrinkleShieldSelect",
    "WhirlpoolDryerManualDryTimeSelect",
]
AWAKE_CHANGEABLE = [
    "WhirlpoolDryerWhatSelect",
    "WhirlpoolDryerHowSelect",
    "WhirlpoolDryerUtilityCycleSelect",
    "WhirlpoolDryerTemperatureSelect",
    "WhirlpoolDryerStaticGuardSelect",
    "WhirlpoolDryerEcoBoostSelect",
    "WhirlpoolDryerWrinkleShieldSelect",
]


class _Recorder:
    def __init__(self) -> None:
        self.calls: list[dict[str, str]] = []

    async def __call__(self, attributes: dict[str, str]) -> bool:
        self.calls.append(dict(attributes))
        return True


def _dryer(remote: int, changeable: int = 1, state: int = 0) -> tuple[Dryer, _Recorder]:
    dryer = Dryer(
        None, None, None,  # type: ignore[arg-type]
        ApplianceInfo("SAIDDRYER", "Dryer", "API144", "Laundry", "WED9620HBK2", "T"),
    )
    attrs: dict[str, object] = {
        "Online": 1,
        "XCat_RemoteSetRemoteControlEnable": remote,
        "Cavity_CycleStatusMachineState": state,
        "DryCavity_CycleSetCycleSelect": 1,
        "DryCavity_CycleSetTemperature": 5,
        "DryCavity_CycleSetDryness": 4,
        "DryCavity_CycleSetWrinkleShield": 0,
        "DryCavity_CycleSetStaticGuardEnable": 0,
        "DryCavity_CycleSetEcoBoostEnable": 0,
        "DryCavity_CycleSetManualDryTime": 0,
        "DryCavity_ChangeStatusCycleSelect": changeable,
        "DryCavity_ChangeStatusDryness": changeable,
        "DryCavity_ChangeStatusManualDryTime": changeable,
        "DryCavity_ChangeStatusStaticGuard": changeable,
        "DryCavity_ChangeStatusEcoBoost": changeable,
        "DryCavity_ChangeStatusTemperature": changeable,
        "DryCavity_ChangeStatusWrinkleShield": changeable,
    }
    dryer._data_dict = {
        "attributes": {k: {"value": str(v), "updateTime": "1"} for k, v in attrs.items()}
    }
    rec = _Recorder()
    dryer.send_attributes = rec  # type: ignore[method-assign]
    return dryer, rec


def _run(coro: Any) -> Any:
    return asyncio.run(coro)


@pytest.mark.parametrize("remote", [0, 1])
@pytest.mark.parametrize("name", AWAKE_CHANGEABLE)
def test_awake_dryer_config_available_regardless_of_remote_enable(name, remote):
    dryer, _ = _dryer(remote)
    assert getattr(sel, name)(dryer).available is True


@pytest.mark.parametrize("remote", [0, 1])
def test_awake_dryer_what_sends_with_remote_enable_off_or_on(remote):
    dryer, rec = _dryer(remote)
    _run(sel.WhirlpoolDryerWhatSelect(dryer).async_select_option("towels"))
    assert len(rec.calls) == 1
    assert "Cavity_OpSetOperations" not in rec.calls[0]


@pytest.mark.parametrize("name", AWAKE_CHANGEABLE)
def test_dryer_changeability_still_gates_config(name):
    dryer, _ = _dryer(remote=1, changeable=0)
    assert getattr(sel, name)(dryer).available is False


def test_offline_dryer_config_unavailable():
    dryer, _ = _dryer(remote=0)
    entity = sel.WhirlpoolDryerWhatSelect(dryer)
    entity._attr_available = False  # WhirlpoolEntity sets this from Online
    assert entity.available is False


@pytest.mark.parametrize("name", CONFIG_SELECTS)
def test_no_dryer_config_select_checks_remote_enable(name):
    assert "get_remote_control_enabled" not in inspect.getsource(getattr(sel, name))


def test_dryer_start_still_requires_remote_enable():
    dryer, rec = _dryer(remote=0)
    start = btn.DryerCommandButton(dryer, btn.DRYER_BUTTONS[0])
    assert start.available is False
    with pytest.raises(HomeAssistantError) as err:
        _run(start.async_press())
    assert err.value.translation_key == "remote_control_disabled"
    assert rec.calls == []


def test_dryer_start_with_remote_enable_sends_only_start():
    dryer, rec = _dryer(remote=1)
    start = btn.DryerCommandButton(dryer, btn.DRYER_BUTTONS[0])
    assert start.available is True
    _run(start.async_press())
    assert rec.calls == [{"Cavity_OpSetOperations": "2"}]


def test_dryer_pause_needs_running_and_remote():
    dryer, _ = _dryer(remote=0, state=7)
    assert btn.DryerCommandButton(dryer, btn.DRYER_BUTTONS[1]).available is False
    dryer, _ = _dryer(remote=1, state=7)
    assert btn.DryerCommandButton(dryer, btn.DRYER_BUTTONS[1]).available is True
