"""Button platform for the Whirlpool Appliances integration.

Modified from the upstream home-assistant/core `whirlpool` integration to
add Start/Pause/Resume/Cancel buttons for API144 legacy-HTTP washers and
dryers (WasherDryerCommandButton and its four subclasses below), alongside
the pre-existing oven Stop button. See CHANGES.md in this fork for the
full list of modifications and their evidence basis.
"""

from dataclasses import dataclass
from typing import override

from whirlpool.dryer import Dryer
from whirlpool.dryer import MachineState as DryerMachineState
from whirlpool.oven import Cavity as OvenCavity, Oven
from whirlpool.washer import Washer
from whirlpool.washer import MachineState as WasherMachineState

from homeassistant.components.button import ButtonEntity, ButtonEntityDescription
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import WhirlpoolConfigEntry
from .const import DOMAIN
from .entity import WhirlpoolEntity, WhirlpoolOvenEntity

PARALLEL_UPDATES = 1

# --- Command availability tables -------------------------------------------
#
# Evidence: a live, server-delivered Device Data Model (DDM) capture and its
# accompanying rule-engine ("ApplianceRulesets") for two API144 laundry
# models (WFW9620HBK3 washer, WED9620HBK2 dryer). Every rule below requires
# Washer.get_remote_control_enabled() / Dryer.get_remote_control_enabled()
# to be True in addition to the machine-state membership shown - that check
# is applied uniformly by WasherDryerCommandButton.available and
# async_press() below, so it is not repeated per entry here.
#
# Washer and dryer are NOT assumed identical: the proven rule set has real,
# evidenced differences (dryer's Cancel rule omits DelayCountdownMode, which
# the washer's does not) - see the "cancel" entries below.
#
# This table is intentionally the ONLY place command availability is
# decided. It is Home Assistant-layer policy, not protocol library
# behavior - see LaundryCommandsMixin in the whirlpool library fork for the
# corresponding protocol-level (has-data-been-fetched) guard.
WASHER_COMMAND_STATES: dict[str, frozenset[WasherMachineState]] = {
    "start": frozenset(
        {
            WasherMachineState.Standby,
            WasherMachineState.Setting,
            WasherMachineState.Complete,
        }
    ),
    "pause": frozenset(
        {WasherMachineState.RunningMainCycle, WasherMachineState.RunningPostCycle}
    ),
    "resume": frozenset({WasherMachineState.Pause}),
    "cancel": frozenset(
        {
            WasherMachineState.DelayCountdownMode,
            WasherMachineState.Pause,
            WasherMachineState.RunningMainCycle,
            WasherMachineState.RunningPostCycle,
        }
    ),
}

DRYER_COMMAND_STATES: dict[str, frozenset[DryerMachineState]] = {
    "start": frozenset(
        {
            DryerMachineState.Standby,
            DryerMachineState.Setting,
            DryerMachineState.Complete,
        }
    ),
    "pause": frozenset(
        {DryerMachineState.RunningMainCycle, DryerMachineState.RunningPostCycle}
    ),
    "resume": frozenset({DryerMachineState.Pause}),
    # No DelayCountdownMode here: the live DDM's dryer ruleset has no
    # equivalent of the washer's wider Cancel condition. Do not "fix" this
    # to match the washer without new DDM evidence for the dryer.
    "cancel": frozenset(
        {
            DryerMachineState.Pause,
            DryerMachineState.RunningMainCycle,
            DryerMachineState.RunningPostCycle,
        }
    ),
}


@dataclass(frozen=True, kw_only=True)
class WhirlpoolLaundryButtonDescription(ButtonEntityDescription):
    """Describes one washer/dryer command button."""

    command: str  # matches a whirlpool Washer/Dryer method name, e.g. "start"


WASHER_BUTTONS: tuple[WhirlpoolLaundryButtonDescription, ...] = (
    WhirlpoolLaundryButtonDescription(
        key="start", translation_key="washer_start", command="start"
    ),
    WhirlpoolLaundryButtonDescription(
        key="pause", translation_key="washer_pause", command="pause"
    ),
    WhirlpoolLaundryButtonDescription(
        key="resume", translation_key="washer_resume", command="resume"
    ),
    WhirlpoolLaundryButtonDescription(
        key="cancel", translation_key="washer_cancel", command="cancel"
    ),
)

