"""Data model: sections, free-text sections, and typed field descriptors."""

from __future__ import annotations

from collections.abc import Iterable, Iterator, Mapping, MutableMapping
from typing import (
    Any,
    Callable,
    NamedTuple,
    TypeVar,
    Union,
    get_args,
    get_origin,
)

__all__ = [
    "AnySection",
    "Section",
    "TextSection",
    "Field",
    "Converter",
    "ParseWarning",
    "ParseError",
]

_T = TypeVar("_T")


class ParseWarning(NamedTuple):
    """Something the tolerant reader accepted but that was not well-formed."""

    lineno: int
    message: str

    def __str__(self) -> str:
        return f"line {self.lineno}: {self.message}"


class ParseError(ValueError):
    """Raised instead of recording a :class:`ParseWarning` when reading strictly."""

    def __init__(self, lineno: int, message: str):
        super().__init__(f"line {lineno}: {message}")
        self.lineno = lineno
        self.message = message


def _normalize_key(key: Any) -> str:
    if not isinstance(key, str):
        raise TypeError(f"key must be a str, not {type(key).__name__}")
    return key.upper()


def _normalize_value(value: Any) -> str:
    """Coerce a value to the string a section stores.

    Strings are stored as they are and other scalars via ``str()``. Any other
    iterable is joined with commas, which is how the format writes lists, so
    its items may not contain commas themselves.
    """
    if isinstance(value, str):
        return value
    if isinstance(value, (bytes, bytearray)):
        raise TypeError("values must be str, not bytes")
    if isinstance(value, Iterable):
        items = [item if isinstance(item, str) else str(item) for item in value]
        for item in items:
            if "," in item:
                raise ValueError(f"list item {item!r} contains a comma")
        return ",".join(items)
    return str(value)


class _SectionBase:
    """Common behaviour of the two section kinds: a normalized upper-case name."""

    #: Default name used when a subclass is instantiated without one.
    section_name: str | None = None

    def __init__(self, name: str | None = None):
        if name is None:
            name = self.section_name
        if name is None:
            raise TypeError(
                f"{type(self).__name__} needs a name (or set section_name on the class)"
            )
        self.name = _normalize_key(name)


class Section(_SectionBase, MutableMapping):
    """A named section holding an ordered mapping of ``KEY`` to value.

    Keys are stored upper-case, and lookups are case-insensitive. Values are
    always strings, exactly as they appear in the file; a comma-separated
    list is one string here, and :class:`Field` splits it when declared with
    a ``list[T]`` type. Subclasses may declare :class:`Field` descriptors to
    expose keys as typed attributes and set ``section_name`` so the name can
    be omitted from the constructor.
    """

    def __init__(
        self,
        name: str | None = None,
        fields: Mapping[str, Any] | None = None,
        **kwargs: Any,
    ):
        super().__init__(name)
        self.fields: dict[str, str] = {}
        if fields is not None:
            for key, value in fields.items():
                self[key] = value
        for attr, value in kwargs.items():
            descriptor = getattr(type(self), attr, None)
            if isinstance(descriptor, Field):
                setattr(self, attr, value)
            else:
                self[attr] = value

    # -- MutableMapping ----------------------------------------------------

    def __getitem__(self, key: str) -> str:
        return self.fields[_normalize_key(key)]

    def __setitem__(self, key: str, value: Any) -> None:
        self.fields[_normalize_key(key)] = _normalize_value(value)

    def __delitem__(self, key: str) -> None:
        del self.fields[_normalize_key(key)]

    def __iter__(self) -> Iterator[str]:
        return iter(self.fields)

    def __len__(self) -> int:
        return len(self.fields)

    def __contains__(self, key: object) -> bool:
        return isinstance(key, str) and _normalize_key(key) in self.fields

    # -- misc --------------------------------------------------------------

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, Section):
            return NotImplemented
        return self.name == other.name and self.fields == other.fields

    __hash__ = None  # type: ignore[assignment]

    def __repr__(self) -> str:
        return f"{type(self).__name__}({self.name!r}, {self.fields!r})"


class TextSection(_SectionBase):
    """A named section whose content is free text rather than key/value pairs.

    ``text`` holds the lines joined with ``"\\n"``. The reader produces these
    for the ``COMMENT`` and ``COMMENTS`` sections by default.
    """

    def __init__(self, name: str | None = None, text: str = ""):
        super().__init__(name)
        if not isinstance(text, str):
            raise TypeError(f"text must be a str, not {type(text).__name__}")
        self.text = text

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, TextSection):
            return NotImplemented
        return self.name == other.name and self.text == other.text

    __hash__ = None  # type: ignore[assignment]

    def __repr__(self) -> str:
        return f"{type(self).__name__}({self.name!r}, {self.text!r})"


