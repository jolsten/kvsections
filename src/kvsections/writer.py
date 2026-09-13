"""Strict writer for the sectioned key/value format.

Unlike the reader, the writer refuses anything that would not read back
correctly: names and keys must be upper-case printable ASCII without spaces
or ``=``, values must contain no whitespace, and every pair must fit on one
line.
"""

from __future__ import annotations

import textwrap
from typing import TYPE_CHECKING

from .model import Section, TextSection

if TYPE_CHECKING:
    from .document import Document

_TOKEN_CHARS = frozenset(chr(c) for c in range(0x21, 0x7F))
_TEXT_CHARS = _TOKEN_CHARS | {" "}


def _check_token(token: str, what: str) -> None:
    if not isinstance(token, str):
        raise TypeError(f"{what} must be a str, not {type(token).__name__}")
    if not set(token) <= _TOKEN_CHARS:
        raise ValueError(
            f"{what} {token!r} contains whitespace or non-ASCII characters"
        )


def _check_name(token: str, what: str) -> None:
    if not token:
        raise ValueError(f"{what} is empty")
    _check_token(token, what)
    if "=" in token:
        raise ValueError(f"{what} {token!r} contains '='")
    if token != token.upper():
        raise ValueError(f"{what} {token!r} is not upper-case")


def format_value(key: str, value: str) -> str:
    """Check a raw value and return it as it appears after ``KEY=``."""
    _check_token(value, f"value of {key}")
    return value


def pack_pairs(section: Section, available: int | None) -> list[str]:
    """Render a section's pairs as content lines of at most ``available`` columns."""
    pairs = []
    for key, value in section.fields.items():
        _check_name(key, f"key in section {section.name}")
        pairs.append(f"{key}={format_value(key, value)}")
    if available is None:
        return [" ".join(pairs)] if pairs else []

    lines: list[str] = []
    current: list[str] = []
    length = 0
    for pair in pairs:
        if len(pair) > available:
            raise ValueError(
                f"{pair!r} in section {section.name} is longer than the "
                f"{available} columns available for content"
            )
        if current and length + 1 + len(pair) > available:
            lines.append(" ".join(current))
            current, length = [], 0
        length += len(pair) + (1 if current else 0)
        current.append(pair)
    if current:
        lines.append(" ".join(current))
    return lines


def text_lines(section: TextSection, available: int | None) -> list[str]:
    """Render a text section's lines, word-wrapping any that are too long."""
    if not isinstance(section.text, str):
        raise TypeError(f"text of section {section.name} must be a str")
    out: list[str] = []
    for line in section.text.splitlines():
        if not set(line) <= _TEXT_CHARS:
            raise ValueError(
                f"text of section {section.name} contains control or non-ASCII "
                f"characters: {line!r}"
            )
        if available is None or len(line) <= available:
            out.append(line)
        else:
            out.extend(
                textwrap.wrap(
                    line, available, break_long_words=True, break_on_hyphens=False
                )
                or [""]
            )
    return out


def format_document(
    doc: Document,
    *,
    width: int | None = 80,
    margin: int = 1,
    indent: int | None = None,
    newline: str = "\r\n",
) -> str:
    """Render ``doc`` as text.

    ``width`` is the padded record length; ``None`` disables both wrapping and
    padding. ``margin`` is how many columns at the end of each record stay
    blank. ``indent`` is the column where content starts; by default it is one
    more than the longest section name.
    """
    if width is not None:
        if width < 1:
            raise ValueError("width must be at least 1")
        if margin < 0 or margin >= width:
            raise ValueError(f"margin must be between 0 and {width - 1}")
    names = [section.name for section in doc.sections.values()]
    if indent is None:
        indent = max((len(name) for name in names), default=0) + 1
    if indent < 1:
        raise ValueError("indent must be at least 1")
    available = None if width is None else width - margin - indent
    if available is not None and available < 1:
        raise ValueError(
            f"an indent of {indent} leaves no room for content in {width} columns"
        )

    out: list[str] = []
    for section in doc.sections.values():
        _check_name(section.name, "section name")
        if len(section.name) >= indent:
            raise ValueError(
                f"section name {section.name} does not fit in an indent "
                f"of {indent} columns"
            )
        if isinstance(section, TextSection):
            body = text_lines(section, available)
        elif isinstance(section, Section):
            body = pack_pairs(section, available)
        else:
            raise TypeError(f"{section!r} is not a Section or TextSection")
        for index, content in enumerate(body or [""]):
            lead = section.name.ljust(indent) if index == 0 else " " * indent
            line = (lead + content).rstrip()
            if width is not None:
                line = line.ljust(width)
            out.append(line)
    return "".join(line + newline for line in out)
