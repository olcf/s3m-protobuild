from __future__ import annotations


class BuildError(RuntimeError):
    """A user-facing build failure."""

    def __init__(self, message: str, output: str | None = None) -> None:
        super().__init__(message)
        self.output = output
