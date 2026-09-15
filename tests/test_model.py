"""Section, TextSection, Field and Converter behaviour."""

import pytest

import kvsections
from helpers import (
    HeaderSection,
    SampleDocument,
    ScheduleSection,
)
from kvsections import (
    Converter,
    Document,
    Field,
    Section,
    TextSection,
)
from kvsections.converters import (
    YYMMDD,
    zero_padded,
)
from kvsections.fields import MISSING


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


def test_lists_assigned_to_raw_keys_are_joined_with_commas():
    section = Section("A", {"L": ["x", "y"], "ONE": ["z"], "NONE": [], "N": [1, 2]})
    assert section.fields == {"L": "x,y", "ONE": "z", "NONE": "", "N": "1,2"}
    assert Document([section]).dumps(width=None) == "A L=x,y ONE=z NONE= N=1,2\n"
    with pytest.raises(ValueError, match="comma"):
        section["BAD"] = ["a,b"]


def test_assigning_none_to_a_raw_key_removes_it():
    section = Section("A", X="1", Y=None)
    assert section.fields == {"X": "1"}
    section["X"] = None
    section["MISSING"] = None
    assert section.fields == {}
    assert Document([section]).dumps(width=None) == "A\n"


def test_non_string_keys_are_absent_rather_than_errors():
    doc = kvsections.loads("A X=1")
    section = doc["A"]
    assert 1 not in doc and 1 not in section
    assert doc.get(1) is None and section.get(1) is None
    with pytest.raises(KeyError):
        _ = doc[1]
    with pytest.raises(KeyError):
        _ = section[1]
    with pytest.raises(KeyError):
        del doc[1]
    with pytest.raises(TypeError):
        section[1] = "x"


def test_setdefault_returns_the_stored_object():
    doc = SampleDocument()
    stored = doc.setdefault("HEADER", Section("HEADER", VERSION="1"))
    assert isinstance(stored, HeaderSection) and stored is doc["HEADER"]
    assert doc.setdefault("HEADER", Section("HEADER", VERSION="2")) is stored
    assert stored.version == 1
    section = Section("A")
    assert section.setdefault("K", [1, 2]) == "1,2"
    assert section.setdefault("K", "other") == "1,2"
    assert section.setdefault("MISSING") is None
    assert "MISSING" not in section


def test_mapping_helpers_on_documents_and_sections():
    doc = kvsections.loads("A X=1 Y=2\nB Z=3\n")
    section = doc["A"]
    assert section.pop("X") == "1"
    assert section.pop("X", "gone") == "gone"
    section.update({"w": "4"}, v=5)
    assert section.fields == {"Y": "2", "W": "4", "V": "5"}
    assert section.popitem() == ("Y", "2")
    section.clear()
    assert len(section) == 0

    assert doc.pop("B") == Section("B", Z="3")
    assert doc.pop("B", None) is None
    doc.update({"C": Section("C")})
    doc.update([("D", Section("D"))])
    assert list(doc) == ["A", "C", "D"]
    assert doc.popitem()[0] == "A"
    doc.clear()
    assert len(doc) == 0


def test_repr():
    assert repr(Section("A", X="1")) == "Section('A', {'X': '1'})"
    assert repr(TextSection("C", "hi")) == "TextSection('C', 'hi')"
    assert repr(Document([Section("A")])) == "Document([Section('A', {})])"


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


def test_list_field_default_none_is_returned_as_is():
    class S(Section):
        section_name = "S"
        xs = Field("XS", list[int], default=None)
        ys = Field("YS", list[int], default=(1,))

    assert S().xs is None
    assert S().ys == [1]


def test_typed_constructor_kwargs_go_through_fields():
    header = HeaderSection(version=5, revision=12, OWNER="SOMEBODY")
    assert header.fields == {"VERSION": "5", "REVISION": "012", "OWNER": "SOMEBODY"}


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


def test_field_and_missing_reprs():
    assert repr(Field("key", int)) == "Field('KEY')"
    assert repr(MISSING) == "<missing>"
    assert isinstance(HeaderSection.version, Field)  # class access gives the descriptor


def test_deleting_a_missing_typed_field_is_an_attribute_error():
    header = HeaderSection()
    with pytest.raises(AttributeError, match=r"HeaderSection\.version \(VERSION\)"):
        del header.version
    with pytest.raises(AttributeError, match=r"HeaderSection\.version"):
        _ = header.version
    header.version = 1
    del header.version
    assert "VERSION" not in header


def test_bool_shorthand_is_rejected_with_a_hint():
    with pytest.raises(TypeError, match="YES_NO"):
        Field("ENABLED", bool)
    with pytest.raises(TypeError, match="YES_NO"):
        Field("FLAGS", list[bool])


def test_field_key_must_be_a_str():
    with pytest.raises(TypeError, match="key must be a str"):
        Field(5)
