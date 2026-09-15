"""Sections: the key/value and free-text containers a document is made of."""

from __future__ import annotations

from collections.abc import Iterable, Iterator, Mapping, MutableMapping
from typing import Any, TypeVar

from .fields import Field

__all__ = ["BaseSection", "Section", "TextSection", "convert_section"]

_S = TypeVar("_S", bound="BaseSection")


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


class BaseSection:
    """What the two section kinds share: a normalized upper-case name.

    ``isinstance(x, BaseSection)`` is the test for "any kind of section".
    """

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


class Section(BaseSection, MutableMapping[str, str]):
    """A named section holding an ordered mapping of ``KEY`` to value.

    Keys are stored upper-case, and lookups are case-insensitive. Values are
    always strings, exactly as they appear in the file; a comma-separated
    list is one string here, and :class:`Field` splits it when declared with
    a ``list[T]`` type. Assigning ``None`` to a key removes it. Subclasses
    may declare :class:`Field` descriptors to expose keys as typed attributes
    and set ``section_name`` so the name can be omitted from the constructor.
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
        if not isinstance(key, str):
            raise KeyError(key)
        return self.fields[_normalize_key(key)]

    def __setitem__(self, key: str, value: Any) -> None:
        """Store ``value`` under ``key``; ``None`` removes the key instead."""
        key = _normalize_key(key)
        if value is None:
            self.fields.pop(key, None)
        else:
            self.fields[key] = _normalize_value(value)

    def __delitem__(self, key: str) -> None:
        if not isinstance(key, str):
            raise KeyError(key)
        del self.fields[_normalize_key(key)]

    def __iter__(self) -> Iterator[str]:
        return iter(self.fields)

    def __len__(self) -> int:
        return len(self.fields)

    def __contains__(self, key: object) -> bool:
        return isinstance(key, str) and _normalize_key(key) in self.fields

    def setdefault(self, key: str, default: Any = None) -> Any:
        """Return the value of ``key``, storing ``default`` first if absent.

        The stored string is returned, so a list default comes back joined.
        A ``None`` default stores nothing and returns ``None``.
        """
        if key in self:
            return self[key]
        if default is None:
            return None
        self[key] = default
        return self[key]

    # -- misc --------------------------------------------------------------

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, Section):
            return NotImplemented
        return self.name == other.name and self.fields == other.fields

    __hash__ = None  # type: ignore[assignment]

    def __repr__(self) -> str:
        return f"{type(self).__name__}({self.name!r}, {self.fields!r})"


class TextSection(BaseSection):
    """A named section whose content is free text rather than key/value pairs.

    ``text`` holds the lines joined with ``"\\n"``. The reader produces these
    for the sections a schema registers as text.

    Text starts at its first non-blank character: leading whitespace on the
    first line, blank lines at either end and trailing spaces cannot be told
    apart from layout, so a round trip through a file drops them.
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


def convert_section(section: BaseSection, target: type[_S]) -> _S:
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
