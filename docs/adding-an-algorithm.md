# Adding an algorithm

Algorithms are plugins. A plugin is a class with a Pydantic parameter model, registered with `@register`.
The catalogue, the parameter form, validation and job execution all work automatically from that.

```python
from pydantic import BaseModel, ConfigDict, Field

from smartagri_core import CapabilityStatus, PluginKind, register
from smartagri_core.progress import ProgressReporter, null_progress


class MyParams(BaseModel):
    model_config = ConfigDict(extra="forbid")

    window: int = Field(60, ge=1, le=3600, description="Batch window length.", json_schema_extra={"x-unit": "s"})
    weight: float = Field(
        0.5, ge=0, le=1, description="Energy weight in the score.", json_schema_extra={"x-advanced": True}
    )  # shown only in researcher mode


@register(
    kind=PluginKind.SCHEDULER,
    key="my_scheduler",
    name="My scheduler",
    version="0.1.0",
    status=CapabilityStatus.IMPLEMENTED,
    summary="One sentence on what it does.",
    params=MyParams,
    layers=["edge", "fog"],
    metrics=["Deadline success", "Energy"],
)
class MyScheduler:
    def __init__(self, params: MyParams) -> None:
        self.params = params

    def run(self, progress: ProgressReporter = null_progress) -> dict:
        ...
        progress(1.0, "Done")
        return {"data_origin": "synthetic", "summary": {...}}
```

## Rules

- **Status must be honest.** Use `IMPLEMENTED` only when the code really runs. Use `declare(...)` with
  `PLANNED` for catalogue entries without an implementation. The registry refuses to run planned plugins.
- **Results carry provenance.** Every result dictionary includes `data_origin`: `real`, `synthetic` or `derived`.
- **Version on behaviour changes.** Bump `version` whenever results could change. Experiments record it.
- **Determinism.** Take randomness only from a seed parameter (`numpy.random.default_rng(seed)`).
- **Tests.** Add a test that checks same seed gives the same output, and that outputs respect physical bounds.

## Where code goes

| Kind of algorithm | Package |
| --- | --- |
| Baselines and shared methods | `packages/core/src/smartagri_core/plugins/` |
| The proposed research algorithm (AURA) | `packages/proposed/src/smartagri_proposed/` |

The proposed package is discovered through the `smartagri.plugins` entry point in its `pyproject.toml`,
so the core never imports it directly. When an implementation replaces a `declare(...)` entry, delete the entry.
