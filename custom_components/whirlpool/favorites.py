"""Home Assistant-local washer and dryer Favorites.

All Favorites live in Home Assistant storage and can be deleted. A fresh
installation receives one optional washer example, seeded only once.
"""

from dataclasses import asdict, dataclass, fields
from typing import Any, Final

from homeassistant.helpers.storage import Store

from whirlpool.dryer import (
    ATTR_DAMP_NOTIFICATION_TONE_VOLUME,
    ATTR_DRYNESS,
    ATTR_ECO_BOOST,
    ATTR_MANUAL_DRY_TIME,
    ATTR_STATIC_GUARD,
    ATTR_TEMPERATURE,
    ATTR_WRINKLE_SHIELD,
    DRY_CYCLE_PAIR_MAP,
    DRYNESS_SET_VALUES,
    ECO_BOOST_SET_VALUES,
    QUICK_GROUP_CYCLES,
    QUICK_MDT_ALLOWED_SECONDS,
    STATIC_GUARD_SET_VALUES,
    TEMPERATURE_SET_VALUES,
    TIMED_DRY_GROUP_CYCLES,
    TIMED_DRY_MDT_ALLOWED_SECONDS,
    WRINKLE_SHIELD_SET_VALUES,
    Dryer,
)
from whirlpool.washer import Washer

STORAGE_VERSION: Final = 1
STORAGE_KEY: Final = "whirlpool.favorites"
MAX_NAME_LENGTH: Final = 50


@dataclass(frozen=True, kw_only=True)
class WasherFavorite:
    """A named washer recipe.

    A field left as None is not part of the recipe: the washer keeps the
    destination cycle's own default (options) or its current setting
    (dispensers).
    """

    what: str
    how: str
    temperature: str | None = None
    soil_level: str | None = None
    spin_speed: str | None = None
    extra_rinse: str | None = None
    fan_fresh: str | None = None
    steam: str | None = None
    presoak: str | None = None
    dispenser_1_enable: str | None = None
    dispenser_2_enable: str | None = None
    dispenser_2_contents: str | None = None


STARTER_WASHER_FAVORITES: Final[dict[str, WasherFavorite]] = {
    "Socks": WasherFavorite(
        what="whites",
        how="sanitize",
        temperature="extra_hot",
        soil_level="heavy",
        spin_speed="extra_high",
        extra_rinse="off",
        fan_fresh="on",
        steam="on",
        # Sanitize does not expose Presoak in the target washer DDM.
        presoak=None,
        dispenser_2_enable="enabled",
        dispenser_2_contents="softener",
    ),
}

# Damp Dry Signal: DrySys_OpSetDampNotificationToneVolume enum in the dryer DDM
# (0 VolumeValueOff, 2 VolumeValueMedium, 4 VolumeValueMax).
DAMP_SIGNAL_SET_VALUES: Final[dict[str, str]] = {"off": "0", "medium": "2", "max": "4"}
DAMP_SIGNAL_DISPLAY: Final[dict[str, str]] = {
    v: k for k, v in DAMP_SIGNAL_SET_VALUES.items()
}


@dataclass(frozen=True, kw_only=True)
class DryerFavorite:
    """A named dryer recipe. A field left as None is not part of the recipe."""

    what: str
    how: str
    temperature: str | None = None
    dryness: str | None = None
    wrinkle_shield: str | None = None
    static_guard: str | None = None
    damp_signal: str | None = None
    eco_boost: str | None = None
    manual_dry_time: str | None = None  # minutes, as the Manual Dry Time select


type Favorite = WasherFavorite | DryerFavorite


def normalize_name(name: str) -> str:
    """Return the Favorite name as stored, or raise ValueError if unusable."""
    cleaned = " ".join(str(name).split())
    if not cleaned or len(cleaned) > MAX_NAME_LENGTH or cleaned.casefold() == "none":
        raise ValueError(f"Invalid favorite name: {name!r}")
    return cleaned


