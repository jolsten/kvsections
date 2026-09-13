import io
from datetime import date, time
from enum import Enum
from pathlib import Path

import pytest

import kvsections
from kvsections import (
    Converter,
    Document,
    Field,
    ParseError,
    Section,
    SectionField,
    TextSection,
)
from kvsections.converters import (
    HHMM,
    HHMMSS,
    YES_NO,
    YYMMDD,
    YYYYMMDD,
    enum_by_name,
    enum_by_value,
    flag,
    one_of,
    zero_padded,
)

SAMPLE = Path(__file__).resolve().parent / "sample1.txt"

# Everything sample1.txt contains, in file order. Values stay strings, so
# leading zeros and comma-separated lists survive verbatim.
SAMPLE_DOCUMENT = Document(
    [
        Section(
            "HEADER",
            VERSION="1",
            FORMAT="TEXT",
            CREATED="20240101",
            REVISION="003",
            AUTHOR="EXAMPLE",
            OWNER="NOBODY",  # from a continuation record
        ),
        Section(
            "CONFIG",
            NAME="DEFAULT",
            MODE="NORMAL",
            LEVEL="2",
            ENABLED="YES",
            TIMEOUT="30",
            RETRIES="3",
            BUFFER="4096",
            VERBOSE="NO",
        ),
        Section(
            "SOURCE", TYPE="FILE", PATH="INPUT.DAT", ENCODING="ASCII", SIZE="001024"
        ),
        Section("TARGET", TYPE="STREAM", NAME="MAIN", RATE="12.5", LIMIT="100"),
        Section("OPTIONS", FLAGS="A,B,C,D", COMPRESS="NONE", CHECKSUM="CRC32"),
        Section("FILTER", MINIMUM="0.5", MAXIMUM="99.5", WINDOW="10"),
        Section(
            "SCHEDULE",
            START="080000",
            STOP="173000",
            INTERVAL="15",
            DAYS="MON,TUE,WED,THU,FRI",
            TIMEZONE="UTC",
        ),
        Section(
            "PARAMETERS",
            ALPHA="1.0",
            BETA="0.25",
            GAMMA="100",
            DELTA="0.001",
            EPSILON="5",
            ZETA="42",
            ETA="7",
            THETA="3.14",
        ),
        Section("OUTPUT", TYPE="REPORT", FORMAT="TABLE"),
        TextSection("COMMENTS", "This is a freeform comment section."),
    ]
)


# --------------------------------------------------------------------------
# the sample file
# --------------------------------------------------------------------------


def test_sample_file_is_fixed_width_ascii_records():
    data = SAMPLE.read_bytes()
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
    doc = kvsections.read(SAMPLE)
    assert doc.warnings == []
    assert doc == SAMPLE_DOCUMENT
    # equality ignores order; the file order must be preserved too
    assert list(doc) == list(SAMPLE_DOCUMENT)
    for name in doc:
        if isinstance(doc[name], Section):
            assert list(doc[name]) == list(SAMPLE_DOCUMENT[name])


# --------------------------------------------------------------------------
# reading
# --------------------------------------------------------------------------


def test_comma_values_stay_strings():
    doc = kvsections.read(SAMPLE)
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
    assert doc.warnings == []


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
    assert doc.warnings == []


def test_empty_input():
    doc = kvsections.loads("")
    assert len(doc) == 0
    assert doc.dumps() == ""


def test_empty_value_and_equals_in_value():
    doc = kvsections.loads("A X= Y=a=b")
    assert doc["A"]["X"] == ""
    assert doc["A"]["Y"] == "a=b"
    assert doc.warnings == []


def test_tolerates_lowercase():
    doc = kvsections.loads("header owner=nobody")
    assert doc["HEADER"]["OWNER"] == "nobody"
    assert [w.message for w in doc.warnings] == [
        "section name 'header' is not upper-case; normalized",
        "key 'owner' is not upper-case; normalized",
    ]


def test_tolerates_duplicate_section_by_merging():
    doc = kvsections.loads("A X=1\nB Y=2\nA Z=3 X=4\n")
    assert list(doc) == ["A", "B"]
    assert doc["A"] == Section("A", X="4", Z="3")
    assert [str(w) for w in doc.warnings] == [
        "line 3: duplicate section A; merged into the earlier one",
        "line 3: duplicate key X in section A; last value wins",
    ]


