"""The strict writer: layout, wrapping, padding, rejections and file output."""

import io
import tempfile

import pytest

import kvsections
from helpers import (
    GOLDEN,
    CommentDocument,
    names,
)
from kvsections import (
    Document,
    Section,
    SectionField,
    TextSection,
)


def test_default_indent_is_longest_name_plus_one():
    doc = kvsections.read(GOLDEN)
    out = doc.document_dumps()
    lines = out.split("\n")[:-1]
    assert all(len(line) == 80 for line in lines)
    # PARAMETERS is the longest name at 10 characters, so content starts at 11
    assert lines[0].startswith("HEADER     VERSION=")
    assert lines[0][10] == " " and lines[0][11] != " "
    assert kvsections.loads(out) == doc


def test_wrapping_respects_margin():
    doc = Document([Section("A", {"K1": "x" * 20, "K2": "y" * 20})])
    # the two pairs need 47 content columns; available = width - margin - indent
    assert doc.document_dumps(width=50, margin=1, indent=2) == (
        "A K1=xxxxxxxxxxxxxxxxxxxx K2=yyyyyyyyyyyyyyyyyyyy".ljust(50) + "\n"
    )
    assert doc.document_dumps(width=49, margin=1, indent=2) == (
        "A K1=xxxxxxxxxxxxxxxxxxxx".ljust(49)
        + "\n"
        + "  K2=yyyyyyyyyyyyyyyyyyyy".ljust(49)
        + "\n"
    )
    assert doc.document_dumps(width=49, margin=0, indent=2) == (
        "A K1=xxxxxxxxxxxxxxxxxxxx K2=yyyyyyyyyyyyyyyyyyyy".ljust(49) + "\n"
    )


def test_pair_too_long_to_fit_gets_a_record_of_its_own():
    doc = Document([Section("A", {"X": "1", "KEY": "v" * 100, "Y": "2"})])
    lines = doc.document_dumps(newline="\n").split("\n")[:-1]
    assert lines[0] == "A X=1".ljust(80)
    assert lines[1] == "  KEY=" + "v" * 100  # longer than width, not padded
    assert lines[2] == "  Y=2".ljust(80)
    assert kvsections.loads(doc.document_dumps()) == doc
    assert doc.document_dumps(width=None) == "A X=1 KEY=" + "v" * 100 + " Y=2\n"


def test_text_indented_beyond_the_width_is_left_unwrapped():
    doc = CommentDocument([TextSection("COMMENT", " " * 20 + "one two three")])
    assert doc.document_dumps(width=24, margin=0, indent=8, newline="\n") == (
        "COMMENT" + " " * 21 + "one two three\n"
    )


def test_width_none_disables_padding_and_wrapping():
    doc = kvsections.read(GOLDEN)
    out = doc.document_dumps(width=None, newline="\n")
    assert out.split("\n")[0] == (
        "HEADER     VERSION=1 FORMAT=TEXT CREATED=20240101 REVISION=003 "
        "AUTHOR=EXAMPLE OWNER=NOBODY"
    )
    assert kvsections.loads(out) == doc


def test_long_text_lines_are_word_wrapped():
    doc = CommentDocument([TextSection("COMMENT", "one two three four five six")])
    assert doc.document_dumps(width=20, margin=0, indent=8, newline="\n") == (
        "COMMENT one two     \n        three four  \n        five six    \n"
    )


def test_writer_wraps_long_words_and_keeps_extra_indent_in_text():
    doc = CommentDocument([TextSection("COMMENT", "a\n  " + "x" * 30 + " end")])
    assert doc.document_dumps(width=24, margin=0, indent=8, newline="\n") == (
        "COMMENT a               \n"
        "          xxxxxxxxxxxxxx\n"
        "          xxxxxxxxxxxxxx\n"
        "          xx end        \n"
    )


def test_empty_section_writes_name_only():
    doc = CommentDocument([Section("A"), TextSection("COMMENT")])
    assert doc.document_dumps(width=None) == "A\nCOMMENT\n"
    assert CommentDocument.document_loads(doc.document_dumps()) == doc


@pytest.mark.parametrize(
    "section",
    [
        Section("A", {"K": "has space"}),
        Section("A", {"K": "café"}),
        Section("A", {"K": "tab\there"}),
        Section("A", {"": "x"}),
        Section("A", {"K=Y": "x"}),
        TextSection("COMMENT", "tab\there"),
        TextSection("COMMENT", "café"),
    ],
)
def test_writer_rejects_unwritable_content(section):
    with pytest.raises(ValueError):
        CommentDocument([section]).document_dumps()


def test_writer_rejects_lowercase_smuggled_into_fields():
    section = Section("A")
    section.section_fields["lower"] = "x"  # bypasses normalization on purpose
    with pytest.raises(ValueError, match="not upper-case"):
        Document([section]).document_dumps()


@pytest.mark.parametrize("text", ["a\x0cb", "a\u2028b", "a\rb", "a\x1cb"])
def test_writer_rejects_line_separators_other_than_newline(text):
    with pytest.raises(ValueError, match="control or non-ASCII"):
        CommentDocument([TextSection("COMMENT", text)]).document_dumps()


