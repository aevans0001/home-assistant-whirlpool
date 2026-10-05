"""Test-only loader that runs the REAL integration select.py / button.py.

Home Assistant is not needed and is not imported. Minimal stand-ins for the
few Home Assistant names these two modules use are put in ``sys.modules``
only while the modules load, and the previous entries are restored
afterwards, so a real Home Assistant install (if one exists) is not affected.

The integration package is loaded under the synthetic, test-only package name
``whisk_integration_pkg``. That package has ``__path__`` pointing at
custom_components/whirlpool, which lets the relative imports in select.py and
button.py (``.const``, ``.entity``, ``.washer_staging``) resolve to the real
files. custom_components/whirlpool/__init__.py is NOT executed, and
custom_components/whirlpool is NOT placed on sys.path, so the stdlib ``select``
module cannot be shadowed. Top-level ``whirlpool`` stays the real
sixth-sense library (conftest.py guarantees that).
"""

from __future__ import annotations

import importlib
import sys
import types
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any, ClassVar

PKG_NAME = "whisk_integration_pkg"
_INTEGRATION_PKG_DIR = Path(__file__).resolve().parent.parent / "custom_components" / "whirlpool"


class HomeAssistantError(Exception):
    """Stand-in for homeassistant.exceptions.HomeAssistantError."""

    def __init__(self, *args: object, **kwargs: Any) -> None:
        super().__init__(*args)
        self.translation_key = kwargs.get("translation_key")
        self.translation_domain = kwargs.get("translation_domain")
        self.translation_placeholders = kwargs.get("translation_placeholders")


class ServiceValidationError(HomeAssistantError):
    """Stand-in for homeassistant.exceptions.ServiceValidationError."""


class ConfigEntryAuthFailed(HomeAssistantError):
    """Unused stand-in (imported by nothing under test)."""


class Entity:
    """Stand-in for homeassistant.helpers.entity.Entity (no hass needed)."""

    _attr_available: bool = True
    entity_id: str = "test.entity"

    @property
    def available(self) -> bool:
        return self._attr_available

    def async_write_ha_state(self) -> None:
        """No-op: no state machine in unit tests."""

    async def async_added_to_hass(self) -> None:
        """Overridden by WhirlpoolEntity."""

    async def async_will_remove_from_hass(self) -> None:
        """Overridden by WhirlpoolEntity."""


class SelectEntity(Entity):
    """Stand-in for homeassistant.components.select.SelectEntity."""

    _attr_options: list[str] = []

    @property
    def options(self) -> list[str]:
        return self._attr_options


class ButtonEntity(Entity):
    """Stand-in for homeassistant.components.button.ButtonEntity."""


@dataclass(frozen=True, kw_only=True)
class _EntityDescription:
    key: str
    translation_key: str | None = None
    options: list[str] | None = None
    unit_of_measurement: str | None = None


class UnitOfTemperature(StrEnum):
    CELSIUS = "°C"


def _callback(func: Any) -> Any:
    return func


class Store:
    """In-memory stand-in for homeassistant.helpers.storage.Store.

    Data is kept per storage key at class level, so a second Store for the
    same key (a restart or integration reload) loads what the first one saved.
    """

    DATA: ClassVar[dict[str, Any]] = {}

    def __init__(self, hass: Any, version: int, key: str) -> None:
        self.version = version
        self.key = key

    async def async_load(self) -> Any:
        import copy

        return copy.deepcopy(Store.DATA.get(self.key))

    async def async_save(self, data: Any) -> None:
        import copy

        Store.DATA[self.key] = copy.deepcopy(data)


class _Platform:
    """Stand-in for the current EntityPlatform: records entity services."""

    def __init__(self) -> None:
        self.services: dict[str, tuple[Any, Any]] = {}

    def async_register_entity_service(self, name: str, schema: Any, func: Any) -> None:
        self.services[name] = (schema, func)


PLATFORM = _Platform()


def _async_get_current_platform() -> _Platform:
    return PLATFORM


def _stub_modules() -> dict[str, types.ModuleType]:
    def mod(name: str, **attrs: Any) -> types.ModuleType:
        m = types.ModuleType(name)
        m.__dict__.update(attrs)
        return m

    return {
        "homeassistant": mod("homeassistant"),
        "homeassistant.components": mod("homeassistant.components"),
        "homeassistant.components.select": mod(
            "homeassistant.components.select",
            SelectEntity=SelectEntity,
            SelectEntityDescription=_EntityDescription,
        ),
        "homeassistant.components.button": mod(
            "homeassistant.components.button",
            ButtonEntity=ButtonEntity,
            ButtonEntityDescription=_EntityDescription,
        ),
        "homeassistant.const": mod(
            "homeassistant.const", UnitOfTemperature=UnitOfTemperature
        ),
        "homeassistant.core": mod(
            "homeassistant.core", HomeAssistant=object, callback=_callback
        ),
        "homeassistant.exceptions": mod(
            "homeassistant.exceptions",
            HomeAssistantError=HomeAssistantError,
            ServiceValidationError=ServiceValidationError,
            ConfigEntryAuthFailed=ConfigEntryAuthFailed,
        ),
        "homeassistant.helpers": mod("homeassistant.helpers"),
        "homeassistant.helpers.entity": mod(
            "homeassistant.helpers.entity", Entity=Entity
        ),
        "homeassistant.helpers.device_registry": mod(
            "homeassistant.helpers.device_registry", DeviceInfo=dict
        ),
        "homeassistant.helpers.entity_platform": mod(
            "homeassistant.helpers.entity_platform",
            AddConfigEntryEntitiesCallback=object,
            async_get_current_platform=_async_get_current_platform,
        ),
        "homeassistant.helpers.storage": mod(
            "homeassistant.helpers.storage", Store=Store
        ),
    }


def load_integration_modules() -> tuple[types.ModuleType, types.ModuleType]:
    """Return the real (select, button) modules loaded under PKG_NAME."""
    if f"{PKG_NAME}.select" in sys.modules:
        return sys.modules[f"{PKG_NAME}.select"], sys.modules[f"{PKG_NAME}.button"]

    stubs = _stub_modules()
    saved = {name: sys.modules.get(name) for name in stubs}
    pkg = types.ModuleType(PKG_NAME)
    pkg.__path__ = [str(_INTEGRATION_PKG_DIR)]
    pkg.WhirlpoolConfigEntry = object  # type alias target only
    try:
        sys.modules.update(stubs)
        sys.modules[PKG_NAME] = pkg
        select_mod = importlib.import_module(f"{PKG_NAME}.select")
        button_mod = importlib.import_module(f"{PKG_NAME}.button")
    finally:
        for name, previous in saved.items():
            if previous is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = previous
    return select_mod, button_mod
