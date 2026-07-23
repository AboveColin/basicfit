"""
Custom exception classes for the Basic-Fit package.

A small hierarchy so callers (including the Home Assistant integration) can tell
authentication problems apart from transient network/API errors.
"""

from __future__ import annotations

from typing import Optional


class BasicFitError(Exception):
    """Base exception for all Basic-Fit errors."""

    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


class BasicFitAPIError(BasicFitError):
    """A non-success response from the Basic-Fit data API."""

    def __init__(self, message: str, status_code: Optional[int] = None):
        super().__init__(message)
        self.status_code = status_code

    def __str__(self) -> str:
        if self.status_code is not None:
            return f"{self.message} (HTTP {self.status_code})"
        return self.message


class BasicFitAuthError(BasicFitError):
    """Authentication / token errors (expired or revoked refresh token)."""


class BasicFitNetworkError(BasicFitError):
    """Network-level errors (timeouts, connection failures)."""


class BasicFitValidationError(BasicFitError):
    """Invalid arguments supplied by the caller."""