def test_tolerates_missing_equals_and_missing_key():
    doc = kvsections.loads("A FLAG =1 X=2")
    assert doc["A"] == Section("A", FLAG="", X="2")
    assert [w.message for w in doc.warnings] == [
        "'FLAG' has no '='; stored with an empty value",
        "'=1' has no key; ignored",
    ]


def test_tolerates_content_before_header_and_header_without_name():
    doc = kvsections.loads("  X=1\nA Y=2\nZ=3\n")
    assert doc["A"] == Section("A", Y="2", Z="3")
    assert [w.lineno for w in doc.warnings] == [1, 3]
    assert "ignored" in doc.warnings[0].message
    assert "no section name" in doc.warnings[1].message


def test_strict_raises_parse_error():
    with pytest.raises(ParseError) as info:
        kvsections.loads("A x=1", strict=True)
    assert info.value.lineno == 1
    assert "not upper-case" in str(info.value)


def test_load_from_text_and_binary_files():
    text = "A X=1\r\n"
    assert kvsections.load(io.StringIO(text))["A"]["X"] == "1"
    assert kvsections.load(io.BytesIO(text.encode()))["A"]["X"] == "1"


def test_non_ascii_bytes_are_replaced_not_fatal(tmp_path):
    path = tmp_path / "bad.txt"
    path.write_bytes(b"A X=caf\xe9\r\n")
    doc = kvsections.read(path)
    assert doc["A"]["X"] == "caf�"
    with pytest.raises(ValueError):
        doc.dumps()


# --------------------------------------------------------------------------
# text sections
# --------------------------------------------------------------------------


def test_comment_section_is_free_text():
    text = (
        "COMMENT     This is a comment with KEY=VALUE inside.\r\n"
        "            Second line, indented.\r\n"
        "              Third line keeps extra indent.\r\n"
        "\r\n"
        "            After a blank line.\r\n"
        "OUTPUT      TYPE=REPORT\r\n"
    )
    doc = kvsections.loads(text)
    comment = doc["COMMENT"]
    assert isinstance(comment, TextSection)
    assert comment.text == (
        "This is a comment with KEY=VALUE inside.\n"
        "Second line, indented.\n"
        "  Third line keeps extra indent.\n"
        "\n"
        "After a blank line."
    )
    assert doc["OUTPUT"]["TYPE"] == "REPORT"
    assert doc.warnings == []


def test_comment_with_empty_header_line_and_trailing_blanks():
    doc = kvsections.loads("COMMENTS\n    hello\n      world\n\n\nA X=1\n")
    assert doc["COMMENTS"].text == "hello\n  world"


def test_comment_continuation_indented_less_than_content_column():
    doc = kvsections.loads("COMMENT     first\n  second\n")
    assert doc["COMMENT"].text == "first\nsecond"


def test_comment_round_trip():
    text = (
        "COMMENT This is a comment.\r\n"
        "        Second line.\r\n"
        "\r\n"
        "        Fourth line.\r\n"
        "OUTPUT  TYPE=REPORT\r\n"
    )
    doc = kvsections.loads(text)
    assert doc.dumps(width=None) == text.replace("\r\n        \r\n", "\r\n\r\n")
    assert kvsections.loads(doc.dumps()) == doc


def test_free_text_sections_configurable():
    class Doc(Document):
        free_text_sections = {"notes"}

    doc = Doc.loads("COMMENT X=1\nNOTES some text here\n")
    assert doc["COMMENT"] == Section("COMMENT", X="1")
    assert doc["NOTES"] == TextSection("NOTES", "some text here")


# --------------------------------------------------------------------------
# writing
# --------------------------------------------------------------------------


def test_sample_round_trips_byte_for_byte():
    original = SAMPLE.read_bytes()
    doc = kvsections.read(SAMPLE)
    assert doc.dumps(indent=12).encode("ascii") == original
    # the same bytes come out of a document built in code, without the reader
    assert SAMPLE_DOCUMENT.dumps(indent=12).encode("ascii") == original


