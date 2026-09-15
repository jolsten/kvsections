"""Record-level primitives shared by the reader, the writer and the layout helpers.

A record is one line of a file. The rule for telling a section header from a
continuation lives in :meth:`Record.from_line`, the characters a record may
hold in :data:`TOKEN_CHARS` and :data:`TEXT_CHARS`, and the greedy line
packing used for wrapping in :func:`pack`, so every part of the package
agrees on them.
"""

from __future__ import annotations

import re
import textwrap
from collections.abc import Callable, Iterable
from typing import Any, NamedTuple

__all__ = [
    "BLANK",
    "CONTINUATION",
    "HEADER",
    "TEXT_CHARS",
    "TOKEN_CHARS",
    "Record",
    "pack",
    "plan_order",
    "split_records",
]

_LINE_BREAK = re.compile(r"(\r\n|\r|\n)")
_HEADER = re.compile(r"\S+\s*")

#: Record kinds.
HEADER = "header"
CONTINUATION = "continuation"
BLANK = "blank"

#: Characters allowed in section names, keys and values: printable ASCII
#: other than space.
TOKEN_CHARS = frozenset(chr(c) for c in range(0x21, 0x7F))
#: Characters allowed in free text: printable ASCII including space.
TEXT_CHARS = TOKEN_CHARS | {" "}


class Record(NamedTuple):
    """One line of a file split into layout and content.

    ``line`` is the text without its terminator and ``ending`` the terminator
    itself, so ``line + ending`` reproduces the input exactly. ``prefix`` is
    the layout part: the section name and the gap after it for a header, or
    the indent of a continuation. ``content`` is the right-stripped rest.
    """

    kind: str
    name: str
    prefix: str
    content: str
    line: str
    ending: str = ""

    @classmethod
    def from_line(cls, line: str, ending: str = "") -> Record:
        """Split one line into a record.

        A line starting in column 1 is a header named by its first token,
        unless that token contains ``=``, in which case it is a continuation
        with no indent. An indented line is a continuation, and a line that
        is empty or all whitespace is blank.
        """
        body = line.rstrip()
        if not body:
            return cls(BLANK, "", "", "", line, ending)
        if body[0].isspace():
            prefix = body[: len(body) - len(body.lstrip())]
            return cls(CONTINUATION, "", prefix, body[len(prefix) :], line, ending)
        match = _HEADER.match(body)
        assert match is not None
        prefix = match.group()
        name = prefix.rstrip()
        if "=" in name:
            return cls(CONTINUATION, "", "", body, line, ending)
        return cls(HEADER, name, prefix, body[len(prefix) :], line, ending)

    @property
    def content_col(self) -> int:
        """The column at which the content starts."""
        return len(self.prefix)


def split_records(text: str) -> list[Record]:
    """Split ``text`` into records, each keeping its own line ending."""
    parts = _LINE_BREAK.split(text)
    records = [
        Record.from_line(parts[i], parts[i + 1]) for i in range(0, len(parts) - 1, 2)
    ]
    if parts[-1]:
        records.append(Record.from_line(parts[-1]))
    return records


def pack(
    words: Iterable[str], available: int, *, break_long: bool = False
) -> list[str]:
    """Pack ``words`` greedily into lines of at most ``available`` columns.

    A word longer than ``available`` is left on a line of its own, or broken
    to fill the lines when ``break_long`` is set. This is :mod:`textwrap`
    with the options a fixed-width record format needs: nothing expanded,
    replaced or split on hyphens.
    """
    wrapper = textwrap.TextWrapper(
        width=max(available, 1),
        break_long_words=break_long,
        break_on_hyphens=False,
        expand_tabs=False,
        replace_whitespace=False,
    )
    # older textwrap versions leave a trailing space when a broken word
    # cannot start on the current line; words never contain whitespace
    return [line.rstrip() for line in wrapper.wrap(" ".join(words))]


def plan_order(
    order: Iterable[Any], canonical: Callable[[str], str]
) -> tuple[list[str], list[str]]:
    """Validate an order specification and return its head and tail names.

    ``order`` lists section names in the wanted order, with at most one
    ``...`` standing for everything not named; names after it form the tail.
    ``canonical`` maps each name to the spelling sections are keyed by.
    """
    head: list[str] = []
    tail: list[str] = []
    target = head
    for entry in order:
        if entry is Ellipsis:
            if target is tail:
                raise ValueError("order may contain '...' only once")
            target = tail
            continue
        name = canonical(entry)
        if name in head or name in tail:
            raise ValueError(f"{name} appears more than once in the order")
        target.append(name)
    return head, tail
