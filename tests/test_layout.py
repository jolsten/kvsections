"""The text-level helpers wrap_records and reorder_records."""

import pytest

import kvsections
from helpers import (
    GOLDEN,
    CommentDocument,
)
from kvsections import (
    Document,
    SectionField,
    TextSection,
    reorder_records,
    wrap_records,
)


def test_wrap_records_reproduces_the_sample_from_unwrapped_input():
    unwrapped = CommentDocument.read(GOLDEN).dumps(
        width=None, indent=12, newline="\r\n"
    )
    assert max(len(line) for line in unwrapped.split("\r\n")) > 80
    assert wrap_records(unwrapped, pad=True).encode("ascii") == GOLDEN.read_bytes()


def test_wrap_records_leaves_fitting_records_untouched():
    text = "HEADER  X=1   Y=2  \nlower  key=val\n\n   \n  cont   Z=3\nNO NEWLINE=1"
    assert wrap_records(text) == text
    padded = wrap_records(text, pad=True)
    assert padded.split("\n") == [line.ljust(80) for line in text.split("\n")]


def test_wrap_records_wraps_headers_continuations_and_text():
    pairs = " ".join(f"K{i}=V{i}" for i in range(10))
    text = (
        "HEADER   " + pairs + "\r\n"
        "\t" + pairs + "\n"
        "COMMENT  " + "word " * 15 + "\n"
        "X " + "A" * 100 + "\r\n"
    )
    out = wrap_records(text, width=40, margin=0)
    assert out == (
        "HEADER   K0=V0 K1=V1 K2=V2 K3=V3 K4=V4\r\n"
        "         K5=V5 K6=V6 K7=V7 K8=V8 K9=V9\r\n"
        "\tK0=V0 K1=V1 K2=V2 K3=V3 K4=V4 K5=V5\n"
        "\tK6=V6 K7=V7 K8=V8 K9=V9\n"
        "COMMENT  word word word word word word\n"
        "         word word word word word word\n"
        "         word word word\n"
        "X " + "A" * 100 + "\r\n"
    )
    before, after = CommentDocument.loads(text), CommentDocument.loads(out)
    assert after["HEADER"] == before["HEADER"] and after["X"] == before["X"]
    # wrapping free text turns spaces into line breaks, so compare words
    assert after["COMMENT"].text.split() == before["COMMENT"].text.split()


def test_wrap_records_terminates_pieces_of_an_unterminated_last_record():
    text = "A X=1\nB " + " ".join(f"K{i}=V" for i in range(20))
    out = wrap_records(text, width=30, margin=0)
    assert not out.endswith("\n") and out.count("\n") > 1
    assert kvsections.loads(out)["B"] == kvsections.loads(text)["B"]


def test_wrap_records_validates_only_its_own_arguments():
    with pytest.raises(ValueError):
        wrap_records("A X=1", width=0)
    with pytest.raises(ValueError):
        wrap_records("A X=1", margin=80)
    assert wrap_records("") == ""
    assert wrap_records("\n\r\n") == "\n\r\n"


def test_reorder_records_matches_document_reorder_without_altering_records():
    text = GOLDEN.read_bytes().decode("ascii")
    order = ["OUTPUT", "header", ..., "SOURCE", "COMMENTS"]
    moved = reorder_records(text, order)
    doc = kvsections.read(GOLDEN)
    doc.reorder(order)
    assert list(kvsections.loads(moved)) == list(doc)
    assert kvsections.loads(moved) == doc
    assert sorted(moved.split("\r\n")) == sorted(text.split("\r\n"))
    assert reorder_records(text, [...]) == text
    assert reorder_records(text, []) == text


def test_reorder_records_keeps_preamble_duplicates_and_unparsed_bytes():
    text = (
        "  stray=1\n"  # before any header: stays first
        "b   X=1\n"  # lower-case header still matches B
        "A   K=V=\x01 weird   \n"  # kept byte for byte
        "KEY=VALUE\n"  # orphan pair: part of A's block
        "\n"
        "B   Y=2\n"  # duplicate B: moves together with the first
        "C   Z=3"  # no final terminator
    )
    assert reorder_records(text, ["C", "B"]) == (
        "  stray=1\n"
        "C   Z=3\n"  # given the file's terminator now that it is not last
        "b   X=1\n"
        "B   Y=2\n"
        "A   K=V=\x01 weird   \n"
        "KEY=VALUE\n"
        "\n"
    )


def test_reorder_records_resolves_aliases_through_a_schema():
    class Doc(Document):
        comments = SectionField(TextSection, "COMMENTS", aliases=("COMMENT",))

    text = "COMMENT text\r\nHEADER X=1\r\n"
    assert reorder_records(text, ["HEADER", ...], document_type=Doc) == (
        "HEADER X=1\r\nCOMMENT text\r\n"
    )
    assert reorder_records(text, [..., "COMMENTS"], document_type=Doc) == (
        "HEADER X=1\r\nCOMMENT text\r\n"
    )
    assert reorder_records(text, [..., "COMMENTS"]) == text  # generic: no alias
    with pytest.raises(ValueError, match="only once"):
        reorder_records(text, [..., "HEADER", ...])


def test_wrap_records_leaves_records_it_cannot_reflow():
    name_only = "N" * 100
    assert wrap_records(name_only, width=40, margin=0) == name_only
    crowded = "N" * 39 + " a b"  # the name and its gap already fill the width
    assert wrap_records(crowded, width=40, margin=0) == crowded
