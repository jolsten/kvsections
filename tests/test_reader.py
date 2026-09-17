"""The tolerant reader: warnings, strict mode, encodings and text sections."""

import io

import pytest

import kvsections
from helpers import (
    GOLDEN,
    CommentDocument,
    names,
)
from kvsections import (
    Document,
    ParseError,
    Section,
    SectionField,
    TextSection,
)


def test_comma_values_stay_strings():
    doc = kvsections.read(GOLDEN)
    assert doc["OPTIONS"]["FLAGS"] == "A,B,C,D"
    assert doc["SCHEDULE"]["DAYS"] == "MON,TUE,WED,THU,FRI"
    assert doc["TARGET"]["RATE"] == "12.5"
    assert kvsections.loads("X A=,,B")["X"]["A"] == ",,B"


def test_layout_is_inferred_not_fixed():
    text = "HEADER VERSION=1\n  OWNER=NOBODY\nAVERYLONGSECTIONNAME KEY=VAL\n\tTAB=1\n"
    doc = kvsections.loads(text)
    assert doc["HEADER"] == Section("HEADER", {"VERSION": "1", "OWNER": "NOBODY"})
    assert doc["AVERYLONGSECTIONNAME"] == Section(
        "AVERYLONGSECTIONNAME", KEY="VAL", TAB="1"
    )
    assert doc.document_warnings == []


@pytest.mark.parametrize("newline", ["\r\n", "\n", "\r"])
def test_line_endings(newline):
    text = newline.join(["A X=1", "  Y=2", "B Z=3"]) + newline
    doc = kvsections.loads(text)
    assert doc["A"] == Section("A", X="1", Y="2")
    assert doc["B"] == Section("B", Z="3")


def test_no_trailing_newline_and_blank_lines():
    doc = kvsections.loads("\n\nA X=1\n\n  Y=2\n\nB Z=3")
    assert doc["A"] == Section("A", X="1", Y="2")
    assert doc["B"] == Section("B", Z="3")
    assert doc.document_warnings == []


def test_empty_input():
    doc = kvsections.loads("")
    assert len(doc) == 0
    assert doc.document_dumps() == ""


def test_empty_value_and_equals_in_value():
    doc = kvsections.loads("A X= Y=a=b")
    assert doc["A"]["X"] == ""
    assert doc["A"]["Y"] == "a=b"
    assert doc.document_warnings == []


def test_tolerates_lowercase():
    doc = kvsections.loads("header owner=nobody")
    assert doc["HEADER"]["OWNER"] == "nobody"
    assert [w.message for w in doc.document_warnings] == [
        "section name 'header' is not upper-case; normalized",
        "key 'owner' is not upper-case; normalized",
    ]


def test_tolerates_duplicate_section_by_merging():
    doc = kvsections.loads("A X=1\nB Y=2\nA Z=3 X=4\n")
    assert names(doc) == ["A", "B"]
    assert doc["A"] == Section("A", X="4", Z="3")
    assert [str(w) for w in doc.document_warnings] == [
        "line 3: duplicate section A; merged into the earlier one",
        "line 3: duplicate key X in section A; last value wins",
    ]


def test_tolerates_missing_equals_and_missing_key():
    doc = kvsections.loads("A FLAG =1 X=2")
    assert doc["A"] == Section("A", FLAG="", X="2")
    assert [w.message for w in doc.document_warnings] == [
        "'FLAG' has no '='; stored with an empty value",
        "'=1' has no key; ignored",
    ]


def test_tolerates_content_before_header_and_header_without_name():
    doc = kvsections.loads("  X=1\nA Y=2\nZ=3\n")
    assert doc["A"] == Section("A", Y="2", Z="3")
    assert [w.lineno for w in doc.document_warnings] == [1, 3]
    assert "ignored" in doc.document_warnings[0].message
    assert "no section name" in doc.document_warnings[1].message


def test_strict_raises_parse_error():
    with pytest.raises(ParseError) as info:
        kvsections.loads("A x=1", strict=True)
    assert info.value.lineno == 1
    assert "not upper-case" in str(info.value)


def test_load_from_text_and_binary_files():
    text = "A X=1\r\n"
    assert kvsections.load(io.StringIO(text))["A"]["X"] == "1"
    assert kvsections.load(io.BytesIO(text.encode()))["A"]["X"] == "1"


def test_undecodable_bytes_are_replaced_with_a_warning(tmp_path):
    path = tmp_path / "bad.txt"
    path.write_bytes(b"A X=caf\xe9 CAF\xe9=1\r\n")
    doc = kvsections.read(path)
    assert doc["A"]["X"] == "caf\ufffd"
    assert [w.message for w in doc.document_warnings] == [
        "value of X 'caf\ufffd' contains characters that cannot be written back",
        "key 'CAF\ufffd' contains characters that cannot be written back",
    ]
    with pytest.raises(ParseError, match="cannot be written back"):
        kvsections.read(path, strict=True)
    with pytest.raises(ValueError):
        doc.document_dumps()
    latin = kvsections.read(path, encoding="latin-1")
    assert latin["A"]["X"] == "caf\u00e9"
    assert len(latin.document_warnings) == 3  # value chars, key case, key chars


