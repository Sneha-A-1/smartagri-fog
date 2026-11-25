"""Code that runs inside a worker process.

Kept free of database and web imports: a worker only needs the core registry, a queue for progress
messages and a shared dictionary of cancellation flags.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from smartagri_core import get_registry


class JobCancelledError(Exception):
    pass


def run_plugin_job(
    job_id: str, plugin_id: str, params: dict[str, Any], results_dir: str, queue: Any, cancel_flags: Any
) -> dict[str, Any]:
    last_sent = [0.0]

    def progress(fraction: float, message: str = "") -> None:
        if cancel_flags.get(job_id):
            raise JobCancelledError()
        now = time.monotonic()
        # Throttle to ~10 messages/s per job; always send the final one.
        if fraction >= 1.0 or now - last_sent[0] >= 0.1:
            last_sent[0] = now
            queue.put({"job_id": job_id, "fraction": max(0.0, min(1.0, float(fraction))), "message": message})

    try:
        plugin = get_registry().create(plugin_id, params)
        if not callable(getattr(plugin, "run", None)):
            raise TypeError(f"{plugin_id} cannot run as a job (it has no run() method)")
        progress(0.0, "Started")
        result = plugin.run(progress)
    except JobCancelledError:
        raise
    except Exception as exc:  # re-raise as a plain, always-picklable error
        raise RuntimeError(f"{type(exc).__name__}: {exc}") from None

    out_dir = Path(results_dir) / "jobs"
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{job_id}.json"
    path.write_text(json.dumps(result, ensure_ascii=False), encoding="utf-8")
    return {
        "result_path": str(path),
        "summary": result.get("summary") if isinstance(result, dict) else None,
        "data_origin": result.get("data_origin") if isinstance(result, dict) else None,
    }
