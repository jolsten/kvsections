"""Section, TextSection, Field and Converter behaviour."""

import pytest

import kvsections
from helpers import (
    HeaderSection,
    ScheduleSection,
    names,
)
from kvsections import (
    Converter,
    Document,
    Field,
    Section,
    SectionField,
    TextSection,
)
from kvsections.converters import (
    YYMMDD,
    zero_padded,
)


def test_section_normalizes_keys_and_values():
    section = Section("header", {"owner": "NOBODY"}, version=42, items=("a", 1))
    assert section.section_name == "HEADER"
    assert section.section_fields == {
        "OWNER": "NOBODY",
        "VERSION": "42",
        "ITEMS": "a,1",
    }
    assert section["owner"] == "NOBODY"
    assert "Owner" in section
    del section["OWNER"]
    assert "owner" not in section
    assert list(section) == [("VERSION", "42"), ("ITEMS", "a,1")]
    assert dict(section) == {"VERSION": "42", "ITEMS": "a,1"}
    assert len(section) == 2


def test_section_requires_name_unless_class_provides_one():
    with pytest.raises(TypeError):
        Section()

    class Header(Section):
        section_name = "HEADER"

    assert Header().section_name == "HEADER"
    assert Header("OTHER").section_name == "OTHER"
    assert Header.section_name == "HEADER"  # the class default is untouched


def test_constructor_names_are_positional_only_so_keywords_are_keys():
    section = HeaderSection(name="Bob", fields="x", version=3)
    assert section.section_name == "HEADER"
    assert dict(section) == {"NAME": "Bob", "FIELDS": "x", "VERSION": "3"}
    assert dict(Section("A", fields="x")) == {"FIELDS": "x"}
    with pytest.raises(TypeError):
        TextSection("A", text="x")
    with pytest.raises(TypeError):
        Document(sections=[])


def test_section_accepts_a_mapping_or_pairs_including_another_section():
    original = Section("A", X="1", Y="2")
    assert Section("B", original) == Section("B", {"X": "1", "Y": "2"})
    assert Section("C", [("x", 1), ("y", [2, 3])]) == Section("C", X="1", Y="2,3")
    assert Section("D", dict(original)) == Section("D", X="1", Y="2")


def test_lists_assigned_to_raw_keys_are_joined_with_commas():
    section = Section("A", {"L": ["x", "y"], "ONE": ["z"], "NONE": [], "N": [1, 2]})
    assert section.section_fields == {"L": "x,y", "ONE": "z", "NONE": "", "N": "1,2"}
    assert Document([section]).document_dumps(width=None) == (
        "A L=x,y ONE=z NONE= N=1,2\n"
    )
    with pytest.raises(ValueError, match="comma"):
        section["BAD"] = ["a,b"]


def test_assigning_none_to_a_raw_key_removes_it():
    section = Section("A", X="1", Y=None)
    assert section.section_fields == {"X": "1"}
    section["X"] = None
    section["MISSING"] = None
    assert section.section_fields == {}
    assert Document([section]).document_dumps(width=None) == "A\n"


def test_non_string_keys_are_absent_rather_than_errors():
    doc = kvsections.loads("A X=1")
    section = doc["A"]
    assert 1 not in doc and 1 not in section
    with pytest.raises(KeyError):
        _ = doc[1]
    with pytest.raises(KeyError):
        _ = section[1]
    with pytest.raises(KeyError):
        del doc[1]
    with pytest.raises(TypeError):
        section[1] = "x"


def test_sections_and_documents_are_pair_containers_not_mappings():
    doc = kvsections.loads("A X=1 Y=2\nB Z=3\n")
    section = doc["A"]
    for name in ("items", "keys", "values", "get", "update", "pop", "clear"):
        assert not hasattr(section, name)
        assert not hasattr(doc, name)
    assert list(section) == [("X", "1"), ("Y", "2")]
    assert dict(section) == {"X": "1", "Y": "2"}
    assert list(doc) == [("A", section), ("B", doc["B"])]
    assert dict(doc) == {"A": section, "B": doc["B"]}
    assert names(doc) == ["A", "B"]
    assert len(doc) == 2 and "b" in doc
    del doc["A"]
    assert names(doc) == ["B"]
    assert Document(doc) == doc and Document(dict(doc)) == doc


def test_repr():
    assert repr(Section("A", X="1")) == "Section('A', {'X': '1'})"
    assert repr(TextSection("C", "hi")) == "TextSection('C', 'hi')"
    assert repr(Document([Section("A")])) == "Document([Section('A', {})])"


