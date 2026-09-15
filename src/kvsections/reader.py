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

from typing import TYPE_CHECKING, TypeVar

from .errors import ParseError, ParseWarning
from .model import BaseSection, Section, TextSection
from .records import BLANK, CONTINUATION, TEXT_CHARS, TOKEN_CHARS, split_records

if TYPE_CHECKING:
    from .document import Document

_D = TypeVar("_D", bound="Document")


class _Reporter:
    """Records what the reader tolerates, or raises at the first problem."""

    def __init__(self, doc: Document, strict: bool):
        self.doc = doc
        self.strict = strict

    def warn(self, lineno: int, message: str) -> None:
        if self.strict:
            raise ParseError(lineno, message)
        self.doc.warnings.append(ParseWarning(lineno, message))

    def check_chars(
        self, lineno: int, text: str, allowed: frozenset[str], what: str
    ) -> None:
        """Warn when ``text`` holds characters the writer would refuse."""
        if not set(text) <= allowed:
            self.warn(
                lineno,
                f"{what} {text!r} contains characters that cannot be written back",
            )


def parse_pairs(section: Section, content: str, lineno: int, report: _Reporter) -> None:
    """Add the ``KEY=VALUE`` tokens found in ``content`` to ``section``."""
    for token in content.split():
        key, equals, value = token.partition("=")
        if not key:
            report.warn(lineno, f"{token!r} has no key; ignored")
            continue
        if not equals:
            report.warn(lineno, f"{token!r} has no '='; stored with an empty value")
        if key != key.upper():
            report.warn(lineno, f"key {key!r} is not upper-case; normalized")
            key = key.upper()
        report.check_chars(lineno, key, TOKEN_CHARS, "key")
        report.check_chars(lineno, value, TOKEN_CHARS, f"value of {key}")
        if key in section.fields:
            report.warn(
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

    def add(self, line: str) -> str:
        """Add a continuation line, stripping the layout indent but not more.

        Returns the content that was kept.
        """
        if self.content_col is None:
            self.content_col = len(line) - len(line.lstrip())
        if line[: self.content_col].strip():
            content = line.lstrip()
        else:
            content = line[self.content_col :]
        self.lines.append(content)
        return content

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
    report = _Reporter(doc, strict)

    if text.startswith("\ufeff"):
        report.warn(1, "UTF-8 byte order mark ignored")
        text = text[1:]

    current: BaseSection | None = None
    buffer: _TextBuffer | None = None

    def continuation(line: str, lineno: int) -> None:
        if current is None:
            report.warn(lineno, "content before the first section header; ignored")
        elif buffer is not None:
            report.check_chars(lineno, buffer.add(line), TEXT_CHARS, "text")
        else:
            assert isinstance(current, Section)
            parse_pairs(current, line, lineno, report)

    for lineno, record in enumerate(split_records(text), 1):
        if record.kind == BLANK:
            if buffer is not None:
                buffer.lines.append("")
            continue
        line = record.prefix + record.content
        if record.kind == CONTINUATION:
            if not record.prefix:
                report.warn(
                    lineno, "line has no section name; treated as a continuation"
                )
            continuation(line, lineno)
            continue

        name = record.name
        rest = record.content

        if buffer is not None:
            buffer.flush()
            buffer = None
        if name != name.upper():
            report.warn(lineno, f"section name {name!r} is not upper-case; normalized")
            name = name.upper()
        report.check_chars(lineno, name, TOKEN_CHARS, "section name")
        canonical = document_type.canonical_name(name)
        existing = doc.sections.get(canonical)
        if existing is not None:
            what = name if name == canonical else f"{name} (alias of {canonical})"
            report.warn(
                lineno, f"duplicate section {what}; merged into the earlier one"
            )
            current = existing
        else:
            current = doc.add(document_type.new_section(name))

        if isinstance(current, TextSection):
            buffer = _TextBuffer(current, record.content_col if rest else None)
            buffer.lines.append(rest)
            report.check_chars(lineno, rest, TEXT_CHARS, "text")
        else:
            assert isinstance(current, Section)
            parse_pairs(current, rest, lineno, report)

    if buffer is not None:
        buffer.flush()
    return doc
