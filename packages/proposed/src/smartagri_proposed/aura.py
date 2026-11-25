"""AURA: Age- and Urgency-aware Reliable Allocation (working name).

Catalogue entry only. The algorithm is implemented in Phase 4, once the simulator (Phase 1) and the
data retrieval framework (Phase 3) exist. Design: see the project document, tab "Proposed algorithm: AURA".
"""

from smartagri_core.registry import PluginKind, declare

declare(
    kind=PluginKind.SCHEDULER,
    key="aura",
    name="AURA (proposed)",
    phase=4,
    source="smartagri-proposed",
    summary=(
        "Two-tier, freshness- and urgency-aware scheduler with anticipatory capacity reservation "
        "for agricultural edge-fog-cloud systems."
    ),
    description=(
        "Tier 1 places urgent tasks online by expected decision value (Age-of-Information-aware deadlines, "
        "path reliability, energy). Tier 2 maps strategic tasks in windows with NSGA-II on capacity not "
        "reserved for urgent work. Reservations anticipate surges from data-retrieval trend signals."
    ),
    layers=["edge", "fog", "cloud"],
    agri_applications=["Irrigation emergencies", "Crop-health alerts", "Strategic analytics"],
    inputs=["Tasks with class, deadline and freshness bound", "Topology state", "Trend signals"],
    outputs=["Task-to-node placements", "Decision traces"],
    metrics=["Urgent deadline success", "AoI violations", "Energy", "Cost", "Autonomy ratio"],
    tags=["proposed"],
)