DRYER_BUTTONS: tuple[WhirlpoolLaundryButtonDescription, ...] = (
    WhirlpoolLaundryButtonDescription(
        key="start", translation_key="dryer_start", command="start"
    ),
    WhirlpoolLaundryButtonDescription(
        key="pause", translation_key="dryer_pause", command="pause"
    ),
    WhirlpoolLaundryButtonDescription(
        key="resume", translation_key="dryer_resume", command="resume"
    ),
    WhirlpoolLaundryButtonDescription(
        key="cancel", translation_key="dryer_cancel", command="cancel"
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: WhirlpoolConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the button platform."""
    appliances_manager = config_entry.runtime_data

    washer_buttons = [
        WasherCommandButton(washer, description)
        for washer in appliances_manager.washers
        for description in WASHER_BUTTONS
    ]
    dryer_buttons = [
        DryerCommandButton(dryer, description)
        for dryer in appliances_manager.dryers
        for description in DRYER_BUTTONS
    ]
    oven_buttons = [
        WhirlpoolOvenStopButton(oven, cavity)
        for oven in appliances_manager.ovens
        for cavity in (OvenCavity.Upper, OvenCavity.Lower)
        if oven.get_oven_cavity_exists(cavity)
    ]

    async_add_entities([*washer_buttons, *dryer_buttons, *oven_buttons])


class WasherDryerCommandButton(WhirlpoolEntity, ButtonEntity):
    """A Start/Pause/Resume/Cancel button for a washer or dryer.

    Availability and the press-time guard both go through
    _is_command_allowed(); the press-time check is not optional even when
    the entity is shown available, since state can change between Home
    Assistant computing `available` and the user actually pressing the
    button (a real appliance state transition, or another client's action,
    in that window is not a bug - it is exactly why this is re-checked).
    """

    entity_description: WhirlpoolLaundryButtonDescription
    _command_states: dict[str, frozenset]

    def __init__(
        self,
        appliance: Washer | Dryer,
        description: WhirlpoolLaundryButtonDescription,
    ) -> None:
        """Initialize the command button."""
        super().__init__(appliance, unique_id_suffix=f"-{description.key}")
        self.entity_description = description

    def _is_command_allowed(self) -> tuple[bool, str | None]:
        """Return (allowed, translation_key_if_blocked).

        translation_key_if_blocked is one of the `exceptions` keys in
        strings.json, or None when the command is currently allowed.
        """
        if self._appliance.get_remote_control_enabled() is not True:
            return False, "remote_control_disabled"
        allowed_states = self._command_states.get(
            self.entity_description.command, frozenset()
        )
        if self._appliance.get_machine_state() not in allowed_states:
            return False, "invalid_machine_state_for_command"
        return True, None

    @property
    @override
    def available(self) -> bool:
        """Return whether this command can currently be used.

        Combines the base connectivity/online check (WhirlpoolEntity sets
        _attr_available from get_online() on every push update) with the
        Remote-Enable/MachineState command-gating check above.
        """
        allowed, _reason = self._is_command_allowed()
        return super().available and allowed

    @override
    async def async_press(self) -> None:
        """Send the command, re-validating state first to avoid a race
        between Home Assistant computing `available` and this press."""
        allowed, reason = self._is_command_allowed()
        if not allowed:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key=reason,
                translation_placeholders={
                    "device_name": self._appliance.name or self._appliance.said
                },
            )
        self._check_service_request(
            await getattr(self._appliance, self.entity_description.command)()
        )
        # No explicit state refresh here on purpose: the legacy HTTP
        # appliance manager already keeps a persistent push event socket
        # open for this account (see whirlpool.httpapi.appliancesmanager /
        # whirlpool.eventsocket), and the appliance's own resulting state
        # change arrives over it the same way any other externally-caused
        # transition does. Polling or sleeping here would duplicate that
        # mechanism rather than reuse it.


class WasherCommandButton(WasherDryerCommandButton):
    """Start/Pause/Resume/Cancel button for a washer."""

    _appliance: Washer
    _command_states = WASHER_COMMAND_STATES


class DryerCommandButton(WasherDryerCommandButton):
    """Start/Pause/Resume/Cancel button for a dryer."""

    _appliance: Dryer
    _command_states = DRYER_COMMAND_STATES


class WhirlpoolOvenStopButton(WhirlpoolOvenEntity, ButtonEntity):
    """Button to stop the current cook in an oven cavity."""

    _appliance: Oven

    def __init__(self, appliance: Oven, cavity: OvenCavity) -> None:
        """Initialize the oven stop button."""
        super().__init__(appliance, cavity, "oven_stop", "-stop")

    @override
    async def async_press(self) -> None:
        """Stop cooking."""
        WhirlpoolOvenStopButton._check_service_request(
            await self._appliance.stop_cook(self.cavity)
        )