def test_default_indent_is_longest_name_plus_one():
    doc = kvsections.read(SAMPLE)
    out = doc.dumps()
    lines = out.split("\r\n")[:-1]
    assert all(len(line) == 80 for line in lines)
    # PARAMETERS is the longest name at 10 characters, so content starts at 11
    assert lines[0].startswith("HEADER     VERSION=")
    assert lines[0][10] == " " and lines[0][11] != " "
    assert kvsections.loads(out) == doc


def test_wrapping_respects_margin():
    doc = Document([Section("A", {"K1": "x" * 20, "K2": "y" * 20})])
    # the two pairs need 47 content columns; available = width - margin - indent
    assert doc.dumps(width=50, margin=1, indent=2) == (
        "A K1=xxxxxxxxxxxxxxxxxxxx K2=yyyyyyyyyyyyyyyyyyyy".ljust(50) + "\r\n"
    )
    assert doc.dumps(width=49, margin=1, indent=2) == (
        "A K1=xxxxxxxxxxxxxxxxxxxx".ljust(49)
        + "\r\n"
        + "  K2=yyyyyyyyyyyyyyyyyyyy".ljust(49)
        + "\r\n"
    )
    assert doc.dumps(width=49, margin=0, indent=2) == (
        "A K1=xxxxxxxxxxxxxxxxxxxx K2=yyyyyyyyyyyyyyyyyyyy".ljust(49) + "\r\n"
    )


def test_pair_too_long_to_fit_raises():
    doc = Document([Section("A", {"KEY": "v" * 100})])
    with pytest.raises(ValueError, match="longer than"):
        doc.dumps()
    assert doc.dumps(width=None) == "A KEY=" + "v" * 100 + "\r\n"


def test_width_none_disables_padding_and_wrapping():
    doc = kvsections.read(SAMPLE)
    out = doc.dumps(width=None, newline="\n")
    assert out.split("\n")[0] == (
        "HEADER     VERSION=1 FORMAT=TEXT CREATED=20240101 REVISION=003 "
        "AUTHOR=EXAMPLE OWNER=NOBODY"
    )
    assert kvsections.loads(out) == doc


def test_long_text_lines_are_word_wrapped():
    doc = Document([TextSection("COMMENT", "one two three four five six")])
    assert doc.dumps(width=20, margin=0, indent=8, newline="\n") == (
        "COMMENT one two     \n        three four  \n        five six    \n"
    )


def test_empty_section_writes_name_only():
    doc = Document([Section("A"), TextSection("COMMENT")])
    assert doc.dumps(width=None) == "A\r\nCOMMENT\r\n"
    assert kvsections.loads(doc.dumps()) == doc


def test_lists_assigned_to_raw_keys_are_joined_with_commas():
    section = Section("A", {"L": ["x", "y"], "ONE": ["z"], "NONE": [], "N": [1, 2]})
    assert section.fields == {"L": "x,y", "ONE": "z", "NONE": "", "N": "1,2"}
    assert Document([section]).dumps(width=None) == "A L=x,y ONE=z NONE= N=1,2\r\n"
    with pytest.raises(ValueError, match="comma"):
        section["BAD"] = ["a,b"]


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
        Document([section]).dumps()


def test_writer_rejects_lowercase_smuggled_into_fields():
    section = Section("A")
    section.fields["lower"] = "x"  # bypasses normalization on purpose
    with pytest.raises(ValueError, match="not upper-case"):
        Document([section]).dumps()


def test_indent_must_fit_names():
    doc = Document([Section("HEADER", X="1")])
    with pytest.raises(ValueError, match="does not fit"):
        doc.dumps(indent=6)
    with pytest.raises(ValueError):
        doc.dumps(width=8, indent=7)


def test_write_and_read_file(tmp_path):
    path = tmp_path / "out.txt"
    doc = kvsections.read(SAMPLE)
    kvsections.write(doc, path, indent=12)
    assert path.read_bytes() == SAMPLE.read_bytes()
    with open(path, "wb") as fp:
        kvsections.dump(doc, fp, indent=12)
    assert path.read_bytes() == SAMPLE.read_bytes()


