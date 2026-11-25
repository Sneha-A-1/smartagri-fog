"""Plugin registry.

Every extensible part of the platform (schedulers, optimisers, pipeline stages, classifiers, data
generators, ...) registers itself here with metadata and a Pydantic parameter model. The API
exposes each plugin's JSON Schema, and the web interface builds configuration forms from it, so
adding an algorithm never requires user-interface code.

Plugins outside this package (for example the proposed AURA algorithm) are discovered through the
``smartagri.plugins`` Python entry-point group, so the core never imports them directly.
"""

from __future__ import annotations

import re
import threading
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from enum import StrEnum
from importlib.metadata import entry_points
from types import ModuleType
from typing import Any, TypeVar

from pydantic import BaseModel, ConfigDict

from smartagri_core.status import CapabilityStatus

ENTRY_POINT_GROUP = "smartagri.plugins"
_SEMVER = re.compile(r"^\d+\.\d+\.\d+$")
_KEY = re.compile(r"^[a-z0-9][a-z0-9_.-]*$")

T = TypeVar("T")


class PluginKind(StrEnum):
    SCHEDULER = "scheduler"
    PLACEMENT = "placement"
    OPTIMIZER = "optimizer"
    PIPELINE_STAGE = "pipeline_stage"
    PREPROCESSOR = "preprocessor"
    CLASSIFIER = "classifier"
    REGRESSOR = "regressor"
    CLUSTERING = "clustering"
    ANOMALY_DETECTOR = "anomaly_detector"
    DEEP_MODEL = "deep_model"
    DATA_GENERATOR = "data_generator"
    DATA_SOURCE = "data_source"


class EmptyParams(BaseModel):
    """Parameter model for plugins that take no parameters."""

    model_config = ConfigDict(extra="forbid")


class PluginError(Exception):
    pass


class DuplicatePluginError(PluginError):
    pass


class PluginNotFoundError(PluginError):
    pass


class PluginNotRunnableError(PluginError):
    """Raised when someone tries to run a plugin that is planned or awaiting integration."""


