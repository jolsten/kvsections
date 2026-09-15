"""Warnings and errors reported by the tolerant reader."""

from __future__ import annotations

from typing import NamedTuple

__all__ = ["ParseError", "ParseWarning"]


class ParseWarning(NamedTuple):
    """Something the tolerant reader accepted but that was not well-formed."""

    lineno: int
    message: str

    def __str__(self) -> str:
        return f"line {self.lineno}: {self.message}"


class ParseError(ValueError):
    """Raised instead of recording a :class:`ParseWarning` when reading strictly."""

    def __init__(self, lineno: int, message: str):
        super().__init__(f"line {lineno}: {message}")
        self.lineno = lineno
        self.message = message