# --------------------------------------------------------------------------
# model
# --------------------------------------------------------------------------


def test_section_normalizes_keys_and_values():
    section = Section("header", {"owner": "NOBODY"}, version=42, items=("a", 1))
    assert section.name == "HEADER"
    assert section.fields == {"OWNER": "NOBODY", "VERSION": "42", "ITEMS": "a,1"}
    assert section["owner"] == "NOBODY"
    assert "Owner" in section
    del section["OWNER"]
    assert "owner" not in section
    assert list(section) == ["VERSION", "ITEMS"]


def test_section_requires_name_unless_class_provides_one():
    with pytest.raises(TypeError):
        Section()

    class Header(Section):
        section_name = "HEADER"

    assert Header().name == "HEADER"
    assert Header("OTHER").name == "OTHER"


def test_document_mapping_behaviour():
    doc = Document()
    doc["a"] = Section("A", X="1")
    assert "A" in doc and "a" in doc
    assert doc.get("MISSING") is None
    with pytest.raises(ValueError):
        doc["B"] = Section("C")
    with pytest.raises(TypeError):
        doc.add("not a section")
    doc.add(Section("A", X="2"))  # replaces
    assert doc["A"]["X"] == "2"
    assert len(doc) == 1
    assert doc == Document([Section("A", X="2")])
    assert doc != Document()


def test_repr():
    assert repr(Section("A", X="1")) == "Section('A', {'X': '1'})"
    assert repr(TextSection("C", "hi")) == "TextSection('C', 'hi')"
    assert repr(Document([Section("A")])) == "Document([Section('A', {})])"


# --------------------------------------------------------------------------
# typed layer
# --------------------------------------------------------------------------


class HeaderSection(Section):
    section_name = "HEADER"
    version = Field("VERSION", int)
    revision = Field("REVISION", int, format="{:03d}".format)
    author = Field("AUTHOR")
    owner = Field("OWNER", default="NOBODY")


class ScheduleSection(Section):
    section_name = "SCHEDULE"
    interval = Field("INTERVAL", int)
    days = Field("DAYS", list[str])
    counts = Field("COUNTS", list[int])


class SampleDocument(Document):
    header = SectionField(HeaderSection)
    schedule = SectionField(ScheduleSection)
    comments = SectionField(TextSection, "COMMENTS", aliases=("COMMENT",))


def test_typed_read():
    doc = SampleDocument.read(SAMPLE)
    assert isinstance(doc["HEADER"], HeaderSection)
    assert doc.header.version == 1
    assert doc.header.revision == 3
    assert doc.header.author == "EXAMPLE"
    assert doc.schedule.interval == 15
    assert doc.schedule.days == ["MON", "TUE", "WED", "THU", "FRI"]
    assert isinstance(doc["CONFIG"], Section)  # unregistered names stay generic


def test_typed_write_and_formatting():
    doc = SampleDocument()
    doc.header.version = 7
    doc.header.revision = 12  # zero padded by the format
    doc.header.author = "EXAMPLE"
    doc.schedule.days = ["MON", "FRI"]
    doc.schedule.counts = [1, 2, 3]
    assert doc.dumps(width=None, newline="\n") == (
        "HEADER   VERSION=7 REVISION=012 AUTHOR=EXAMPLE\n"
        "SCHEDULE DAYS=MON,FRI COUNTS=1,2,3\n"
    )
    assert doc.schedule.counts == [1, 2, 3]


def test_field_default_missing_and_deletion():
    header = HeaderSection()
    assert header.owner == "NOBODY"
    with pytest.raises(AttributeError, match="VERSION"):
        _ = header.version
    assert not hasattr(header, "version")
    header.version = 1
    header.version = None
    assert "VERSION" not in header
    header.owner = "SOMEBODY"
    del header.owner
    assert header.owner == "NOBODY"


def test_scalar_field_keeps_commas():
    assert HeaderSection(fields={"AUTHOR": "A,B"}).author == "A,B"
    assert HeaderSection(fields={"AUTHOR": ["A", "B"]}).author == "A,B"


