"""Warnings and errors reported by the tolerant reader."""

from __future__ import annotations

from enum import Enum
from typing import NamedTuple

__all__ = ["ParseError", "ParseWarning", "Problem"]


class Problem(Enum):
    """The kinds of problem the reader tolerates, one per warning it can emit.

    Filter warnings by ``kind`` rather than by matching their message. The
    ``subject`` of a warning names what the problem concerns: the section
    name for ``DUPLICATE_SECTION`` (canonical, so aliases fold together),
    ``LOWERCASE_SECTION`` and an unwritable section name; the key for
    ``LOWERCASE_KEY``, ``DUPLICATE_KEY``, ``BARE_TOKEN`` and an unwritable
    key or value; the token for ``MISSING_KEY``; ``None`` where nothing is
    named, as for a byte order mark or unwritable free text.
    """

    #: A UTF-8 byte order mark at the start of the input was dropped.
    BOM = "bom"
    #: An indented line before the first section header was ignored.
    ORPHAN_CONTENT = "orphan-content"
    #: A line in column 1 that holds pairs but no name; read as a continuation.
    UNNAMED_HEADER = "unnamed-header"
    #: A section name that was not upper-case; normalized.
    LOWERCASE_SECTION = "lowercase-section"
    #: A key that was not upper-case; normalized.
    LOWERCASE_KEY = "lowercase-key"
    #: A token such as ``=1`` with nothing before the ``=``; ignored.
    MISSING_KEY = "missing-key"
    #: A token with no ``=``; stored with an empty value.
    BARE_TOKEN = "bare-token"
    #: A key seen twice in one section; the last value wins.
    DUPLICATE_KEY = "duplicate-key"
    #: A section header seen twice; merged into the earlier section.
    DUPLICATE_SECTION = "duplicate-section"
    #: Characters the writer would refuse, in a name, key, value or text.
    UNWRITABLE = "unwritable"


class ParseWarning(NamedTuple):
    """Something the tolerant reader accepted but that was not well-formed."""

    lineno: int
    kind: Problem
    subject: str | None
    message: str

    def __str__(self) -> str:
        return f"line {self.lineno}: {self.message}"


class ParseError(ValueError):
    """Raised instead of recording a :class:`ParseWarning` when reading strictly.

    Carries the same ``lineno``, ``kind``, ``subject`` and ``message``.
    """

    def __init__(self, lineno: int, kind: Problem, subject: str | None, message: str):
        super().__init__(f"line {lineno}: {message}")
        self.lineno = lineno
        self.kind = kind
        self.subject = subject
        self.message = message
