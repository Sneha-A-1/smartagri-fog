"""Capability status and data provenance.

These two enums enforce the project's integrity rule: the platform must always make clear what is
implemented, what is simulated, what awaits an external integration and what is only planned, and
whether any data shown is real, synthetic or derived.
"""

from enum import StrEnum


class CapabilityStatus(StrEnum):
    """How real a feature is. Shown as a badge everywhere the feature appears."""

    IMPLEMENTED = "implemented"
    """The feature executes for real (e.g. an algorithm whose code runs)."""

    SIMULATED = "simulated"
    """The feature executes, but stands in for something physical (e.g. a simulated sensor)."""

    NEEDS_INTEGRATION = "needs-integration"
    """Code exists but needs external configuration (an API key, a device) before it can run."""

    PLANNED = "planned"
    """Described in the catalogue only. It cannot be run and must never produce results."""

    @property
    def runnable(self) -> bool:
        return self in (CapabilityStatus.IMPLEMENTED, CapabilityStatus.SIMULATED)


class DataOrigin(StrEnum):
    """Where a dataset or result came from. Inherited by every chart, table and report built on it."""

    REAL = "real"
    SYNTHETIC = "synthetic"
    DERIVED = "derived"
