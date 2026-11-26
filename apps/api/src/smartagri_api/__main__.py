"""Start the API: ``uv run smartagri-api`` (add ``--reload`` while developing)."""

from __future__ import annotations

import argparse

import uvicorn

from smartagri_api.config import get_settings


def main() -> None:
    settings = get_settings()
    parser = argparse.ArgumentParser(prog="smartagri-api")
    parser.add_argument("--host", default=settings.host)
    parser.add_argument("--port", type=int, default=settings.port)
    parser.add_argument("--reload", action="store_true", help="Restart automatically when code changes")
    args = parser.parse_args()
    try:
        uvicorn.run(
            "smartagri_api.main:create_app",
            factory=True,
            host=args.host,
            port=args.port,
            reload=args.reload,
            timeout_graceful_shutdown=10,  # never hang on Ctrl+C, even with a stuck connection
        )
    except KeyboardInterrupt:
        pass
    print("SmartAgri-Fog stopped.")


if __name__ == "__main__":
    main()
