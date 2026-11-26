"""Built-in plugins. Importing this package registers them (it is the ``builtin`` entry point)."""

from smartagri_core import experiment  # noqa: F401
from smartagri_core.agro import plugins as agro_plugins  # noqa: F401
from smartagri_core.plugins import catalogue, demo_soil_moisture  # noqa: F401
from smartagri_core.sched import plugins as sched_plugins  # noqa: F401
from smartagri_core.sim import ifogsim_eeg, policies, runner  # noqa: F401