def test_list_field_splits_and_joins():
    schedule = ScheduleSection()
    schedule["DAYS"] = "ONLY"
    assert schedule.days == ["ONLY"]
    schedule["DAYS"] = ""
    assert schedule.days == []
    schedule["DAYS"] = "A,B"
    assert schedule.days == ["A", "B"]
    schedule.days = ("X", "Y")
    assert schedule["DAYS"] == "X,Y"
    with pytest.raises(AttributeError):
        _ = schedule.counts
    with pytest.raises(TypeError):
        schedule.days = "A,B"
    with pytest.raises(ValueError, match="comma"):
        schedule.days = ["a,b"]


def test_list_field_type_forms_and_item_converters():
    class Items(Section):
        section_name = "ITEMS"
        bare = Field("BARE", list)
        tags = Field("TAGS", list[str], parse=str.lower, format=str.upper)
        padded = Field("PADDED", list[int], format="{:03d}".format, default=())

    items = Items(fields={"BARE": "a,b", "TAGS": "X,Y"})
    assert items.bare == ["a", "b"]
    assert items.tags == ["x", "y"]
    assert items.padded == []
    items.tags = ["p", "q"]
    items.padded = [7, 42]
    assert items.fields["TAGS"] == "P,Q"
    assert items.fields["PADDED"] == "007,042"
    assert items.padded == [7, 42]


def test_typed_constructor_kwargs_go_through_fields():
    header = HeaderSection(version=5, revision=12, OWNER="SOMEBODY")
    assert header.fields == {"VERSION": "5", "REVISION": "012", "OWNER": "SOMEBODY"}


def test_section_field_auto_creates_and_assigns():
    doc = SampleDocument()
    assert "HEADER" not in doc
    header = doc.header
    assert isinstance(header, HeaderSection) and "HEADER" in doc
    assert doc.header is header
    doc.header = {"VERSION": "9"}
    assert doc.header.version == 9
    doc.header = HeaderSection(version=10)
    assert doc.header.version == 10
    with pytest.raises(ValueError):
        doc.header = Section("CONFIG")
    doc.comments = "free text"
    assert doc["COMMENTS"] == TextSection("COMMENTS", "free text")
    doc.header = None
    assert "HEADER" not in doc
    del doc.comments
    assert "COMMENTS" not in doc


def test_generic_section_is_converted_when_added_to_typed_document():
    doc = SampleDocument()
    stored = doc.add(Section("HEADER", VERSION="3"))
    assert isinstance(stored, HeaderSection)
    assert doc.header.version == 3
    doc.sections["HEADER"] = Section("HEADER", VERSION="4")  # bypass add()
    assert doc.header.version == 4
    assert isinstance(doc["HEADER"], HeaderSection)
    with pytest.raises(TypeError):
        doc.add(TextSection("HEADER", "text"))


def test_registry_is_inherited_and_extended():
    class ConfigSection(Section):
        section_name = "CONFIG"
        buffer = Field("BUFFER", int)

    class Extended(SampleDocument):
        config = SectionField(ConfigSection)

    assert set(Extended.section_types) == {"HEADER", "SCHEDULE", "COMMENTS", "CONFIG"}
    assert set(SampleDocument.section_types) == {"HEADER", "SCHEDULE", "COMMENTS"}
    assert Extended.section_aliases == {"COMMENT": "COMMENTS"}
    doc = Extended.read(SAMPLE)
    assert doc.config.buffer == 4096
    assert doc.header.version == 1


def test_section_field_requires_a_name():
    with pytest.raises(TypeError):
        SectionField(Section)
    with pytest.raises(TypeError):
        SectionField(str, "X")


# --------------------------------------------------------------------------
# section aliases
# --------------------------------------------------------------------------


def test_generic_document_has_no_aliases():
    doc = kvsections.loads("COMMENT one\nCOMMENTS two\n")
    assert Document.section_aliases == {}
    assert list(doc) == ["COMMENT", "COMMENTS"]
    assert doc.warnings == []


