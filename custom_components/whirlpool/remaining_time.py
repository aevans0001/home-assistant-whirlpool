"""Local display countdown for a laundry appliance's reported remaining time."""

from datetime import datetime, timedelta
from math import ceil


class RemainingTimeEstimate:
    """Count down between appliance updates without extending a stale estimate."""

    def __init__(self) -> None:
        self._mode = "idle"
        self._last_seconds: int | None = None
        self._deadline: datetime | None = None
        self._paused_seconds: int | None = None

    def observe(self, mode: str, seconds: int | None, now: datetime) -> None:
        """Accept an appliance update for running, paused, complete, or idle."""
        if mode == "complete":
            self._mode = mode
            self._deadline = None
            self._paused_seconds = None
            self._last_seconds = None
            return

        if mode == "paused":
            if seconds is not None and seconds >= 0:
                self._paused_seconds = seconds
            elif self._deadline is not None:
                self._paused_seconds = max(
                    0, ceil((self._deadline - now).total_seconds())
                )
            self._mode = mode
            self._deadline = None
            self._last_seconds = None
            return

        if mode == "running":
            if seconds is not None and seconds >= 0:
                if self._mode != mode or seconds != self._last_seconds:
                    self._deadline = now + timedelta(seconds=seconds)
                self._last_seconds = seconds
            else:
                self._deadline = None
                self._last_seconds = None
            self._paused_seconds = None
            self._mode = mode
            return

        self._mode = "idle"
        self._deadline = None
        self._paused_seconds = None
        self._last_seconds = None

    def minutes(self, now: datetime) -> int | None:
        """Return whole displayed minutes, rounded up until the deadline."""
        if self._mode == "complete":
            return 0
        if self._mode == "paused":
            return (
                None
                if self._paused_seconds is None
                else ceil(self._paused_seconds / 60)
            )
        if self._mode == "running" and self._deadline is not None:
            return max(0, ceil((self._deadline - now).total_seconds() / 60))
        return None


def format_remaining_minutes(minutes: int | None) -> str | None:
    """Format a countdown for the Home Assistant sensor state."""
    if minutes is None:
        return None
    hours, remainder = divmod(minutes, 60)
    return f"{hours} hr {remainder} min" if hours else f"{remainder} min"
