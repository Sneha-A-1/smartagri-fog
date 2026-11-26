"""SmartAgri-Fog API. Routers validate requests and call services; the science lives in smartagri_core."""

__version__ = "0.1.0"


def _git_commit() -> str:
    """Short commit of the running code, or "unknown" outside a Git checkout."""
    import subprocess
    from pathlib import Path

    try:
        out = subprocess.run(
            ["git", "rev-parse", "--short=7", "HEAD"],
            cwd=Path(__file__).resolve().parent,
            capture_output=True,
            text=True,
            timeout=5,
            check=True,
        )
        return out.stdout.strip() or "unknown"
    except Exception:
        return "unknown"


__commit__ = _git_commit()
