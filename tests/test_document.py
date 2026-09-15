"""Document: mapping protocol, schemas, registry inheritance, aliases, order."""

import pytest

import kvsections
from helpers import (
    GOLDEN,
    CommentDocument,
    HeaderSection,
    SampleDocument,
    ScheduleSection,
)
from kvsections import (
    BaseSection,
    Document,
    Field,
    Section,
    SectionField,
    TextSection,
)
from kvsections.model import convert_section


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


def test_typed_read():
    doc = SampleDocument.read(GOLDEN)
    assert isinstance(doc["HEADER"], HeaderSection)
    assert doc.header.version == 1
    assert doc.header.revision == 3
    assert doc.header.author == "EXAMPLE"
    assert doc.schedule.interval == 15
    assert doc.schedule.days == ["MON", "TUE", "WED", "THU", "FRI"]
    assert isinstance(doc["CONFIG"], Section)  # unregistered names stay generic


def test_typed_write_and_formatting():
    doc = SampleDocument()
    doc.header = {}
    doc.schedule = {}
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


def test_section_field_requires_explicit_creation():
    doc = SampleDocument()
    assert "HEADER" not in doc
    with pytest.raises(AttributeError, match="SampleDocument.header"):
        _ = doc.header
    assert "HEADER" not in doc  # reading never creates
    doc.header = {}
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
    doc = Extended.read(GOLDEN)
    assert doc.config.buffer == 4096
    assert doc.header.version == 1


def test_registrations_merge_across_multiple_inheritance():
    class Left(Document):
        header = SectionField(HeaderSection)

    class Right(Document):
        schedule = SectionField(ScheduleSection, aliases=("SCHED",))

    class Mixin:
        pass

    class Both(Left, Right):
        pass

    class WithMixin(Mixin, Left):
        pass

    assert set(Both.section_types) == {"HEADER", "SCHEDULE"}
    assert Both.section_aliases == {"SCHED": "SCHEDULE"}
    assert set(WithMixin.section_types) == {"HEADER"}
    doc = Both.loads("HEADER VERSION=1\nSCHED INTERVAL=5\n")
    assert doc.header.version == 1
    assert doc.schedule.interval == 5


def test_section_field_requires_a_name():
    with pytest.raises(TypeError):
        SectionField(Section)
    with pytest.raises(TypeError):
        SectionField(str, "X")


def test_generic_document_has_no_aliases():
    doc = kvsections.loads("COMMENT X=1\nCOMMENTS Y=2\n")
    assert isinstance(doc["COMMENT"], Section)  # no free text by default
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


def test_reorder_with_head_else_and_tail():
    doc = CommentDocument.read(GOLDEN)
    sections = doc.sections  # reordering happens in place
    doc.reorder(["OUTPUT", "header", "MISSING", ..., "SOURCE", "COMMENTS"])
    assert doc.sections is sections
    assert list(doc) == [
        "OUTPUT",
        "HEADER",
        "CONFIG",
        "TARGET",
        "OPTIONS",
        "FILTER",
        "SCHEDULE",
        "PARAMETERS",
        "SOURCE",
        "COMMENTS",
    ]
    assert doc.dumps(width=None, newline="\n").startswith("OUTPUT     TYPE=REPORT")
    assert CommentDocument.loads(doc.dumps()) == doc


def test_reorder_without_else_puts_the_rest_after_the_named():
    doc = kvsections.loads("A X=1\nB X=1\nC X=1\nD X=1\n")
    doc.reorder(["C", "A"])
    assert list(doc) == ["C", "A", "B", "D"]
    doc.reorder([..., "A"])
    assert list(doc) == ["C", "B", "D", "A"]
    doc.reorder([])
    assert list(doc) == ["C", "B", "D", "A"]
    doc.reorder([...])
    assert list(doc) == ["C", "B", "D", "A"]


def test_reorder_resolves_aliases_and_uses_the_schema_order():
    class Doc(Document):
        section_order = ["HEADER", ..., "COMMENTS"]
        comments = SectionField(TextSection, "COMMENTS", aliases=("COMMENT",))

    class Derived(Doc):
        pass

    doc = Derived.loads("COMMENT text\nCONFIG X=1\nHEADER X=1\n")
    doc.reorder()
    assert list(doc) == ["HEADER", "CONFIG", "COMMENTS"]
    doc.reorder(["comment", ...])
    assert list(doc) == ["COMMENTS", "HEADER", "CONFIG"]


def test_reorder_rejects_bad_specifications():
    doc = kvsections.loads("A X=1\nB X=1\n")
    with pytest.raises(ValueError, match="more than once"):
        doc.reorder(["A", "a"])
    with pytest.raises(ValueError, match="only once"):
        doc.reorder([..., "A", ...])
    with pytest.raises(TypeError):
        doc.reorder(["A", None])
    assert list(doc) == ["A", "B"]  # untouched after a rejected order


def test_section_field_repr_and_class_access():
    assert isinstance(SampleDocument.header, SectionField)
    assert repr(SampleDocument.header) == "SectionField(HeaderSection, 'HEADER')"
    assert repr(SampleDocument.comments) == (
        "SectionField(TextSection, 'COMMENTS', aliases=('COMMENT',))"
    )


def test_document_rejects_non_sections_and_converts_text_sections():
    with pytest.raises(TypeError):
        Document()["A"] = "not a section"

    class Notes(TextSection):
        section_name = "NOTES"

    class Doc(Document):
        notes = SectionField(Notes)

    stored = Doc().add(TextSection("NOTES", "hello"))
    assert isinstance(stored, Notes) and stored.text == "hello"
    with pytest.raises(TypeError):
        convert_section(TextSection("NOTES"), int)
    with pytest.raises(TypeError, match="text section"):
        Doc().add(Section("NOTES", X="1"))


def test_any_section_is_a_base_section():
    assert isinstance(Section("A"), BaseSection)
    assert isinstance(TextSection("A"), BaseSection)
    assert not isinstance("A", BaseSection)
    with pytest.raises(TypeError):
        SectionField(str, "A")


def test_documents_build_from_and_update_from_other_documents():
    class Schema(Document):
        comments = SectionField(TextSection, "COMMENTS", aliases=("COMMENT",))

    typed = Schema.loads("HEADER X=1\nCOMMENT text\n")
    plain = Document(typed)  # a mapping of sections
    assert list(plain) == ["HEADER", "COMMENT"]  # stored under their own names
    assert plain["COMMENT"].text == "text"
    other = Document([Section("A", Y="2")])
    other.update(typed)
    assert list(other) == ["A", "HEADER", "COMMENT"]
    other.update([("B", Section("B"))], C=Section("C"))
    assert list(other) == ["A", "HEADER", "COMMENT", "B", "C"]


def test_section_field_assignment_type_errors_name_the_attribute():
    doc = SampleDocument()
    with pytest.raises(TypeError, match="header expects a mapping"):
        doc.header = "not a mapping"
    with pytest.raises(TypeError, match="comments expects a str"):
        doc.comments = {"X": "1"}


def test_module_level_functions_are_the_generic_document_methods():
    assert kvsections.loads("A X=1") == Document.loads("A X=1")
    assert type(kvsections.loads("A X=1")) is Document
    doc = Document([Section("A", X="1")])
    assert kvsections.dumps(doc, width=None) == doc.dumps(width=None)