@dataclass(frozen=True)
class PluginSpec:
    """Everything the platform knows about one plugin."""

    kind: PluginKind
    key: str
    name: str
    version: str
    status: CapabilityStatus
    summary: str
    params_model: type[BaseModel] = EmptyParams
    factory: Callable[..., Any] | None = None
    description: str = ""
    layers: tuple[str, ...] = ()
    agri_applications: tuple[str, ...] = ()
    inputs: tuple[str, ...] = ()
    outputs: tuple[str, ...] = ()
    metrics: tuple[str, ...] = ()
    references: tuple[str, ...] = ()
    phase: int | None = None
    source: str = "builtin"
    tags: tuple[str, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        if not _KEY.match(self.key):
            raise PluginError(f"Invalid plugin key {self.key!r}: use lowercase letters, digits, _ . -")
        if not _SEMVER.match(self.version):
            raise PluginError(f"Plugin {self.id}: version must be MAJOR.MINOR.PATCH, got {self.version!r}")
        if self.status.runnable and self.factory is None:
            raise PluginError(f"Plugin {self.id} is marked {self.status} but has no implementation")

    @property
    def id(self) -> str:
        return f"{self.kind}:{self.key}"

    @property
    def runnable(self) -> bool:
        return self.status.runnable and self.factory is not None

    def params_schema(self) -> dict[str, Any]:
        return self.params_model.model_json_schema()

    def default_params(self) -> dict[str, Any]:
        return self.params_model().model_dump(mode="json")

    def validate_params(self, raw: dict[str, Any] | None) -> BaseModel:
        return self.params_model.model_validate(raw or {})

    def to_dict(self, include_schema: bool = False) -> dict[str, Any]:
        data: dict[str, Any] = {
            "id": self.id,
            "kind": str(self.kind),
            "key": self.key,
            "name": self.name,
            "version": self.version,
            "status": str(self.status),
            "runnable": self.runnable,
            "summary": self.summary,
            "description": self.description,
            "layers": list(self.layers),
            "agri_applications": list(self.agri_applications),
            "inputs": list(self.inputs),
            "outputs": list(self.outputs),
            "metrics": list(self.metrics),
            "references": list(self.references),
            "phase": self.phase,
            "source": self.source,
            "tags": list(self.tags),
        }
        if include_schema:
            data["params_schema"] = self.params_schema()
            data["default_params"] = self.default_params()
        return data


class PluginRegistry:
    def __init__(self) -> None:
        self._specs: dict[str, PluginSpec] = {}
        self._lock = threading.RLock()
        self._entry_points_loaded = False
        self.load_errors: list[str] = []

    def add(self, spec: PluginSpec) -> PluginSpec:
        with self._lock:
            existing = self._specs.get(spec.id)
            if existing is not None and existing != spec:
                raise DuplicatePluginError(f"A different plugin is already registered as {spec.id}")
            self._specs[spec.id] = spec
            return spec

    def get(self, plugin_id: str) -> PluginSpec:
        self.ensure_loaded()
        try:
            return self._specs[plugin_id]
        except KeyError:
            raise PluginNotFoundError(f"No plugin registered as {plugin_id!r}") from None

    def all(self, kind: PluginKind | str | None = None) -> list[PluginSpec]:
        self.ensure_loaded()
        specs: Iterable[PluginSpec] = self._specs.values()
        if kind is not None:
            specs = (s for s in specs if s.kind == PluginKind(kind))
        return sorted(specs, key=lambda s: (str(s.kind), s.name.lower()))

    def create(self, plugin_id: str, params: dict[str, Any] | BaseModel | None = None) -> Any:
        """Instantiate a runnable plugin with validated parameters."""
        spec = self.get(plugin_id)
        if not spec.runnable:
            raise PluginNotRunnableError(
                f"{spec.name} ({spec.id}) is '{spec.status}' and cannot be run"
                + (f"; it is scheduled for Phase {spec.phase}" if spec.phase is not None else "")
            )
        validated = params if isinstance(params, BaseModel) else spec.validate_params(params)
        assert spec.factory is not None
        return spec.factory(validated)

    def ensure_loaded(self) -> None:
        if not self._entry_points_loaded:
            self.load_entry_points()

    def load_entry_points(self, group: str = ENTRY_POINT_GROUP) -> None:
        """Import every installed plugin package. Failures are recorded, never fatal."""
        with self._lock:
            self._entry_points_loaded = True
            for ep in entry_points(group=group):
                try:
                    loaded = ep.load()
                    if callable(loaded) and not isinstance(loaded, ModuleType):
                        loaded(self)
                except Exception as exc:  # a broken plugin must not take the platform down
                    self.load_errors.append(f"{ep.name} ({ep.value}): {exc!r}")


_default_registry = PluginRegistry()


def get_registry() -> PluginRegistry:
    return _default_registry


def register(
    *,
    kind: PluginKind | str,
    key: str,
    name: str,
    version: str,
    status: CapabilityStatus,
    summary: str,
    params: type[BaseModel] = EmptyParams,
    registry: PluginRegistry | None = None,
    **metadata: Any,
) -> Callable[[T], T]:
    """Decorator registering a class or function as a runnable plugin.

    The decorated object is called with the validated parameter model and must return the plugin
    instance (a class whose ``__init__`` takes the params works directly).
    """

    def decorator(obj: T) -> T:
        spec = PluginSpec(
            kind=PluginKind(kind),
            key=key,
            name=name,
            version=version,
            status=status,
            summary=summary,
            params_model=params,
            factory=obj,  # type: ignore[arg-type]
            **_tuplify(metadata),
        )
        (registry or _default_registry).add(spec)
        return obj

    return decorator


def declare(
    *,
    kind: PluginKind | str,
    key: str,
    name: str,
    summary: str,
    phase: int | None,
    version: str = "0.0.0",
    status: CapabilityStatus = CapabilityStatus.PLANNED,
    registry: PluginRegistry | None = None,
    **metadata: Any,
) -> PluginSpec:
    """Add a catalogue entry for something not yet implemented. It can be browsed, never run."""
    if status.runnable:
        raise PluginError("declare() is for planned or integration-pending entries; use @register")
    spec = PluginSpec(
        kind=PluginKind(kind),
        key=key,
        name=name,
        version=version,
        status=status,
        summary=summary,
        phase=phase,
        **_tuplify(metadata),
    )
    return (registry or _default_registry).add(spec)


def _tuplify(metadata: dict[str, Any]) -> dict[str, Any]:
    return {k: tuple(v) if isinstance(v, list) else v for k, v in metadata.items()}
