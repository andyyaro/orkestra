"""Orkestra exception hierarchy."""

from __future__ import annotations


class OrkestraError(Exception):
    """Base class for all Orkestra errors."""


class ConfigError(OrkestraError):
    """Invalid or missing configuration."""


class StoreError(OrkestraError):
    """Persistence-layer failure."""


class StateTransitionError(OrkestraError):
    """An illegal state transition was attempted."""


class DagError(OrkestraError):
    """Task graph is invalid (cycles, unknown references)."""


class AdapterError(OrkestraError):
    """Agent adapter failure."""


class WorkspaceError(OrkestraError):
    """Git/worktree operation failure."""


class PolicyViolation(OrkestraError):
    """An action was rejected by the policy engine."""


class VerificationError(OrkestraError):
    """Deterministic verification could not be executed."""


class DirectorError(OrkestraError):
    """Director interaction failed after bounded retries."""
