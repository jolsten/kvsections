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
``doc.document_warnings``; the writer is strict and raises ``ValueError`` for content
that would not read back. Subclass :class:`Document` and :class:`Section` with
:class:`SectionField` and :class:`Field` descriptors to describe a specific
file with typed attributes. Values are always strings; a field declared with
a ``list[T]`` type splits comma-separated values, and ready-made converters
for dates, times, zero-padded numbers and flags live in
:mod:`kvsections.converters`.
"""

from __future__ import annotations

from importlib.metadata import PackageNotFoundError, version

from .document import Document, SectionField
from .errors import ParseError, ParseWarning, Problem
from .fields import Converter, Field
from .layout import reorder_records, wrap_records
from .model import BaseSection, Section, TextSection

try:
    __version__ = version("kvsections")
except PackageNotFoundError:  # pragma: no cover - only when not installed
    __version__ = "0+unknown"

__all__ = [
    "BaseSection",
    "Converter",
    "Document",
    "Field",
    "ParseError",
    "ParseWarning",
    "Problem",
    "Section",
    "SectionField",
    "TextSection",
    "dump",
    "dumps",
    "load",
    "loads",
    "read",
    "write",
    "reorder_records",
    "wrap_records",
]

# The module-level functions are the generic Document's methods: ``loads``,
# ``load`` and ``read`` parse into a plain Document, and ``dumps``, ``dump``
# and ``write`` take the document as their first argument. A schema class
# offers the same methods for typed documents.
loads = Document.document_loads
load = Document.document_load
read = Document.document_read
dumps = Document.document_dumps
dump = Document.document_dump
write = Document.document_write
