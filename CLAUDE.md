# SmartAgri-Fog: notes for AI assistants and contributors

PhD research platform: "Design and Development of an Efficient Cloud-Enabled Framework for Smart Agriculture".
The owner develops on Windows 11 (PowerShell, 8 GB RAM laptop) and is new to software tooling: explain steps
plainly and give exact PowerShell commands.

## Layout

- `packages/core` (`smartagri_core`): all science. No web or database imports. Plugin registry, statuses, plugins, CLI.
- `packages/proposed` (`smartagri_proposed`): the proposed AURA algorithm, discovered via entry points.
- `apps/api` (`smartagri_api`): FastAPI adapter. SQLAlchemy 2 models, Alembic migrations (run automatically at
  start-up), local-mode auth + RBAC, process-pool job runner with WebSocket progress.
- `apps/web`: React 19 + TypeScript + Vite + Tailwind v4. Pages are declared in `src/modules/registry.tsx`.
  The API client is generated: after API changes run `uv run python -m smartagri_api.export_openapi` then
  `npm run gen:api` in `apps/web`, and commit both files.
- `docs/`: getting started, adding an algorithm, ADRs.

## Commands

```bash
uv sync                      # Python deps
uv run pytest                # Python tests
uv run ruff check . && uv run ruff format --check .
cd apps/web && npm ci && npm run typecheck && npm test && npm run build
uv run smartagri-api         # serves API + built web app on :8000
```

New migration after changing `models.py`: `cd apps/api && uv run alembic revision --autogenerate -m "..."`.

## Non-negotiable rules

1. Never fabricate results or present planned/simulated features as implemented. Use `CapabilityStatus` and
   `DataOrigin` honestly; planned plugins use `declare()` and must not run.
2. Every stochastic process takes an explicit seed; same seed means identical output (test it).
3. Comparisons between algorithms must use identical frozen workloads and report statistics, not single runs.
4. Don't remove working functionality when adding modules. Database changes go through additive migrations.
5. Work on a branch and open a pull request with test instructions for the owner; don't push to `main`.
