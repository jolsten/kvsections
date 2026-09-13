"""Read and write files made of named sections holding ``KEY=VALUE`` pairs.

A file is a sequence of fixed-width records. The section name sits at the
start of a record; indented records continue the previous section. The rest
of each record holds space-separated ``KEY=VALUE`` pairs, or free text for
comment sections::

    HEADER      VERSION=1 FORMAT=TEXT CREATED=20240101 REVISION=003
                OWNER=NOBODY
    SCHEDULE    START=080000 STOP=173000 DAYS=MON,TUE,WED,THU,FRI

Typical use::

    import kvsections

    doc = kvsections.read("input.txt")
    doc["HEADER"]["REVISION"]       # '003'
    doc["SCHEDULE"]["DAYS"]         # 'MON,TUE,WED,THU,FRI'
    doc["HEADER"]["REVISION"] = "004"
    kvsections.write(doc, "out.txt")

The reader tolerates malformed input and lists what it tolerated in
``doc.warnings``; the writer is strict and raises ``ValueError`` for content
that would not read back. Subclass :class:`Document` and :class:`Section` with
:class:`SectionField` and :class:`Field` descriptors to describe a specific
file with typed attributes. Values are always strings; a field declared with
a ``list[T]`` type splits comma-separated values, and ready-made converters
for dates, times, zero-padded numbers and flags live in
:mod:`kvsections.converters`.
"""

from __future__ import annotations

from typing import IO, Any

from .document import Document, SectionField
from .model import (
    AnySection,
    Converter,
    Field,
    ParseError,
    ParseWarning,
    Section,
    TextSection,
)

__version__ = "0.1.0"

__all__ = [
    "AnySection",
    "Converter",
    "Document",
    "Field",
    "ParseError",
    "ParseWarning",
    "Section",
    "SectionField",
    "TextSection",
    "dump",
    "dumps",
    "load",
    "loads",
    "read",
    "write",
]


def loads(text: str, *, strict: bool = False) -> Document:
    """Parse ``text`` into a generic :class:`Document`.

    Reading is tolerant: problems are recorded in ``doc.warnings``. With
    ``strict=True`` the first problem raises :class:`ParseError` instead.
    """
    return Document.loads(text, strict=strict)


def load(
    fp: IO[Any],
    *,
    strict: bool = False,
    encoding: str = "ascii",
    errors: str = "replace",
) -> Document:
    """Parse an open text or binary file into a generic :class:`Document`."""
    return Document.load(fp, strict=strict, encoding=encoding, errors=errors)


def read(
    path: Any,
    *,
    strict: bool = False,
    encoding: str = "ascii",
    errors: str = "replace",
) -> Document:
    """Parse the file at ``path`` into a generic :class:`Document`."""
    return Document.read(path, strict=strict, encoding=encoding, errors=errors)


def dumps(
    doc: Document,
    *,
    width: int | None = 80,
    margin: int = 1,
    indent: int | None = None,
    newline: str = "\r\n",
) -> str:
    """Render ``doc`` as text.

    Every record is padded to ``width`` columns, of which the last ``margin``
    stay blank; pairs that would cross that limit wrap onto an indented
    continuation record. ``width=None`` disables wrapping and padding.
    ``indent`` is the column where content starts and defaults to one more
    than the longest section name. Raises :class:`ValueError` for content
    that cannot be written faithfully.
    """
    return doc.dumps(width=width, margin=margin, indent=indent, newline=newline)


def dump(doc: Document, fp: IO[Any], **kwargs: Any) -> None:
    """Write ``doc`` to an open text or binary file.

    Accepts the :func:`dumps` options.
    """
    doc.dump(fp, **kwargs)


def write(doc: Document, path: Any, *, encoding: str = "ascii", **kwargs: Any) -> None:
    """Write ``doc`` to the file at ``path``. Accepts the :func:`dumps` options."""
    doc.write(path, encoding=encoding, **kwargs)
