# ADR 0001: All science lives in a headless core package

Date: 2026-11-25. Status: accepted.

## Context

The platform must be usable from a GUI, but PhD experiments must also be reproducible on another machine,
runnable overnight in batches, and inspectable in notebooks. Logic duplicated between the UI and scripts
drifts, and results produced by the GUI would then not match results produced by scripts.

## Decision

`smartagri_core` contains the domain models, plugin registry, simulator, schedulers, pipeline and metrics.
It imports no web framework and no database. The FastAPI app (`smartagri_api`) and the CLI are thin adapters
around it. Long-running core functions report progress through a plain callable.

## Consequences

- An experiment run from the GUI, the CLI or a notebook executes the same code.
- The core is unit-testable without starting a server.
- Persistence concerns (SQL, files) stay in the API layer or in explicit result-store modules.
