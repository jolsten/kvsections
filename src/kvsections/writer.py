"""Strict writer for the sectioned key/value format.

Unlike the reader, the writer refuses anything that would not read back
correctly: names and keys must be upper-case printable ASCII without spaces
or ``=``, and values must contain no whitespace. Record width is a
convention rather than a limit: a pair or word that cannot fit is written
on a record of its own, longer than the width.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from .model import BaseSection, Section, TextSection
from .records import TEXT_CHARS, TOKEN_CHARS, pack

if TYPE_CHECKING:
    from .document import Document


def _check_token(token: str, what: str) -> None:
    if not isinstance(token, str):
        raise TypeError(f"{what} must be a str, not {type(token).__name__}")
    if not set(token) <= TOKEN_CHARS:
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
    for key, value in section.section_fields.items():
        _check_name(key, f"key in section {section.section_name}")
        pairs.append(f"{key}={format_value(key, value)}")
    if available is None:
        return [" ".join(pairs)] if pairs else []
    return pack(pairs, available)


def text_lines(section: TextSection, available: int | None) -> list[str]:
    """Render a text section's lines, word-wrapping any that are too long."""
    text = section.section_text
    if not isinstance(text, str):
        raise TypeError(f"text of section {section.section_name} must be a str")
    bad = set(text) - TEXT_CHARS - {"\n"}
    if bad:
        raise ValueError(
            f"text of section {section.section_name} contains control or non-ASCII "
            f"characters: {''.join(sorted(bad))!r}"
        )
    lines = text.split("\n")
    if lines[-1] == "":
        lines.pop()
    out: list[str] = []
    for line in lines:
        words = line.split()
        if available is None or len(line) <= available:
            out.append(line)
        elif not words:
            out.append("")
        else:
            lead = line[: len(line) - len(line.lstrip())]
            room = available - len(lead)
            if room < 1:
                out.append(line)
            else:
                out.extend(lead + piece for piece in pack(words, room, break_long=True))
    return out


def format_document(
    doc: Document,
    *,
    width: int | None = 80,
    margin: int = 1,
    indent: int | None = None,
    newline: str = "\n",
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
    for section in doc.document_sections.values():
        if not isinstance(section, BaseSection):
            raise TypeError(f"{section!r} is not a section")
    names = [section.section_name for section in doc.document_sections.values()]
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
    for section in doc.document_sections.values():
        _check_name(section.section_name, "section name")
        expected = type(doc).document_section_type(section.section_name)
        if issubclass(expected, TextSection) != isinstance(section, TextSection):
            kind = (
                "free text" if issubclass(expected, TextSection) else "key/value pairs"
            )
            raise ValueError(
                f"section {section.section_name} must hold {kind} "
                f"in a {type(doc).__name__}"
            )
        if len(section.section_name) >= indent:
            raise ValueError(
                f"section name {section.section_name} does not fit in an indent "
                f"of {indent} columns"
            )
        if isinstance(section, TextSection):
            body = text_lines(section, available)
        else:
            assert isinstance(section, Section)
            body = pack_pairs(section, available)
        for index, content in enumerate(body or [""]):
            lead = section.section_name.ljust(indent) if index == 0 else " " * indent
            line = (lead + content).rstrip()
            if width is not None:
                line = line.ljust(width)
            out.append(line)
    return "".join(line + newline for line in out)