# --------------------------------------------------------------------------
# missing keys: None by default, a default if given, an error if required
# --------------------------------------------------------------------------


def test_missing_keys_read_as_none_unless_defaulted_or_required():
    header = HeaderSection()
    assert header.author is None  # absent, no default
    assert hasattr(header, "author")
    assert header.owner == "NOBODY"  # absent, default
    with pytest.raises(AttributeError, match=r"HeaderSection\.version \(VERSION\)"):
        _ = header.version  # absent, required
    assert not hasattr(header, "version")
    header.version = 1
    assert header.version == 1
    header.version = None  # None removes, so the key is absent again
    assert "VERSION" not in header
    with pytest.raises(AttributeError):
        _ = header.version
    header.author = "X"
    header.author = None
    assert header.author is None and "AUTHOR" not in header
    header.owner = "SOMEBODY"
    del header.owner
    assert header.owner == "NOBODY"


def test_deleting_a_typed_field_matches_assigning_none():
    header = HeaderSection()
    del header.version  # absent already: a no-op, like header.version = None
    assert "VERSION" not in header
    header.version = 1
    del header.version
    assert "VERSION" not in header


def test_required_fields_cannot_have_a_default():
    with pytest.raises(TypeError, match="required field cannot have a default"):
        Field(int, required=True, default=0)
    assert Field(int, required=True, default=None).required  # None is no default


def test_required_list_field_and_empty_versus_absent():
    class S(Section):
        section_name = "S"
        xs = Field(list[int], required=True)
        ys = Field(list[int])

    with pytest.raises(AttributeError, match="XS"):
        _ = S().xs
    assert S(XS="").xs == []  # present but empty
    assert S(XS="1,2").xs == [1, 2]
    assert S().ys is None  # absent
    assert S(YS="").ys == []


def test_scalar_field_keeps_commas():
    assert HeaderSection(AUTHOR="A,B").author == "A,B"
    assert HeaderSection(AUTHOR=["A", "B"]).author == "A,B"


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
    assert schedule.counts is None
    with pytest.raises(TypeError):
        schedule.days = "A,B"
    with pytest.raises(ValueError, match="comma"):
        schedule.days = ["a,b"]


def test_list_field_type_forms_and_item_converters():
    class Items(Section):
        section_name = "ITEMS"
        bare = Field(list)
        tags = Field(list[str], parse=str.lower, format=str.upper)
        padded = Field(list[int], format="{:03d}".format, default=())

    items = Items(BARE="a,b", TAGS="X,Y")
    assert items.bare == ["a", "b"]
    assert items.tags == ["x", "y"]
    assert items.padded == []
    items.tags = ["p", "q"]
    items.padded = [7, 42]
    assert items.section_fields["TAGS"] == "P,Q"
    assert items.section_fields["PADDED"] == "007,042"
    assert items.padded == [7, 42]


def test_list_field_default_is_copied_on_every_read():
    class S(Section):
        section_name = "S"
        xs = Field(list[int], default=None)
        ys = Field(list[int], default=(1,))

    assert S().xs is None
    assert S().ys == [1]
    first = S().ys
    first.append(2)
    assert S().ys == [1]


def test_typed_constructor_kwargs_go_through_fields():
    header = HeaderSection(version=5, revision=12, OWNER="SOMEBODY")
    assert header.section_fields == {
        "VERSION": "5",
        "REVISION": "012",
        "OWNER": "SOMEBODY",
    }


def test_custom_converter_and_repr():
    upper = Converter(str.upper, str.lower, name="upper")
    assert repr(upper) == "Converter(upper)"
    assert repr(Converter(int, str)) == "Converter(...)"
    assert repr(YYMMDD) == "Converter(YYMMDD)"
    assert repr(zero_padded(3)) == "Converter(zero_padded(3))"

    class S(Section):
        section_name = "S"
        word = Field(upper)
        words = Field(list[upper])

    s = S(WORD="abc", WORDS="a,b")
    assert s.word == "ABC" and s.words == ["A", "B"]
    s.word = "XYZ"
    s.words = ["P", "Q"]
    assert s.section_fields == {"WORD": "xyz", "WORDS": "p,q"}


def test_model_type_errors_and_unrelated_comparisons():
    with pytest.raises(TypeError):
        Section("A", K=b"bytes")
    with pytest.raises(TypeError):
        TextSection("A", 5)
    with pytest.raises(TypeError):
        Section(5)
    assert Section("A") != "A"
    assert TextSection("A") != "A"
    assert Section("A") != TextSection("A")
    assert Document() != {}
    with pytest.raises(KeyError):
        del Section("A", K="1")[1]


