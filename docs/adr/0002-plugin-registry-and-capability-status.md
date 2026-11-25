# ADR 0002: Schema-backed plugin registry with enforced capability status

Date: 2026-11-25. Status: accepted.

## Context

The research will keep adding algorithms, classifiers, pipeline stages and data sources. Each addition should
not require UI work. The project also requires a clear, enforced distinction between implemented, simulated,
integration-pending and planned functionality, and must never present fabricated results.

## Decision

- Every extensible component registers a `PluginSpec`: kind, key, semantic version, status, metadata and a
  Pydantic parameter model. The API serves the model's JSON Schema; the web app renders forms from it
  (`x-unit` and `x-advanced` extensions control units and beginner/researcher visibility).
- `CapabilityStatus` has four values. A spec marked implemented or simulated must have an implementation;
  `declare()` creates planned entries, and the registry refuses to instantiate them.
- Results carry `DataOrigin` (real, synthetic, derived), shown as a badge wherever they appear.
- External packages register through the `smartagri.plugins` entry-point group. The proposed algorithm
  lives in its own package for this reason.

## Consequences

- Adding an algorithm is one Python class plus tests.
- The catalogue doubles as an honest roadmap of what exists.
- A broken plugin package is reported in Settings but cannot take the platform down.
