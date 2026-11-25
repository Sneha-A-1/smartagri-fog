"""Built-in plugins. Importing this package registers them (it is the ``builtin`` entry point)."""

from smartagri_core import experiment  # noqa: F401
from smartagri_core.plugins import catalogue, demo_soil_moisture  # noqa: F401
from smartagri_core.sim import policies, runner  # noqa: F401
