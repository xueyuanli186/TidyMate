"""Cooperative cancellation for long-running scans.

Python has no ``CancellationToken``; the equivalent is a thread-safe flag the scan loop
checks periodically. The check is deliberately cheap and sampled (every
:data:`CHECK_INTERVAL` items) so the hot loop stays fast.

A cancelled scan stops *cleanly*: the iterator ends, ``ScanStats.cancelled`` becomes True
and whatever was found so far is still valid. It never raises, because "user pressed stop"
is not an error, and the caller still needs the partial result to report honestly.
"""

from __future__ import annotations

import threading

#: How many directory entries to process between cancellation checks.
CHECK_INTERVAL = 256


class CancelToken:
    """A thread-safe "please stop" flag."""

    __slots__ = ("_event",)

    def __init__(self) -> None:
        self._event = threading.Event()

    def cancel(self) -> None:
        """Ask the scan loop to stop at the next checkpoint."""
        self._event.set()

    @property
    def cancelled(self) -> bool:
        """True once :meth:`cancel` has been called."""
        return self._event.is_set()