AnySection = Union[Section, TextSection]


class _Missing:
    def __repr__(self) -> str:
        return "<missing>"


MISSING: Any = _Missing()


class Converter:
    """A ``parse``/``format`` pair that a :class:`Field` accepts as its type.

    ``parse`` turns the stored string into a value and ``format`` turns a
    value back into the string to store. Ready-made converters for common
    encodings live in :mod:`kvsections.converters`.
    """

    __slots__ = ("parse", "format", "name")

    def __init__(
        self,
        parse: Callable[[str], Any],
        format: Callable[[Any], str],
        name: str | None = None,
    ):
        self.parse = parse
        self.format = format
        self.name = name

    def __repr__(self) -> str:
        return f"Converter({self.name})" if self.name else "Converter(...)"


def _converters_for(type_: Any) -> tuple[Any, Any]:
    """The default ``parse`` and ``format`` implied by a field type."""
    if isinstance(type_, Converter):
        return type_.parse, type_.format
    if type_ is None or type_ is str:
        return None, None
    return type_, None


class Field:
    """Descriptor exposing one key of a :class:`Section` as a typed attribute.

    ``parse`` converts the stored string to the attribute's type on read and
    ``format`` converts it back to a string on write. Passing ``type`` is
    shorthand for ``parse=type, format=str``; a :class:`Converter` supplies
    both. Values with leading zeros need an explicit ``format`` to survive a
    round trip, for example ``Field("ORBIT", int, format="{:05d}".format)``
    or ``Field("ORBIT", zero_padded(5))``.

    A ``type`` of ``list[T]`` (or bare ``list``) makes the attribute a list:
    the stored value is split on commas, each item converted with ``T``, and
    joined again on assignment. ``parse`` and ``format`` then apply to each
    item, an empty value is an empty list, and the list returned is a copy,
    so assign a new list rather than mutating it.

    Reading a missing key raises :class:`AttributeError` unless ``default`` is
    given. Assigning ``None`` removes the key.
    """

    def __init__(
        self,
        key: str,
        type: Any = None,
        *,
        parse: Callable[[str], Any] | None = None,
        format: Callable[[Any], str] | None = None,
        default: Any = MISSING,
    ):
        self.key = _normalize_key(key)
        self.is_list = type is list or get_origin(type) is list
        if self.is_list:
            args = get_args(type)
            type = args[0] if args else str
        if self.is_list or type is not None:
            default_parse, default_format = _converters_for(type)
            parse = parse or default_parse
            format = format or default_format or str
        self.parse = parse
        self.format = format
        self.default = default
        self.attr = key

    def __set_name__(self, owner: type, attr: str) -> None:
        self.attr = attr

    def __get__(self, section: Section | None, owner: type | None = None) -> Any:
        if section is None:
            return self
        raw = section.fields.get(self.key)
        if raw is None:
            if self.default is MISSING:
                raise AttributeError(
                    f"{type(section).__name__} {section.name} has no {self.key} value"
                )
            return list(self.default) if self.is_list else self.default
        if self.is_list:
            items = raw.split(",") if raw else []
            if self.parse is not None:
                return [self.parse(item) for item in items]
            return items
        return self.parse(raw) if self.parse is not None else raw

    def __set__(self, section: Section, value: Any) -> None:
        if value is None:
            section.fields.pop(self.key, None)
            return
        if self.is_list:
            if isinstance(value, str):
                raise TypeError(f"{self.key} expects a list, not a str")
            if self.format is not None:
                value = [self.format(item) for item in value]
            section[self.key] = list(value)
        else:
            section[self.key] = self.format(value) if self.format is not None else value

    def __delete__(self, section: Section) -> None:
        del section[self.key]

    def __repr__(self) -> str:
        return f"{type(self).__name__}({self.key!r})"


def convert_section(section: AnySection, target: type[_T]) -> _T:
    """Return ``section`` as an instance of ``target``, copying its content."""
    if isinstance(section, target):
        return section
    if issubclass(target, TextSection):
        if not isinstance(section, TextSection):
            raise TypeError(
                f"section {section.name} holds key/value pairs but "
                f"{target.__name__} is a text section"
            )
        return target(section.name, section.text)
    if issubclass(target, Section):
        if not isinstance(section, Section):
            raise TypeError(
                f"section {section.name} is free text but "
                f"{target.__name__} is a key/value section"
            )
        return target(section.name, section.fields)
    raise TypeError(f"{target.__name__} is not a section class")