def test_alias_is_found_under_either_name_and_keeps_its_spelling():
    doc = SampleDocument.loads("HEADER VERSION=1\nCOMMENT some text\n")
    assert list(doc) == ["HEADER", "COMMENTS"]
    assert doc["COMMENTS"] is doc["COMMENT"] is doc.comments
    assert "comment" in doc and "COMMENTS" in doc
    assert doc.comments.name == "COMMENT"  # the spelling the file used
    assert doc.comments.text == "some text"
    assert doc.dumps(width=None, newline="\n") == (
        "HEADER  VERSION=1\nCOMMENT some text\n"
    )
    del doc["COMMENT"]
    assert "COMMENTS" not in doc


def test_both_spellings_in_one_file_are_merged_with_a_warning():
    doc = SampleDocument.loads("COMMENTS first\nCOMMENT second\n")
    assert list(doc) == ["COMMENTS"]
    assert doc.comments.name == "COMMENTS"
    assert doc.comments.text == "first\nsecond"
    assert [str(w) for w in doc.warnings] == [
        "line 2: duplicate section COMMENT (alias of COMMENTS); "
        "merged into the earlier one"
    ]


def test_sections_built_in_code_use_the_canonical_name():
    doc = SampleDocument()
    doc.comments = "built"
    assert doc.comments.name == "COMMENTS"
    # storing or assigning under an alias is accepted and keeps that spelling
    doc["COMMENT"] = TextSection("COMMENT", "stored")
    assert doc.comments.text == "stored" and doc.comments.name == "COMMENT"
    doc.comments = TextSection("COMMENT", "assigned")
    assert doc["COMMENTS"].text == "assigned"
    assert len(doc) == 1
    with pytest.raises(ValueError):
        doc["COMMENTS"] = TextSection("NOTES")
    with pytest.raises(ValueError):
        doc.comments = TextSection("NOTES")


def test_class_level_aliases_are_inherited_and_extended():
    class Base(Document):
        section_aliases = {"cfg": "config"}

    class Derived(Base):
        section_aliases = {"HDR": "HEADER"}
        comments = SectionField(TextSection, "COMMENTS", aliases=("COMMENT",))

    assert Base.section_aliases == {"CFG": "CONFIG"}
    assert Derived.section_aliases == {
        "CFG": "CONFIG",
        "HDR": "HEADER",
        "COMMENT": "COMMENTS",
    }
    doc = Derived.loads("CFG MODE=X\nHDR VERSION=1\n")
    assert list(doc) == ["CONFIG", "HEADER"]
    assert [section.name for section in doc.values()] == ["CFG", "HDR"]
    assert doc["config"]["MODE"] == "X"
    assert doc.section_type_for("cfg") is Section
    assert Derived.section_type_for("comment") is TextSection


def test_conflicting_aliases_are_rejected():
    with pytest.raises(TypeError, match="registered as a section"):

        class AliasOfAnotherSection(Document):
            a = SectionField(Section, "A", aliases=("B",))
            b = SectionField(Section, "B")

    with pytest.raises(TypeError, match="already an alias"):

        class AliasUsedTwice(Document):
            a = SectionField(Section, "A", aliases=("X",))
            b = SectionField(Section, "B", aliases=("X",))

    with pytest.raises(TypeError, match="is an alias itself"):

        class ChainedAlias(Document):
            section_aliases = {"A": "B", "B": "C"}

    with pytest.raises(ValueError):
        SectionField(Section, "A", aliases=("a",))


def test_writer_indent_follows_the_spelling_not_the_canonical_name():
    class Doc(Document):
        x = SectionField(Section, "X", aliases=("LONGALIAS",))

    doc = Doc.loads("LONGALIAS K=1\nY K=2\n")
    assert list(doc) == ["X", "Y"]
    assert doc.dumps(width=None, newline="\n") == "LONGALIAS K=1\nY         K=2\n"


# --------------------------------------------------------------------------
# converters
# --------------------------------------------------------------------------