def test_writer_rejects_a_section_of_the_wrong_kind():
    with pytest.raises(TypeError, match="text section"):
        CommentDocument([Section("COMMENT", X="1")])  # converted on add() and refused
    smuggled = CommentDocument()
    smuggled.document_sections["COMMENT"] = Section("COMMENT", X="1")  # bypasses add()
    with pytest.raises(ValueError, match="must hold free text"):
        smuggled.document_dumps()
    with pytest.raises(ValueError, match="must hold key/value pairs"):
        Document([TextSection("NOTES", "hello world")]).document_dumps()

    class Doc(Document):
        notes = SectionField(TextSection)

    assert Doc([TextSection("NOTES", "hello world")]).document_dumps(width=None) == (
        "NOTES hello world\n"
    )


def test_writer_indent_follows_the_spelling_not_the_canonical_name():
    class Doc(Document):
        x = SectionField(Section, aliases=("LONGALIAS",))

    doc = Doc.document_loads("LONGALIAS K=1\nY K=2\n")
    assert names(doc) == ["X", "Y"]
    assert (
        doc.document_dumps(width=None, newline="\n") == "LONGALIAS K=1\nY         K=2\n"
    )


def test_indent_must_fit_names():
    doc = Document([Section("HEADER", X="1")])
    with pytest.raises(ValueError, match="does not fit"):
        doc.document_dumps(indent=6)
    with pytest.raises(ValueError):
        doc.document_dumps(width=8, indent=7)


@pytest.mark.parametrize("newline", ["\r\n", "\n", "\r"])
def test_any_input_ending_is_written_as_lf(newline):
    text = newline.join(["A X=1", "B Y=2"]) + newline
    doc = kvsections.loads(text)
    assert doc.document_dumps(width=None) == "A X=1\nB Y=2\n"
    assert doc.document_dumps(width=None, newline="\r\n") == "A X=1\r\nB Y=2\r\n"


def test_written_files_are_lf_whatever_the_platform(tmp_path):
    path = tmp_path / "out.txt"
    doc = CommentDocument(
        [Section("HEADER", VERSION="1"), TextSection("COMMENTS", "text")]
    )
    kvsections.write(doc, path, width=None)
    assert path.read_bytes() == b"HEADER   VERSION=1\nCOMMENTS text\n"
    with open(path, "w") as fp:  # text mode would translate LF on Windows
        kvsections.dump(doc, fp, width=None)
    assert path.read_bytes() == b"HEADER   VERSION=1\nCOMMENTS text\n"
    kvsections.write(doc, path, width=None, newline="\r\n")
    assert path.read_bytes() == b"HEADER   VERSION=1\r\nCOMMENTS text\r\n"


def test_dump_keeps_crlf_whatever_the_file_mode(tmp_path):
    doc = CommentDocument.document_read(GOLDEN)
    path = tmp_path / "out.txt"
    with open(path, "w") as fp:  # default newline translation
        kvsections.dump(doc, fp, indent=12, newline="\r\n")
    assert path.read_bytes() == GOLDEN.read_bytes()
    text = io.StringIO()
    kvsections.dump(doc, text, indent=12, newline="\r\n")
    assert text.getvalue().encode("ascii") == GOLDEN.read_bytes()
    with tempfile.SpooledTemporaryFile(mode="w+b") as spooled:
        kvsections.dump(doc, spooled, indent=12, newline="\r\n")
        spooled.seek(0)
        assert spooled.read() == GOLDEN.read_bytes()


def test_module_level_dumps_matches_the_method():
    doc = CommentDocument([Section("A", X="1"), TextSection("COMMENT", "hi")])
    assert kvsections.dumps(doc, width=None) == doc.document_dumps(width=None)
    assert (
        kvsections.dumps(doc, width=None, newline="\r\n")
        == "A       X=1\r\nCOMMENT hi\r\n"
    )


def test_writer_parameter_validation():
    doc = Document([Section("A", X="1")])
    with pytest.raises(ValueError, match="width"):
        doc.document_dumps(width=0)
    with pytest.raises(ValueError, match="margin"):
        doc.document_dumps(width=10, margin=10)
    with pytest.raises(ValueError, match="indent"):
        doc.document_dumps(indent=0)


def test_writer_rejects_objects_that_are_not_sections():
    doc = Document([Section("A", X="1")])
    doc.document_sections["B"] = "not a section"  # bypasses add()
    with pytest.raises(TypeError):
        doc.document_dumps()
    section = Section("A")
    section.section_fields["K"] = 5  # bypasses normalization
    with pytest.raises(TypeError):
        Document([section]).document_dumps()
    comment = TextSection("COMMENT")
    comment.section_text = 5
    with pytest.raises(TypeError):
        CommentDocument([comment]).document_dumps()


def test_blank_over_long_text_line_becomes_an_empty_record():
    doc = CommentDocument([TextSection("COMMENT", "a\n" + " " * 100 + "\nb")])
    assert doc.document_dumps(width=20, margin=0, indent=8, newline="\n") == (
        "COMMENT a".ljust(20) + "\n" + " " * 20 + "\n" + "        b".ljust(20) + "\n"
    )