def test_utf8_bom_is_dropped_with_a_warning(tmp_path):
    path = tmp_path / "bom.txt"
    path.write_bytes(b"\xef\xbb\xbfHEADER VERSION=1\r\n")
    doc = kvsections.read(path)
    assert names(doc) == ["HEADER"]
    assert [str(w) for w in doc.document_warnings] == [
        "line 1: UTF-8 byte order mark ignored"
    ]
    with open(path, "rb") as fp:
        assert names(kvsections.load(fp)) == ["HEADER"]
    assert names(kvsections.loads("\ufeffHEADER VERSION=1")) == ["HEADER"]
    with pytest.raises(ParseError, match="byte order mark"):
        kvsections.read(path, strict=True)


def test_unwritable_characters_in_comments_and_names_are_reported():
    doc = CommentDocument.document_loads(
        "COMMENT     one\ttwo\n            three\tfour\n"
    )
    assert doc["COMMENT"].section_text == "one\ttwo\nthree\tfour"
    assert [str(w) for w in doc.document_warnings] == [
        "line 1: text 'one\\ttwo' contains characters that cannot be written back",
        "line 2: text 'three\\tfour' contains characters that cannot be written back",
    ]
    doc = CommentDocument.document_loads("HEAD\x01ER X=1\n")
    assert [w.message for w in doc.document_warnings] == [
        "section name 'HEAD\\x01ER' contains characters that cannot be written back"
    ]


def test_readme_warnings_example():
    doc = kvsections.loads("header owner=nobody\nheader x=1")
    assert [str(w) for w in doc.document_warnings] == [
        "line 1: section name 'header' is not upper-case; normalized",
        "line 1: key 'owner' is not upper-case; normalized",
        "line 2: section name 'header' is not upper-case; normalized",
        "line 2: duplicate section HEADER; merged into the earlier one",
        "line 2: key 'x' is not upper-case; normalized",
    ]


def test_comment_section_is_free_text():
    text = (
        "COMMENT     This is a comment with KEY=VALUE inside.\r\n"
        "            Second line, indented.\r\n"
        "              Third line keeps extra indent.\r\n"
        "\r\n"
        "            After a blank line.\r\n"
        "OUTPUT      TYPE=REPORT\r\n"
    )
    doc = CommentDocument.document_loads(text)
    comment = doc["COMMENT"]
    assert isinstance(comment, TextSection)
    assert comment.section_text == (
        "This is a comment with KEY=VALUE inside.\n"
        "Second line, indented.\n"
        "  Third line keeps extra indent.\n"
        "\n"
        "After a blank line."
    )
    assert doc["OUTPUT"]["TYPE"] == "REPORT"
    assert doc.document_warnings == []


def test_comment_with_empty_header_line_and_trailing_blanks():
    doc = CommentDocument.document_loads(
        "COMMENTS\n    hello\n      world\n\n\nA X=1\n"
    )
    assert doc["COMMENTS"].section_text == "hello\n  world"


def test_comment_continuation_indented_less_than_content_column():
    doc = CommentDocument.document_loads("COMMENT     first\n  second\n")
    assert doc["COMMENT"].section_text == "first\nsecond"


def test_comment_round_trip():
    text = (
        "COMMENT This is a comment.\r\n"
        "        Second line.\r\n"
        "\r\n"
        "        Fourth line.\r\n"
        "OUTPUT  TYPE=REPORT\r\n"
    )
    doc = CommentDocument.document_loads(text)
    assert doc.document_dumps(width=None, newline="\r\n") == text.replace(
        "\r\n        \r\n", "\r\n\r\n"
    )
    assert CommentDocument.document_loads(doc.document_dumps()) == doc


def test_comment_text_starts_at_its_first_character():
    # Leading whitespace on the first line, blank edge lines and trailing
    # spaces cannot be told apart from layout, so one round trip drops them
    # and the result is stable from then on.
    doc = CommentDocument([TextSection("COMMENT", "\n   indented  \nsecond   \n\n")])
    back = CommentDocument.document_loads(doc.document_dumps())["COMMENT"]
    assert back.section_text == "indented\nsecond"
    again = CommentDocument.document_loads(CommentDocument([back]).document_dumps())[
        "COMMENT"
    ]
    assert again == back


def test_free_text_sections_are_schema_registrations():
    class Doc(Document):
        notes = SectionField(TextSection)
        comment = SectionField(Section)

    doc = Doc.document_loads("COMMENT X=1\nNOTES some text here\n")
    assert doc["COMMENT"] == Section("COMMENT", X="1")
    assert doc["NOTES"] == TextSection("NOTES", "some text here")
    assert Document.document_section_type("comment") is Section
    assert Doc.document_section_type("comment") is Section
