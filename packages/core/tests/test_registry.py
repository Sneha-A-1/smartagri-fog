import pytest
from pydantic import BaseModel, Field
from smartagri_core import (
    CapabilityStatus,
    PluginKind,
    PluginNotRunnableError,
    PluginRegistry,
    declare,
    register,
)
from smartagri_core.registry import DuplicatePluginError, PluginError, PluginNotFoundError, PluginSpec


class _Params(BaseModel):
    alpha: float = Field(0.5, ge=0, le=1, json_schema_extra={"x-unit": "ratio"})


def test_register_and_create_validates_params() -> None:
    reg = PluginRegistry()

    @register(
        kind="scheduler",
        key="toy",
        name="Toy",
        version="1.0.0",
        status=CapabilityStatus.IMPLEMENTED,
        summary="t",
        params=_Params,
        registry=reg,
    )
    class Toy:
        def __init__(self, params: _Params) -> None:
            self.params = params

    instance = reg.create("scheduler:toy", {"alpha": 0.2})
    assert instance.params.alpha == 0.2
    with pytest.raises(ValueError):
        reg.create("scheduler:toy", {"alpha": 5})


def test_schema_exposes_units() -> None:
    reg = PluginRegistry()
    register(
        kind="scheduler",
        key="toy",
        name="Toy",
        version="1.0.0",
        status=CapabilityStatus.IMPLEMENTED,
        summary="t",
        params=_Params,
        registry=reg,
    )(lambda p: p)
    schema = reg.get("scheduler:toy").params_schema()
    assert schema["properties"]["alpha"]["x-unit"] == "ratio"


def test_planned_plugins_cannot_run() -> None:
    reg = PluginRegistry()
    declare(kind="optimizer", key="future", name="Future", summary="s", phase=4, registry=reg)
    with pytest.raises(PluginNotRunnableError, match="Phase 4"):
        reg.create("optimizer:future")


def test_runnable_status_requires_implementation() -> None:
    with pytest.raises(PluginError):
        PluginSpec(
            kind=PluginKind.SCHEDULER,
            key="x",
            name="X",
            version="1.0.0",
            status=CapabilityStatus.IMPLEMENTED,
            summary="s",
        )


def test_declare_refuses_runnable_status() -> None:
    with pytest.raises(PluginError):
        declare(
            kind="scheduler",
            key="x",
            name="X",
            summary="s",
            phase=1,
            status=CapabilityStatus.IMPLEMENTED,
            registry=PluginRegistry(),
        )


def test_duplicate_ids_are_rejected() -> None:
    reg = PluginRegistry()
    declare(kind="scheduler", key="dup", name="A", summary="s", phase=1, registry=reg)
    with pytest.raises(DuplicatePluginError):
        declare(kind="scheduler", key="dup", name="B", summary="s", phase=1, registry=reg)


def test_bad_version_and_key_rejected() -> None:
    with pytest.raises(PluginError):
        declare(kind="scheduler", key="Bad Key", name="A", summary="s", phase=1, registry=PluginRegistry())
    with pytest.raises(PluginError):
        declare(kind="scheduler", key="ok", name="A", summary="s", phase=1, version="1.0", registry=PluginRegistry())


def test_unknown_plugin() -> None:
    with pytest.raises(PluginNotFoundError):
        PluginRegistry().get("scheduler:nope")


def test_builtin_catalogue_loads_via_entry_points() -> None:
    from smartagri_core import get_registry

    reg = get_registry()
    assert reg.get("data_generator:soil_moisture_demo").runnable
    assert reg.get("optimizer:ppo").status is CapabilityStatus.PLANNED
    assert reg.get("optimizer:ga").status is CapabilityStatus.IMPLEMENTED
    assert reg.get("queue_discipline:edf").status is CapabilityStatus.IMPLEMENTED
    assert not reg.load_errors
