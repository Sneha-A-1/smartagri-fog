"""SmartAgri-Fog core package.

Everything scientific lives here: domain models, the plugin registry, the simulator, schedulers,
the data-retrieval pipeline and metrics. This package must never import web frameworks or databases,
so the same code runs from the GUI (through the API), from the command line and from notebooks.
"""

from smartagri_core.registry import (
    PluginKind,
    PluginNotRunnableError,
    PluginRegistry,
    PluginSpec,
    declare,
    get_registry,
    register,
)
from smartagri_core.status import CapabilityStatus, DataOrigin

__version__ = "0.1.0"

__all__ = [
    "CapabilityStatus",
    "DataOrigin",
    "PluginKind",
    "PluginNotRunnableError",
    "PluginRegistry",
    "PluginSpec",
    "__version__",
    "declare",
    "get_registry",
    "register",
]