def test_field_reprs_and_class_access():
    assert repr(Field(int, key="key")) == "Field('KEY')"
    assert repr(HeaderSection.version) == "Field('VERSION')"
    assert isinstance(HeaderSection.version, Field)  # class access gives the descriptor


def test_bool_shorthand_is_rejected_with_a_hint():
    with pytest.raises(TypeError, match="YES_NO"):
        Field(bool)
    with pytest.raises(TypeError, match="YES_NO"):
        Field(list[bool])


def test_field_key_is_keyword_only_and_a_non_empty_str():
    with pytest.raises(TypeError, match="keyword-only"):
        Field("VERSION")
    with pytest.raises(TypeError):
        Field("VERSION", int)
    with pytest.raises(TypeError, match="key must be a str"):
        Field(key=5)
    with pytest.raises(ValueError, match="empty"):
        Field(key="")


def test_section_get_is_the_lenient_raw_lookup():
    section = Section("A", X="1", EMPTY="")
    assert section.section_get("x") == "1"
    assert section.section_get("EMPTY") == ""
    assert section.section_get("MISSING") is None
    assert section.section_get("MISSING", default="d") == "d"
    assert section.section_get(1) is None
    assert HeaderSection(version=3).section_get("VERSION") == "3"  # raw, not typed


# --------------------------------------------------------------------------
# the attribute names the key
# --------------------------------------------------------------------------


def test_field_key_comes_from_the_attribute():
    class S(Section):
        section_name = "S"
        version = Field(int)
        name = Field()  # nothing on a section is called name any more
        class_ = Field()  # trailing underscore for a keyword
        max_size = Field(int, key="MAX-SIZE")  # explicit key for a non-identifier
        mixed = Field(key="lower")  # explicit keys are upper-cased like any key

    fields = (S.version, S.name, S.class_, S.max_size, S.mixed)
    assert [f.key for f in fields] == ["VERSION", "NAME", "CLASS", "MAX-SIZE", "LOWER"]
    s = S(version=1, name="Bob", class_="X", max_size=9)
    assert dict(s) == {"VERSION": "1", "NAME": "Bob", "CLASS": "X", "MAX-SIZE": "9"}
    assert s.name == "Bob" and s.class_ == "X" and s.max_size == 9
    assert kvsections.dumps(Document([s]), width=None) == (
        "S VERSION=1 NAME=Bob CLASS=X MAX-SIZE=9\n"
    )


def test_mapping_method_names_are_free_for_keys():
    class S(Section):
        section_name = "S"
        items = Field(list[str])
        values = Field()
        update = Field()
        keys = Field()

    s = S(items=["a", "b"], values="v", update="u", keys="k")
    assert s.items == ["a", "b"]
    assert dict(iter(s)) == {"ITEMS": "a,b", "VALUES": "v", "UPDATE": "u", "KEYS": "k"}
    with pytest.raises(TypeError):
        dict(s)  # dict() takes anything with a keys attribute for a mapping


def test_field_declarations_are_checked_when_the_class_is_created():
    with pytest.raises(TypeError, match="starting with 'section_' are reserved"):

        class Reserved(Section):
            section_name = "S"
            section_id = Field()

    with pytest.raises(TypeError, match=r"Dunder\.__init__ would shadow Section"):

        class Dunder(Section):
            section_name = "S"
            __init__ = Field()

    class Plain:
        def total(self):
            return 0

    with pytest.raises(TypeError, match=r"Mixed\.total would shadow Plain\.total"):

        class Mixed(Plain, Section):
            section_name = "S"
            total = Field(int)

    with pytest.raises(TypeError, match="cannot name a key"):

        class Underscore(Section):
            section_name = "S"
            _ = Field()

    with pytest.raises(TypeError, match="holds free text"):

        class Text(TextSection):
            section_name = "T"
            x = Field()

    with pytest.raises(TypeError, match="belongs on a Document"):

        class Wrong(Section):
            section_name = "S"
            x = SectionField(Section)

    with pytest.raises(TypeError, match="belongs on a Document"):

        class WrongText(TextSection):
            section_name = "T"
            x = SectionField(Section)


def test_inherited_fields_may_be_redeclared_and_mixed_in():
    class Base(Section):
        section_name = "B"
        version = Field(int)

    class Derived(Base):
        version = Field(str)

    assert Derived(version=7).version == "7"

    class Stamped:
        created = Field()

    class WithMixin(Section, Stamped):
        section_name = "M"

    assert WithMixin(created="x").created == "x"
    assert WithMixin.created.key == "CREATED"
