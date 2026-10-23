"""Exception hierarchy shared by every instrument driver.

All driver-level failures derive from :class:`InstrumentError` so that test
sequences can catch one base type while still distinguishing connection,
communication, identity and command (SCPI error queue) problems.

Author: mozial
"""

from __future__ import annotations


class InstrumentError(Exception):
    """Base class for all instrument related failures."""


class InstrumentConnectionError(InstrumentError):
    """Raised when a session cannot be opened or is used while closed."""


class InstrumentIdentityError(InstrumentConnectionError):
    """Raised when the *IDN? response does not match the expected model."""


class InstrumentCommunicationError(InstrumentError):
    """Raised when an I/O operation still fails after all retries."""


class InstrumentCommandError(InstrumentError):
    """Raised when the instrument error queue reports a rejected command."""

    def __init__(self, message: str, code: int | None = None, command: str | None = None):
        super().__init__(message)
        self.code = code
        self.command = command


class TransportError(InstrumentError):
    """Low level, retryable failure of a non-VISA transport (e.g. TCP socket)."""


class SafetyInterlockError(InstrumentError):
    """Raised when a hardware safety precondition is violated."""