# ---------------------------------------------------------------------------
# Capture the appliance's CURRENT configuration
# ---------------------------------------------------------------------------


def capture_washer_favorite(washer: Washer) -> WasherFavorite:
    """Build a recipe from the washer's currently reported configuration.

    Only options the current cycle offers, with a value that is legal for that
    cycle, are recorded; nothing is invented. Raises ValueError when the
    current cycle is not a What/How cycle (utility cycles cannot be captured).
    """
    pair = washer.get_wash_cycle_pair()
    if pair is None:
        raise ValueError("The current washer cycle is not a What/How cycle")

    def option(supported: bool, value: str | None, legal: list[str]) -> str | None:
        return value if supported and value is not None and value in legal else None

    dispenser_2 = washer.get_dispense_2_enable()
    return WasherFavorite(
        what=pair[0],
        how=pair[1],
        temperature=option(
            washer.cycle_supports_temperature(),
            washer.get_temperature(),
            washer.get_supported_temperatures(),
        ),
        soil_level=option(
            washer.cycle_supports_soil_level(),
            washer.get_soil_level(),
            washer.get_supported_soil_levels(),
        ),
        spin_speed=option(
            washer.cycle_supports_spin_speed(),
            washer.get_spin_speed(),
            washer.get_supported_spin_speeds(),
        ),
        extra_rinse=option(
            washer.cycle_supports_extra_rinse(),
            washer.get_extra_rinse(),
            washer.get_supported_extra_rinse_options(),
        ),
        presoak=option(
            washer.cycle_supports_presoak(),
            washer.get_presoak(),
            washer.get_supported_presoak_options(),
        ),
        fan_fresh=option(
            washer.cycle_supports_fan_fresh(), washer.get_fan_fresh(), ["off", "on"]
        ),
        steam=option(washer.cycle_supports_steam(), washer.get_steam(), ["off", "on"]),
        dispenser_1_enable=washer.get_dispense_1_enable(),
        dispenser_2_enable=dispenser_2,
        dispenser_2_contents=(
            washer.get_dispense_2_selection() if dispenser_2 == "enabled" else None
        ),
    )


