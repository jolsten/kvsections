"""Tolerant reader for the sectioned key/value format.

The reader never gives up on malformed input. Anything it has to guess about
is recorded as a :class:`ParseWarning` on the resulting document, or raised as
a :class:`ParseError` when ``strict`` is requested.

Layout is inferred rather than assumed: a line whose first character is not
whitespace starts a new section named by its first token, and every indented
line continues the current section. Line length, padding and line endings are
not checked.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Callable, TypeVar

from .model import AnySection, ParseError, ParseWarning, Section, TextSection

if TYPE_CHECKING:
    from .document import Document

_D = TypeVar("_D", bound="Document")

_LINE_BREAK = re.compile(r"\r\n|\r|\n")
_HEADER = re.compile(r"\S+\s*")

Warn = Callable[[int, str], None]


def split_lines(text: str) -> list[str]:
    """Split on CRLF, LF or CR, dropping the empty piece after a final newline."""
    lines = _LINE_BREAK.split(text)
    if lines and lines[-1] == "":
        lines.pop()
    return lines


def parse_pairs(section: Section, content: str, lineno: int, warn: Warn) -> None:
    """Add the ``KEY=VALUE`` tokens found in ``content`` to ``section``."""
    for token in content.split():
        key, equals, value = token.partition("=")
        if not key:
            warn(lineno, f"{token!r} has no key; ignored")
            continue
        if not equals:
            warn(lineno, f"{token!r} has no '='; stored with an empty value")
        if key != key.upper():
            warn(lineno, f"key {key!r} is not upper-case; normalized")
            key = key.upper()
        if key in section.fields:
            warn(
                lineno,
                f"duplicate key {key} in section {section.name}; last value wins",
            )
        section.fields[key] = value


class _TextBuffer:
    """Collects the lines of one free-text section until the section ends."""

    def __init__(self, section: TextSection, content_col: int | None):
        self.section = section
        self.content_col = content_col
        self.lines: list[str] = []

    def add(self, line: str) -> None:
        """Add a continuation line, stripping the layout indent but not more."""
        if self.content_col is None:
            self.content_col = len(line) - len(line.lstrip())
        if line[: self.content_col].strip():
            self.lines.append(line.lstrip())
        else:
            self.lines.append(line[self.content_col :])

    def flush(self) -> None:
        lines = self.lines
        while lines and not lines[-1]:
            lines.pop()
        while lines and not lines[0]:
            lines.pop(0)
        text = "\n".join(lines)
        if self.section.text and text:
            self.section.text += "\n" + text
        elif text:
            self.section.text = text


def parse(document_type: type[_D], text: str, *, strict: bool = False) -> _D:
    """Parse ``text`` into a new instance of ``document_type``."""
    doc = document_type()

    def warn(lineno: int, message: str) -> None:
        if strict:
            raise ParseError(lineno, message)
        doc.warnings.append(ParseWarning(lineno, message))

    current: AnySection | None = None
    buffer: _TextBuffer | None = None

    def continuation(line: str, lineno: int) -> None:
        if current is None:
            warn(lineno, "content before the first section header; ignored")
        elif buffer is not None:
            buffer.add(line)
        else:
            assert isinstance(current, Section)
            parse_pairs(current, line, lineno, warn)

    for lineno, raw in enumerate(split_lines(text), 1):
        line = raw.rstrip()
        if not line:
            if buffer is not None:
                buffer.lines.append("")
            continue
        if line[0].isspace():
            continuation(line, lineno)
            continue

        match = _HEADER.match(line)
        assert match is not None
        name = match.group().rstrip()
        rest = line[match.end() :]
        if "=" in name:
            warn(lineno, "line has no section name; treated as a continuation")
            continuation(line, lineno)
            continue

        if buffer is not None:
            buffer.flush()
            buffer = None
        if name != name.upper():
            warn(lineno, f"section name {name!r} is not upper-case; normalized")
            name = name.upper()
        canonical = document_type.canonical_name(name)
        existing = doc.sections.get(canonical)
        if existing is not None:
            what = name if name == canonical else f"{name} (alias of {canonical})"
            warn(lineno, f"duplicate section {what}; merged into the earlier one")
            current = existing
        else:
            current = doc.add(document_type.new_section(name))

        if isinstance(current, TextSection):
            buffer = _TextBuffer(current, match.end() if rest else None)
            buffer.lines.append(rest)
        else:
            parse_pairs(current, rest, lineno, warn)

    if buffer is not None:
        buffer.flush()
    return doc
