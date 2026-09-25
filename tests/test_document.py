"""Document: container protocol, schemas, registry inheritance, aliases, order."""

import pytest

import kvsections
from helpers import (
    GOLDEN,
    CommentDocument,
    HeaderSection,
    SampleDocument,
    ScheduleSection,
    names,
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


def test_document_container_behaviour():
    doc = Document()
    doc["a"] = Section("A", X="1")
    assert "A" in doc and "a" in doc
    assert "MISSING" not in doc
    with pytest.raises(ValueError):
        doc["B"] = Section("C")
    with pytest.raises(TypeError):
        doc.document_add("not a section")
    doc.document_add(Section("A", X="2"))  # replaces
    assert doc["A"]["X"] == "2"
    assert len(doc) == 1
    assert doc == Document([Section("A", X="2")])
    assert doc != Document()
    assert list(doc) == [("A", doc["A"])]


def test_typed_read():
    doc = SampleDocument.document_read(GOLDEN)
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
    assert doc.document_dumps(width=None, newline="\n") == (
        "HEADER   VERSION=7 REVISION=012 AUTHOR=EXAMPLE\n"
        "SCHEDULE DAYS=MON,FRI COUNTS=1,2,3\n"
    )
    assert doc.schedule.counts == [1, 2, 3]


def test_absent_declared_section_reads_as_empty_and_joins_on_first_write():
    doc = SampleDocument()
    header = doc.header
    assert isinstance(header, HeaderSection) and header.section_name == "HEADER"
    assert dict(header) == {}
    assert doc.header is header  # the same section until it joins
    assert "HEADER" not in doc and not doc.document_has("HEADER")
    assert len(doc) == 0 and doc == SampleDocument()  # reading never creates
    assert doc.document_dumps() == ""
    assert header.author is None and header.owner == "NOBODY"
    with pytest.raises(AttributeError, match="VERSION"):
        _ = header.version  # required, and the section is empty
    header.version = 7
    assert "HEADER" in doc and doc["HEADER"] is header and doc.header is header
    assert doc.header.version == 7
    assert doc.document_dumps(width=None) == "HEADER VERSION=7\n"


def test_writes_that_leave_a_section_empty_do_not_create_it():
    doc = SampleDocument()
    doc.header.author = None
    del doc.header.owner
    doc.header["X"] = None
    assert "HEADER" not in doc
    doc.header["X"] = ""  # an empty value is a value
    assert "HEADER" in doc and doc["HEADER"]["X"] == ""


def test_absent_text_section_reads_as_empty_and_joins_on_first_write():
    doc = SampleDocument()
    assert doc.comments.section_text == ""
    assert "COMMENTS" not in doc
    doc.comments.section_text = "free"
    assert doc["COMMENTS"] == TextSection("COMMENTS", "free")
    doc.comments.section_text += " text"
    assert doc.comments.section_text == "free text"
    doc = SampleDocument()
    doc.comments.section_text = ""  # empty text is still text
    assert doc["COMMENTS"] == TextSection("COMMENTS", "")


def test_sections_join_in_the_order_they_are_written():
    doc = SampleDocument()
    header = doc.header  # handed out first, written second
    doc.schedule.interval = 15
    header.version = 1
    assert names(doc) == ["SCHEDULE", "HEADER"]
    assert doc.document_dumps(width=None) == (
        "SCHEDULE INTERVAL=15\nHEADER   VERSION=1\n"
    )


def test_a_section_handed_out_earlier_is_stale_once_another_replaces_it():
    doc = SampleDocument()
    stale = doc.header
    doc.header = HeaderSection(version=1)
    assert doc.header is not stale
    stale.revision = 2  # goes nowhere
    assert dict(doc.header) == {"VERSION": "1"}
    stale = doc.header
    doc.document_add(HeaderSection(version=3))
    stale.revision = 4
    assert dict(doc.header) == {"VERSION": "3"}
    stale = doc.header
    doc.header = None  # removed, so the stored one is stale too
    stale.revision = 5
    assert "HEADER" not in doc
    stale = doc.header  # empty again, and assigning None forgets it as well
    doc.header = None
    stale.version = 6
    assert "HEADER" not in doc and doc.header is not stale


def test_section_field_assignment():
    doc = SampleDocument()
    header = HeaderSection(version=9)
    doc.header = header
    assert doc.header is header and "HEADER" in doc
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
    stored = doc.document_add(Section("HEADER", VERSION="3"))
    assert isinstance(stored, HeaderSection)
    assert doc.header.version == 3
    doc.document_sections["HEADER"] = Section("HEADER", VERSION="4")  # bypass add
    assert doc.header.version == 4
    assert isinstance(doc["HEADER"], HeaderSection)
    with pytest.raises(TypeError):
        doc.document_add(TextSection("HEADER", "text"))


def test_registry_is_inherited_and_extended():
    class ConfigSection(Section):
        section_name = "CONFIG"
        buffer = Field(int)

    class Extended(SampleDocument):
        config = SectionField(ConfigSection)

    assert set(Extended.document_section_types) == {
        "HEADER",
        "SCHEDULE",
        "COMMENTS",
        "CONFIG",
    }
    assert set(SampleDocument.document_section_types) == {
        "HEADER",
        "SCHEDULE",
        "COMMENTS",
    }
    assert Extended.document_aliases == {"COMMENT": "COMMENTS"}
    doc = Extended.document_read(GOLDEN)
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

    assert set(Both.document_section_types) == {"HEADER", "SCHEDULE"}
    assert Both.document_aliases == {"SCHED": "SCHEDULE"}
    assert set(WithMixin.document_section_types) == {"HEADER"}
    doc = Both.document_loads("HEADER VERSION=1\nSCHED INTERVAL=5\n")
    assert doc.header.version == 1
    assert doc.schedule.interval == 5


def test_section_field_rejects_non_section_classes():
    with pytest.raises(TypeError):
        SectionField(str)
    with pytest.raises(TypeError):
        SectionField(str, name="X")


def test_section_field_name_comes_from_the_attribute_or_the_class():
    class Notes(TextSection):
        section_name = "NOTES"

    class Doc(Document):
        header = SectionField(HeaderSection)  # the class says HEADER
        notes = SectionField(Notes)
        comments = SectionField(TextSection)  # from the attribute
        class_ = SectionField(Section)  # trailing underscore for a keyword
        my_notes = SectionField(TextSection, name="MY-NOTES")  # a non-identifier
        items = SectionField(Section)  # a former mapping method name

    assert Doc.document_section_types == {
        "HEADER": HeaderSection,
        "NOTES": Notes,
        "COMMENTS": TextSection,
        "CLASS": Section,
        "MY-NOTES": TextSection,
        "ITEMS": Section,
    }
    doc = Doc.document_loads("CLASS A=1\nMY-NOTES text\nITEMS B=2\n")
    assert doc.class_["A"] == "1"
    assert doc.my_notes.section_text == "text"
    assert doc.items["B"] == "2"
    assert repr(Doc.my_notes) == "SectionField(TextSection, 'MY-NOTES')"


def test_section_field_declarations_are_checked_when_the_class_is_created():
    with pytest.raises(TypeError, match="named HEADER; name the attribute"):

        class Renamed(Document):
            hdr = SectionField(HeaderSection)

    with pytest.raises(TypeError, match="named HEADER, not HDR"):
        SectionField(HeaderSection, name="HDR")

    class Explicit(Document):
        hdr = SectionField(HeaderSection, name="HEADER")  # explicit, so allowed

    assert Explicit.document_section_types == {"HEADER": HeaderSection}

    with pytest.raises(TypeError, match="starting with 'document_' are reserved"):

        class Reserved(Document):
            document_x = SectionField(Section)

    with pytest.raises(TypeError, match="cannot name a section"):

        class Underscore(Document):
            _ = SectionField(Section)

    with pytest.raises(TypeError, match="declares a key of a Section"):

        class WithField(Document):
            x = Field()

    class Plain:
        def total(self):
            return 0

    with pytest.raises(TypeError, match=r"Mixed\.total would shadow Plain\.total"):

        class Mixed(Plain, Document):
            total = SectionField(Section)

    class Mixin:
        header = SectionField(HeaderSection)  # harmless until mixed in

    with pytest.raises(TypeError, match="never registered"):

        class WithMixin(Document, Mixin):
            pass


def test_generic_document_has_no_aliases():
    doc = kvsections.loads("COMMENT X=1\nCOMMENTS Y=2\n")
    assert isinstance(doc["COMMENT"], Section)  # no free text by default
    assert Document.document_aliases == {}
    assert names(doc) == ["COMMENT", "COMMENTS"]
    assert doc.document_warnings == []


def test_alias_is_found_under_either_name_and_keeps_its_spelling():
    doc = SampleDocument.document_loads("HEADER VERSION=1\nCOMMENT some text\n")
    assert names(doc) == ["HEADER", "COMMENTS"]
    assert doc["COMMENTS"] is doc["COMMENT"] is doc.comments
    assert "comment" in doc and "COMMENTS" in doc
    assert doc.comments.section_name == "COMMENT"  # the spelling the file used
    assert doc.comments.section_text == "some text"
    assert doc.document_dumps(width=None, newline="\n") == (
        "HEADER  VERSION=1\nCOMMENT some text\n"
    )
    del doc["COMMENT"]
    assert "COMMENTS" not in doc


def test_both_spellings_in_one_file_are_merged_with_a_warning():
    doc = SampleDocument.document_loads("COMMENTS first\nCOMMENT second\n")
    assert names(doc) == ["COMMENTS"]
    assert doc.comments.section_name == "COMMENTS"
    assert doc.comments.section_text == "first\nsecond"
    assert [str(w) for w in doc.document_warnings] == [
        "line 2: duplicate section COMMENT (alias of COMMENTS); "
        "merged into the earlier one"
    ]


def test_sections_built_in_code_use_the_canonical_name():
    doc = SampleDocument()
    doc.comments = "built"
    assert doc.comments.section_name == "COMMENTS"
    # storing or assigning under an alias is accepted and keeps that spelling
    doc["COMMENT"] = TextSection("COMMENT", "stored")
    assert doc.comments.section_text == "stored"
    assert doc.comments.section_name == "COMMENT"
    doc.comments = TextSection("COMMENT", "assigned")
    assert doc["COMMENTS"].section_text == "assigned"
    assert len(doc) == 1
    with pytest.raises(ValueError):
        doc["COMMENTS"] = TextSection("NOTES")
    with pytest.raises(ValueError):
        doc.comments = TextSection("NOTES")


def test_class_level_aliases_are_inherited_and_extended():
    class Base(Document):
        document_aliases = {"cfg": "config"}

    class Derived(Base):
        document_aliases = {"HDR": "HEADER"}
        comments = SectionField(TextSection, aliases=("COMMENT",))

    assert Base.document_aliases == {"CFG": "CONFIG"}
    assert Derived.document_aliases == {
        "CFG": "CONFIG",
        "HDR": "HEADER",
        "COMMENT": "COMMENTS",
    }
    doc = Derived.document_loads("CFG MODE=X\nHDR VERSION=1\n")
    assert names(doc) == ["CONFIG", "HEADER"]
    assert [section.section_name for _, section in doc] == ["CFG", "HDR"]
    assert doc["config"]["MODE"] == "X"
    assert doc.document_section_type("cfg") is Section
    assert Derived.document_section_type("comment") is TextSection


def test_conflicting_aliases_are_rejected():
    with pytest.raises(TypeError, match="registered as a section"):

        class AliasOfAnotherSection(Document):
            a = SectionField(Section, aliases=("B",))
            b = SectionField(Section)

    with pytest.raises(TypeError, match="already an alias"):

        class AliasUsedTwice(Document):
            a = SectionField(Section, aliases=("X",))
            b = SectionField(Section, aliases=("X",))

    with pytest.raises(TypeError, match="is an alias itself"):

        class ChainedAlias(Document):
            document_aliases = {"A": "B", "B": "C"}

    with pytest.raises(ValueError, match="alias of itself"):
        SectionField(Section, name="A", aliases=("a",))

    with pytest.raises(ValueError, match="alias of itself"):

        class SelfAlias(Document):
            a = SectionField(Section, aliases=("A",))


def test_reorder_with_head_else_and_tail():
    doc = CommentDocument.document_read(GOLDEN)
    sections = doc.document_sections  # reordering happens in place
    doc.document_reorder(["OUTPUT", "header", "MISSING", ..., "SOURCE", "COMMENTS"])
    assert doc.document_sections is sections
    assert names(doc) == [
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
    out = doc.document_dumps(width=None, newline="\n")
    assert out.startswith("OUTPUT     TYPE=REPORT")
    assert CommentDocument.document_loads(doc.document_dumps()) == doc


def test_reorder_without_else_puts_the_rest_after_the_named():
    doc = kvsections.loads("A X=1\nB X=1\nC X=1\nD X=1\n")
    doc.document_reorder(["C", "A"])
    assert names(doc) == ["C", "A", "B", "D"]
    doc.document_reorder([..., "A"])
    assert names(doc) == ["C", "B", "D", "A"]
    doc.document_reorder([])
    assert names(doc) == ["C", "B", "D", "A"]
    doc.document_reorder([...])
    assert names(doc) == ["C", "B", "D", "A"]


def test_reorder_resolves_aliases_and_uses_the_schema_order():
    class Doc(Document):
        document_order = ["HEADER", ..., "COMMENTS"]
        comments = SectionField(TextSection, aliases=("COMMENT",))

    class Derived(Doc):
        pass

    doc = Derived.document_loads("COMMENT text\nCONFIG X=1\nHEADER X=1\n")
    doc.document_reorder()
    assert names(doc) == ["HEADER", "CONFIG", "COMMENTS"]
    doc.document_reorder(["comment", ...])
    assert names(doc) == ["COMMENTS", "HEADER", "CONFIG"]


def test_reorder_rejects_bad_specifications():
    doc = kvsections.loads("A X=1\nB X=1\n")
    with pytest.raises(ValueError, match="more than once"):
        doc.document_reorder(["A", "a"])
    with pytest.raises(ValueError, match="only once"):
        doc.document_reorder([..., "A", ...])
    with pytest.raises(TypeError):
        doc.document_reorder(["A", None])
    assert names(doc) == ["A", "B"]  # untouched after a rejected order


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

    stored = Doc().document_add(TextSection("NOTES", "hello"))
    assert isinstance(stored, Notes) and stored.section_text == "hello"
    with pytest.raises(TypeError):
        convert_section(TextSection("NOTES"), int)
    with pytest.raises(TypeError, match="text section"):
        Doc().document_add(Section("NOTES", X="1"))


def test_any_section_is_a_base_section():
    assert isinstance(Section("A"), BaseSection)
    assert isinstance(TextSection("A"), BaseSection)
    assert not isinstance("A", BaseSection)
    with pytest.raises(TypeError):
        SectionField(str, name="A")


def test_documents_build_from_other_documents_and_mappings():
    class Schema(Document):
        comments = SectionField(TextSection, aliases=("COMMENT",))

    typed = Schema.document_loads("HEADER X=1\nCOMMENT text\n")
    plain = Document(typed)
    assert names(plain) == ["HEADER", "COMMENT"]  # stored under their own names
    assert plain["COMMENT"].section_text == "text"
    assert Document(dict(typed)) == plain
    assert Document(list(dict(typed).values())) == plain
    with pytest.raises(TypeError):
        Document([("A", Section("A"))])  # pairs are not sections


def test_section_field_assignment_type_errors_name_the_attribute():
    doc = SampleDocument()
    with pytest.raises(TypeError, match="header expects a HeaderSection, not str"):
        doc.header = "not a section"
    with pytest.raises(TypeError, match="header expects a HeaderSection, not dict"):
        doc.header = {}  # a mapping would store values raw, past the converters
    with pytest.raises(TypeError, match="comments expects a str or TextSection"):
        doc.comments = {"X": "1"}


def test_module_level_functions_are_the_generic_document_methods():
    assert kvsections.loads("A X=1") == Document.document_loads("A X=1")
    assert type(kvsections.loads("A X=1")) is Document
    doc = Document([Section("A", X="1")])
    assert kvsections.dumps(doc, width=None) == doc.document_dumps(width=None)


def test_document_get_reaches_sections_and_keys_leniently():
    doc = SampleDocument.document_loads("HEADER VERSION=1\nCOMMENT text\n")
    assert doc.document_get("header") is doc.header
    assert doc.document_get("COMMENT") is doc.comments  # aliases resolve
    assert doc.document_get("MISSING") is None
    assert doc.document_get("MISSING", default="d") == "d"
    assert doc.document_get("header", "version") == "1"  # the raw string
    assert doc.document_get("HEADER", "MISSING") is None
    assert doc.document_get("MISSING", "VERSION", default="d") == "d"
    assert doc.document_get("comments", "X") is None  # free text has no keys
    assert doc.document_get(1) is None
    assert doc.document_get("HEADER", 1) is None
    assert doc["HEADER"]["VERSION"] == "1"  # the subscript stays strict
    with pytest.raises(KeyError):
        _ = doc["HEADER"]["MISSING"]


def test_document_has_is_the_two_level_presence_test():
    doc = SampleDocument.document_loads("HEADER VERSION=1 EMPTY=\nCOMMENT text\n")
    assert doc.document_has("header")
    assert doc.document_has("COMMENT")  # aliases resolve
    assert not doc.document_has("MISSING")
    assert doc.document_has("header", "version")
    assert doc.document_has("HEADER", "EMPTY")  # present but empty counts
    assert not doc.document_has("HEADER", "MISSING")
    assert not doc.document_has("MISSING", "VERSION")
    assert not doc.document_has("comments", "X")  # free text has no keys
    assert not doc.document_has(1)
    assert not doc.document_has("HEADER", 1)
    # the raw family ignores field defaults: OWNER defaults to NOBODY
    assert doc.header.owner == "NOBODY"
    assert not doc.document_has("HEADER", "OWNER")
    assert doc.document_get("HEADER", "OWNER") is None


def test_section_init_creates_an_empty_declared_section_in_place():
    doc = SampleDocument()
    header = doc.header
    header.section_init()  # empty, but present now
    assert "HEADER" in doc and doc.header is header and dict(header) == {}
    assert doc.document_dumps(width=None) == "HEADER\n"
    doc.schedule.interval = 15
    header.version = 1
    doc.header.section_init()  # emptied in place: same object, same position
    assert doc.header is header and dict(header) == {}
    assert names(doc) == ["HEADER", "SCHEDULE"]
    doc.comments.section_init()
    assert doc["COMMENTS"] == TextSection("COMMENTS", "")
    stale = doc.header
    doc.header = None
    stale.section_init()  # stale, so it no longer reaches the document
    assert "HEADER" not in doc
