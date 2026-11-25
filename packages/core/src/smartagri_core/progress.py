"""Progress reporting shared by long-running core functions.

Core code reports progress through a plain callable, so it stays independent of how progress is
displayed: the API's job runner forwards it to the browser, the CLI prints it, tests ignore it.
"""

from typing import Protocol


class ProgressReporter(Protocol):
    def __call__(self, fraction: float, message: str = "") -> None: ...


def null_progress(fraction: float, message: str = "") -> None:
    """A reporter that discards progress."""
