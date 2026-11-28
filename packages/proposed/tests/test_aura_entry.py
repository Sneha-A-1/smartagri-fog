from smartagri_core import CapabilityStatus, get_registry


def test_aura_is_discovered_through_entry_points() -> None:
    reg = get_registry()
    spec = reg.get("scheduler:aura")
    assert spec.source == "smartagri-proposed"
    assert spec.status is CapabilityStatus.IMPLEMENTED
    for key in ["aura", "aura_noaoi", "aura_noreserve", "aura_staticreserve", "aura_noreliability", "aura_singletier"]:
        assert reg.get(f"placement:{key}").runnable
    assert reg.get("queue_discipline:aura").runnable
    assert reg.get("simulation:aura_evaluation").startable
