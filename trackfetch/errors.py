# SPDX-License-Identifier: GPL-3.0-or-later
"""Exceptions raised by metadata providers."""


class ProviderError(Exception):
    """A provider request failed for a real, retryable reason."""


class ProviderAuthError(ProviderError):
    """A provider rejected the credentials."""