def test_date_and_time_converters_round_trip():
    class Header(Section):
        section_name = "HEADER"
        created = Field("CREATED", YYYYMMDD)
        short = Field("SHORT", YYMMDD)

    class Schedule(Section):
        section_name = "SCHEDULE"
        start = Field("START", HHMMSS)
        stop = Field("STOP", HHMM)
        dates = Field("DATES", list[YYYYMMDD], default=())

    header = Header(fields={"CREATED": "20240101", "SHORT": "001210"})
    assert header.created == date(2024, 1, 1)
    assert header.short == date(2000, 12, 10)
    header.created = date(2025, 2, 3)
    header.short = date(1999, 12, 31)
    assert header.fields == {"CREATED": "20250203", "SHORT": "991231"}

    schedule = Schedule(fields={"START": "080000", "STOP": "1730"})
    assert schedule.start == time(8, 0, 0)
    assert schedule.stop == time(17, 30)
    assert schedule.dates == []
    schedule.dates = [date(2024, 1, 1), date(2024, 1, 2)]
    assert schedule.fields["DATES"] == "20240101,20240102"
    assert schedule.dates == [date(2024, 1, 1), date(2024, 1, 2)]
    with pytest.raises(ValueError):
        _ = Schedule(fields={"START": "8am"}).start


def test_converters_on_the_sample():
    class Header(Section):
        section_name = "HEADER"
        created = Field("CREATED", YYYYMMDD)
        revision = Field("REVISION", zero_padded(3))

    class Config(Section):
        section_name = "CONFIG"
        enabled = Field("ENABLED", YES_NO)
        mode = Field("MODE", one_of("NORMAL", "FAST"))

    class Schedule(Section):
        section_name = "SCHEDULE"
        start = Field("START", HHMMSS)
        stop = Field("STOP", HHMMSS)

    class Doc(Document):
        header = SectionField(Header)
        config = SectionField(Config)
        schedule = SectionField(Schedule)

    doc = Doc.read(SAMPLE)
    assert doc.header.created == date(2024, 1, 1)
    assert doc.header.revision == 3
    assert doc.config.enabled is True
    assert doc.config.mode == "NORMAL"
    assert (doc.schedule.start, doc.schedule.stop) == (time(8, 0), time(17, 30))
    # reading through converters changes nothing on disk
    assert doc.dumps(indent=12).encode("ascii") == SAMPLE.read_bytes()


def test_zero_padded_flag_choice_and_enum_converters():
    class Mode(Enum):
        NORMAL = "N"
        FAST = "F"

    class Items(Section):
        section_name = "ITEMS"
        size = Field("SIZE", zero_padded(6))
        on = Field("ON", flag("ON", "OFF"))
        level = Field("LEVEL", one_of("LOW", "HIGH"))
        by_value = Field("BYVALUE", enum_by_value(Mode))
        by_name = Field("BYNAME", enum_by_name(Mode))

    items = Items(
        size=1024, on=False, level="LOW", by_value=Mode.FAST, by_name=Mode.FAST
    )
    assert items.fields == {
        "SIZE": "001024",
        "ON": "OFF",
        "LEVEL": "LOW",
        "BYVALUE": "F",
        "BYNAME": "FAST",
    }
    assert items.size == 1024 and items.on is False
    assert items.by_value is Mode.FAST and items.by_name is Mode.FAST
    with pytest.raises(ValueError, match="digits"):
        items.size = 1234567
    with pytest.raises(ValueError, match="expected"):
        items.level = "MEDIUM"
    items["LEVEL"] = "MEDIUM"
    with pytest.raises(ValueError, match="expected"):
        _ = items.level
    items["ON"] = "MAYBE"
    with pytest.raises(ValueError, match="expected ON or OFF"):
        _ = items.on
    items["BYNAME"] = "SLOW"
    with pytest.raises(ValueError, match="expected one of NORMAL, FAST"):
        _ = items.by_name


def test_custom_converter_and_repr():
    upper = Converter(str.upper, str.lower, name="upper")
    assert repr(upper) == "Converter(upper)"
    assert repr(Converter(int, str)) == "Converter(...)"
    assert repr(YYMMDD) == "Converter(YYMMDD)"
    assert repr(zero_padded(3)) == "Converter(zero_padded(3))"

    class S(Section):
        section_name = "S"
        word = Field("WORD", upper)
        words = Field("WORDS", list[upper])

    s = S(fields={"WORD": "abc", "WORDS": "a,b"})
    assert s.word == "ABC" and s.words == ["A", "B"]
    s.word = "XYZ"
    s.words = ["P", "Q"]
    assert s.fields == {"WORD": "xyz", "WORDS": "p,q"}
