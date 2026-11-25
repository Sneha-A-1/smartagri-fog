# ADR 0003: Process-pool job runner behind a small interface

Date: 2026-11-25. Status: accepted.

## Context

Simulations, replications and model training can take minutes to hours. They must not block web requests,
must report progress live, must be cancellable, and should use several CPU cores. The target machine is a
single Windows laptop, where running Redis or Celery adds setup burden.

## Decision

`JobRunner` wraps a `ProcessPoolExecutor` using the `spawn` start method (identical behaviour on Windows and
Linux). Workers send progress through a managed queue; a pump task writes throttled updates to the `jobs`
table and broadcasts them over the `/api/ws/jobs` WebSocket. Cancellation is cooperative through shared flags
checked on each progress report. Jobs left running when the API stops are marked `interrupted` at the next start.
Results are written as files in the results folder; the database stores the path and a summary.

## Consequences

- No extra services on day one; parallel replications use every configured worker.
- The interface (`submit`, `cancel`, `start`, `stop`) can be re-implemented on Celery or Dramatiq with Redis
  if the platform moves to a server.
- Code that runs inside a job must report progress regularly to be cancellable.
