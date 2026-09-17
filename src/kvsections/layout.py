"""Text-level layout helpers that work on a file's records without parsing it.

They keep every record they do not need to touch byte for byte, so they suit
tidying a file whose content is right but whose layout is not, without the
normalization a full read and write would apply.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import TYPE_CHECKING, Any

from .model import _normalize_key
from .records import CONTINUATION, HEADER, Record, pack, plan_order, split_records

if TYPE_CHECKING:
    from .document import Document

__all__ = ["reorder_records", "wrap_records"]


def _default_ending(records: Iterable[Record]) -> str:
    """The file's line terminator: the first one seen, or LF for a one-line file."""
    return next((record.ending for record in records if record.ending), "\n")


def _reflow(record: Record, limit: int) -> list[str]:
    """Split one over-long record at whitespace into lines of at most ``limit``."""
    words = record.content.split()
    available = limit - record.content_col
    if available < 1 or not words:
        return [record.prefix + record.content]
    indent = record.prefix if record.kind == CONTINUATION else " " * record.content_col
    first, *rest = pack(words, available)
    return [record.prefix + first] + [indent + line for line in rest]


def wrap_records(
    text: str, *, width: int = 80, margin: int = 1, pad: bool = False
) -> str:
    """Re-flow records longer than ``width - margin`` columns onto continuation records.

    Only over-long records change: their content is split at whitespace and
    packed greedily, the first piece keeping the record's original prefix
    (the section name and the spacing after it, or the leading indent of a
    continuation record) and later pieces indented to the same column. A
    single word too long to fit is left on a record of its own. Every other
    record is returned exactly as it was, line endings included; with
    ``pad`` every record is instead padded with spaces to ``width``. Nothing
    is parsed, so names, keys, values, spelling and order are untouched.
    """
    if width < 1:
        raise ValueError("width must be at least 1")
    if margin < 0 or margin >= width:
        raise ValueError(f"margin must be between 0 and {width - 1}")
    limit = width - margin
    records = split_records(text)
    default_ending = _default_ending(records)
    out: list[str] = []
    for record in records:
        body = record.prefix + record.content
        if len(body) <= limit:
            pieces = [body if pad else record.line]
        else:
            pieces = _reflow(record, limit)
        for index, piece in enumerate(pieces):
            last = index == len(pieces) - 1
            ending = record.ending if last else record.ending or default_ending
            out.append((piece.ljust(width) if pad else piece) + ending)
    return "".join(out)


def reorder_records(
    text: str, order: Iterable[Any], *, document_type: type[Document] | None = None
) -> str:
    """Move whole sections of ``text`` into a prescribed order without parsing them.

    A block starts at each header record and runs to the next one; anything
    before the first header stays first. ``order`` has the same form as for
    :meth:`Document.document_reorder`: names in the wanted order, ``...`` for every
    section not named (kept in their current relative order), and names after
    ``...`` last. Pass a schema class as ``document_type`` to resolve its
    aliases; without one, names match by spelling alone. Every byte inside a
    block is kept, including records the reader would only tolerate; a final
    record that lacked a terminator gets the file's terminator if it is no
    longer last.
    """
    canonical = (
        _normalize_key
        if document_type is None
        else document_type.document_canonical_name
    )
    head, tail = plan_order(order, canonical)
    named = set(head) | set(tail)
    preamble: list[Record] = []
    blocks: list[tuple[str, list[Record]]] = []
    for record in split_records(text):
        if record.kind == HEADER:
            blocks.append((canonical(record.name), [record]))
        elif blocks:
            blocks[-1][1].append(record)
        else:
            preamble.append(record)

    def blocks_named(names: Iterable[str]) -> list[list[Record]]:
        return [block for name in names for key, block in blocks if key == name]

    ordered = (
        [preamble]
        + blocks_named(head)
        + [block for key, block in blocks if key not in named]
        + blocks_named(tail)
    )
    records = [record for block in ordered for record in block]
    default_ending = _default_ending(records)
    out: list[str] = []
    for index, record in enumerate(records):
        last = index == len(records) - 1
        ending = record.ending if last else record.ending or default_ending
        out.append(record.line + ending)
    return "".join(out)
