"""Golden-file invariants and the checks every file in tests/samples must pass."""

import pytest

import kvsections
from helpers import (
    GOLDEN,
    GOLDEN_DOCUMENT,
    CommentDocument,
)
from kvsections import (
    ParseError,
    Section,
    TextSection,
    reorder_records,
    wrap_records,
)
from kvsections.records import (
    BLANK,
    HEADER,
    split_records,
)


def test_sample_file_is_fixed_width_ascii_records():
    data = GOLDEN.read_bytes()
    assert data.isascii()
    assert data.endswith(b"\r\n")
    records = data[:-2].split(b"\r\n")
    assert len(records) == 14
    assert all(len(record) == 80 for record in records)
    # section names start in column 1 and content in column 13
    for record in records:
        assert record[:1] != b" " or record[:12] == b" " * 12
        assert record[12:13] != b" "


def test_sample_parses_to_expected_document():
    doc = CommentDocument.read(GOLDEN)
    assert doc.warnings == []
    assert doc == GOLDEN_DOCUMENT
    # equality ignores order; the file order must be preserved too
    assert list(doc) == list(GOLDEN_DOCUMENT)
    for name in doc:
        if isinstance(doc[name], Section):
            assert list(doc[name]) == list(GOLDEN_DOCUMENT[name])


def test_sample_round_trips_byte_for_byte():
    original = GOLDEN.read_bytes()
    doc = CommentDocument.read(GOLDEN)
    assert doc.dumps(indent=12, newline="\r\n").encode("ascii") == original
    # the same bytes come out of a document built in code, without the reader
    assert GOLDEN_DOCUMENT.dumps(indent=12, newline="\r\n").encode("ascii") == original


def test_write_and_read_file(tmp_path):
    path = tmp_path / "out.txt"
    doc = CommentDocument.read(GOLDEN)
    kvsections.write(doc, path, indent=12, newline="\r\n")
    assert path.read_bytes() == GOLDEN.read_bytes()
    with open(path, "wb") as fp:
        kvsections.dump(doc, fp, indent=12, newline="\r\n")
    assert path.read_bytes() == GOLDEN.read_bytes()


# --------------------------------------------------------------------------
# every file in tests/samples (parametrized by conftest.py)
# --------------------------------------------------------------------------


def test_sample_parses_without_raising(sample):
    doc = CommentDocument.read(sample)
    records = split_records(sample.read_bytes().decode("ascii", "replace"))
    for warning in doc.warnings:
        assert 1 <= warning.lineno <= max(len(records), 1)
    if doc.warnings:
        with pytest.raises(ParseError):
            CommentDocument.read(sample, strict=True)
    else:
        assert CommentDocument.read(sample, strict=True) == doc


def test_sample_round_trips_through_the_model(sample):
    doc = CommentDocument.read(sample)
    try:
        out = doc.dumps()
    except ValueError:
        assert doc.warnings, (
            "the writer refused a document the reader did not warn about"
        )
        return
    again = CommentDocument.loads(out)
    assert again == doc
    assert again.warnings == []
    assert again.dumps() == out  # writing is idempotent


def test_sample_survives_the_layout_helpers(sample):
    text = sample.read_bytes().decode("ascii", "replace")
    assert reorder_records(text, [...]) == text
    doc = CommentDocument.loads(text)
    wrapped = CommentDocument.loads(wrap_records(text))
    assert list(wrapped) == list(doc)
    for name, section in doc.items():
        if isinstance(section, TextSection):
            assert wrapped[name].text.split() == section.text.split()
        else:
            assert wrapped[name] == section


def test_golden_samples_reproduce_byte_for_byte(golden_sample):
    data = golden_sample.read_bytes()
    records = split_records(data.decode("ascii"))
    newline = next(record.ending for record in records if record.ending)
    indent = next(record.content_col for record in records if record.kind == HEADER)
    lengths = {len(record.line) for record in records if record.kind != BLANK}
    width = lengths.pop() if len(lengths) == 1 else None
    doc = CommentDocument.read(golden_sample)
    assert doc.warnings == []
    out = doc.dumps(width=width, indent=indent, newline=newline)
    assert out.encode("ascii") == data