def _dryer_mdt_minutes(cycle_wire: str | None) -> list[str]:
    if cycle_wire in QUICK_GROUP_CYCLES:
        return sorted((str(int(s) // 60) for s in QUICK_MDT_ALLOWED_SECONDS), key=int)
    if cycle_wire in TIMED_DRY_GROUP_CYCLES:
        return sorted(
            (str(int(s) // 60) for s in TIMED_DRY_MDT_ALLOWED_SECONDS), key=int
        )
    return []


def capture_dryer_favorite(dryer: Dryer) -> DryerFavorite:
    """Build a recipe from the dryer's currently reported configuration.

    A setting is recorded only when the dryer reports it as changeable for
    the current cycle and its value is one the library knows how to write.
    Raises ValueError when the current cycle is not a What/How cycle.
    """
    pair = dryer.get_dry_cycle_pair()
    if pair is None:
        raise ValueError("The current dryer cycle is not a What/How cycle")

    def option(
        changeable: bool | int | None, value: str | None, legal: dict[str, str]
    ) -> str | None:
        return value if changeable is True and value in legal else None

    seconds = dryer.get_manual_dry_time()
    minutes = None if seconds is None else str(seconds // 60)
    damp = dryer.get_damp_notification_tone_volume()
    return DryerFavorite(
        what=pair[0],
        how=pair[1],
        temperature=option(
            dryer.get_temperature_changeable(),
            dryer.get_temperature_str(),
            TEMPERATURE_SET_VALUES,
        ),
        dryness=option(
            dryer.get_dryness_changeable(), dryer.get_dryness_str(), DRYNESS_SET_VALUES
        ),
        wrinkle_shield=option(
            dryer.get_wrinkle_shield_changeable(),
            dryer.get_wrinkle_shield_str(),
            WRINKLE_SHIELD_SET_VALUES,
        ),
        static_guard=option(
            dryer.get_static_guard_changeable(),
            dryer.get_static_guard_str(),
            STATIC_GUARD_SET_VALUES,
        ),
        damp_signal=None if damp is None else DAMP_SIGNAL_DISPLAY.get(str(damp)),
        eco_boost=option(
            dryer.get_eco_boost_changeable(),
            dryer.get_eco_boost_str(),
            ECO_BOOST_SET_VALUES,
        ),
        manual_dry_time=(
            minutes
            if minutes in _dryer_mdt_minutes(DRY_CYCLE_PAIR_MAP.get(pair))
            else None
        ),
    )


# ---------------------------------------------------------------------------
# Apply a dryer recipe
# ---------------------------------------------------------------------------


def dryer_favorite_writes(recipe: DryerFavorite) -> list[dict[str, str]]:
    """Return the single-attribute writes that follow the cycle selection.

    The dryer protocol writes one attribute per request (see Dryer.set_*), so
    a recipe is the cycle selection followed by these, in the dryer DDM's
    FavoriteCycles order. Values are validated against the DESTINATION cycle,
    not the (possibly stale) current state. Raises ValueError for an unknown
    option or a Manual Dry Time the destination cycle does not allow.
    """
    cycle_wire = DRY_CYCLE_PAIR_MAP.get((recipe.what, recipe.how))
    if cycle_wire is None:
        raise ValueError(f"Unknown dry cycle: {recipe.what!r}/{recipe.how!r}")

    def wire(value: str, table: dict[str, str], label: str) -> str:
        if value not in table:
            raise ValueError(f"Unknown dryer {label}: {value!r}")
        return table[value]

    writes: list[dict[str, str]] = []
    if recipe.temperature is not None:
        writes.append(
            {ATTR_TEMPERATURE: wire(recipe.temperature, TEMPERATURE_SET_VALUES, "temperature")}
        )
    if recipe.dryness is not None:
        writes.append({ATTR_DRYNESS: wire(recipe.dryness, DRYNESS_SET_VALUES, "dryness")})
    if recipe.wrinkle_shield is not None:
        writes.append(
            {
                ATTR_WRINKLE_SHIELD: wire(
                    recipe.wrinkle_shield, WRINKLE_SHIELD_SET_VALUES, "wrinkle shield"
                )
            }
        )
    if recipe.static_guard is not None:
        writes.append(
            {ATTR_STATIC_GUARD: wire(recipe.static_guard, STATIC_GUARD_SET_VALUES, "static guard")}
        )
    if recipe.damp_signal is not None:
        writes.append(
            {
                ATTR_DAMP_NOTIFICATION_TONE_VOLUME: wire(
                    recipe.damp_signal, DAMP_SIGNAL_SET_VALUES, "damp signal"
                )
            }
        )
    if recipe.eco_boost is not None:
        writes.append(
            {ATTR_ECO_BOOST: wire(recipe.eco_boost, ECO_BOOST_SET_VALUES, "eco boost")}
        )
    if recipe.manual_dry_time is not None:
        if recipe.manual_dry_time not in _dryer_mdt_minutes(cycle_wire):
            raise ValueError(
                f"Manual dry time {recipe.manual_dry_time!r} is not valid for "
                f"{recipe.what}/{recipe.how}"
            )
        writes.append({ATTR_MANUAL_DRY_TIME: str(int(recipe.manual_dry_time) * 60)})
    return writes


async def apply_dryer_favorite(dryer: Dryer, recipe: DryerFavorite) -> bool:
    """Send a dryer recipe: cycle selection first, then each setting.

    Never sends an operation, so it never Starts the dryer. Returns False
    (after sending nothing further) as soon as a write is refused.
    """
    writes = dryer_favorite_writes(recipe)  # validate everything before sending
    if not await dryer.set_dry_cycle_pair(recipe.what, recipe.how):
        return False
    for body in writes:
        if not await dryer.send_attributes(body):
            return False
    return True


# ---------------------------------------------------------------------------
# Persistent storage of all Favorites
# ---------------------------------------------------------------------------

_KINDS: Final[dict[str, type]] = {"washer": WasherFavorite, "dryer": DryerFavorite}


def _from_dict(kind: str, data: dict[str, Any]) -> Favorite | None:
    """Rebuild a recipe from storage, ignoring unknown keys; None if unusable."""
    cls = _KINDS[kind]
    known = {f.name for f in fields(cls)}
    try:
        return cls(**{k: v for k, v in data.items() if k in known})
    except TypeError:
        return None


class FavoriteStore:
    """Per-appliance Favorites in HA storage, with one-time fresh-install seed.

    The ``_initialized`` marker persists even for an empty Favorite list, so
    deleting the starter cannot cause it to reappear on a later setup.
    """

    def __init__(self, hass: Any) -> None:
        self._store: Store[dict[str, Any]] = Store(hass, STORAGE_VERSION, STORAGE_KEY)
        self._data: dict[str, Any] = {}
        self._fresh_install = False

    async def async_load(self) -> None:
        loaded = await self._store.async_load()
        if loaded is not None and not isinstance(loaded, dict):
            raise ValueError("Invalid Favorites storage payload")
        self._fresh_install = loaded is None
        self._data = loaded if loaded is not None else {}

    async def async_initialize_appliance(self, kind: str, said: str) -> None:
        """Initialize once; seed Socks only when the whole Store was absent.

        A v1 Store that already exists contains user-created Favorites and is
        retained unchanged. Importing pre-v2 implicit recipes into that Store
        is a separate private, offline cutover step; it must finish before
        deploying this code to an older installation.
        """
        if kind not in _KINDS:
            raise ValueError(f"Unknown Favorite kind: {kind}")
        markers = self._data.setdefault("_initialized", {}).setdefault(kind, [])
        if said in markers:
            return
        if self._fresh_install and kind == "washer":
            current = self._data.setdefault(kind, {}).setdefault(said, {})
            for name, recipe in STARTER_WASHER_FAVORITES.items():
                current.setdefault(name, asdict(recipe))
        markers.append(said)
        await self._store.async_save(self._data)

    def favorites(self, kind: str, said: str) -> dict[str, Favorite]:
        """Return all stored Favorites of one appliance, in saved order."""
        result: dict[str, Favorite] = {}
        for name, data in self._data.get(kind, {}).get(said, {}).items():
            recipe = _from_dict(kind, data)
            if recipe is not None:
                result[name] = recipe
        return result

    async def async_save(self, kind: str, said: str, name: str, recipe: Favorite) -> str:
        """Save ``recipe`` under ``name``; a same-named Favorite is replaced.

        Names compare case-insensitively; the replaced Favorite keeps its
        position and takes the newly typed spelling. Returns the stored name.
        """
        current = self._data.setdefault(kind, {}).setdefault(said, {})
        updated: dict[str, dict[str, Any]] = {}
        replaced = False
        for existing, data in current.items():
            if existing.casefold() == name.casefold():
                updated[name] = asdict(recipe)
                replaced = True
            else:
                updated[existing] = data
        if not replaced:
            updated[name] = asdict(recipe)
        self._data[kind][said] = updated
        await self._store.async_save(self._data)
        return name

    async def async_delete(self, kind: str, said: str, name: str) -> bool:
        """Delete any Favorite by name (case-insensitive)."""
        current = self._data.get(kind, {}).get(said, {})
        match = next((n for n in current if n.casefold() == name.casefold()), None)
        if match is None:
            return False
        del current[match]
        await self._store.async_save(self._data)
        return True
