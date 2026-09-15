"""Record-level primitives shared by the reader, writer and layout helpers."""

from kvsections.records import (
    BLANK,
    CONTINUATION,
    HEADER,
    Record,
    pack,
    split_records,
)


def test_record_from_line_kinds():
    header = Record.from_line("HEADER   VERSION=1  ", "\r\n")
    assert header.kind == HEADER
    assert (header.name, header.prefix, header.content) == (
        "HEADER",
        "HEADER   ",
        "VERSION=1",
    )
    assert header.content_col == 9
    assert header.line + header.ending == "HEADER   VERSION=1  \r\n"
    cont = Record.from_line("  \tX=1")
    assert cont.kind == CONTINUATION
    assert (cont.prefix, cont.content) == ("  \t", "X=1")
    orphan = Record.from_line("KEY=VALUE X=1")
    assert orphan.kind == CONTINUATION
    assert (orphan.prefix, orphan.content) == ("", "KEY=VALUE X=1")
    assert Record.from_line("   ").kind == BLANK
    assert Record.from_line("").kind == BLANK
    assert Record.from_line("NAME").content == ""


def test_split_records_keeps_each_ending():
    records = split_records("A X=1\r\nB\n\rC")
    assert [(r.line, r.ending) for r in records] == [
        ("A X=1", "\r\n"),
        ("B", "\n"),
        ("", "\r"),
        ("C", ""),
    ]
    assert "".join(r.line + r.ending for r in records) == "A X=1\r\nB\n\rC"
    assert split_records("") == []


def test_pack_greedy_and_break_long():
    words = ["aa", "bbb", "cccccc", "d"]
    assert pack(words, 6) == ["aa bbb", "cccccc", "d"]
    assert pack(words, 4) == ["aa", "bbb", "cccccc", "d"]
    assert pack(words, 4, break_long=True) == ["aa", "bbb", "cccc", "cc d"]
    assert pack([], 10) == []
