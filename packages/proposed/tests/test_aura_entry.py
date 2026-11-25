from smartagri_core import CapabilityStatus, get_registry


def test_aura_is_discovered_through_entry_points() -> None:
    spec = get_registry().get("scheduler:aura")
    assert spec.source == "smartagri-proposed"
    assert spec.status is CapabilityStatus.PLANNED
    assert not spec.runnable
