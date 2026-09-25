"""Sections: the key/value and free-text containers a document is made of."""

from __future__ import annotations

from collections.abc import Callable, Iterable, Iterator, Mapping
from typing import Any, TypeVar, cast, overload

from .fields import Declaration, Field

__all__ = ["BaseSection", "Section", "TextSection", "convert_section"]

_S = TypeVar("_S", bound="BaseSection")
_T = TypeVar("_T")


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
        iterable = cast("Iterable[object]", value)
        items = [item if isinstance(item, str) else str(item) for item in iterable]
        for item in items:
            if "," in item:
                raise ValueError(f"list item {item!r} contains a comma")
        return ",".join(items)
    return str(value)


class BaseSection:
    """What the two section kinds share: a normalized upper-case name.

    Everything the library puts on a section is named ``section_...``, so
    that on a :class:`Section` subclass every other attribute can be a key.
    ``isinstance(x, BaseSection)`` is the test for "any kind of section".
    ``section_init`` starts a section over, empty, in place.
    """

    #: The section's name, upper-case. A subclass may set it as a class
    #: attribute to supply the default when instantiated without a name.
    section_name: str

    #: Set by ``SectionField`` on the empty section it hands out for a name
    #: the document lacks: called with the section on its first write, so
    #: that the section joins the document then and not before.
    _section_join: Callable[[BaseSection], object] | None = None

    def __init__(self, name: str | None = None, /):
        if name is None:
            name = getattr(type(self), "section_name", None)
        if name is None:
            raise TypeError(
                f"{type(self).__name__} needs a name (or set section_name on the class)"
            )
        self.section_name = _normalize_key(name)

    def _section_written(self) -> None:
        """Run the pending join, if any; every write of content calls this."""
        join = self._section_join
        if join is not None:
            self._section_join = None
            join(self)

    def section_init(self) -> None:
        """Start the section over, as the constructor with no arguments would.

        The content is dropped: every pair of a :class:`Section`, the text
        of a :class:`TextSection`. A section a document handed out but does
        not hold yet joins it, so ``doc.header.section_init()`` creates an
        empty HEADER without importing the section class or replacing the
        object you hold; a section the document holds keeps its place.
        """
        self._section_written()


class Section(BaseSection):
    """A named section holding an ordered set of ``KEY=VALUE`` pairs.

    ``section[key]`` reads, assigns and deletes values, ``key in section``
    tests for one, and iterating yields ``(key, value)`` pairs, so
    ``dict(section)`` and ``for key, value in section`` both work. Keys are
    stored upper-case and looked up case-insensitively. Values are always
    strings, exactly as they appear in the file; a comma-separated list is
    one string here, and :class:`Field` splits it when declared with a
    ``list[T]`` type. Assigning ``None`` to a key removes it.

    ``name`` and ``fields`` are positional-only, so every keyword argument
    is a key: ``Section("HEADER", VERSION="1")``. On a subclass a keyword
    that names a :class:`Field` goes through it, so ``HeaderSection(version=1)``
    stores the formatted value. Subclasses set ``section_name`` so the name
    can be omitted. A section is deliberately not a ``Mapping``: apart from
    the ``section_...`` names, every attribute of a subclass is a key.
    """

    def __init_subclass__(cls, **kwargs: Any) -> None:
        super().__init_subclass__(**kwargs)
        for value in vars(cls).values():
            if isinstance(value, Field):
                value._check(cls)
            elif isinstance(value, Declaration):
                raise TypeError(
                    f"{cls.__name__}.{value.attr}: a SectionField belongs on a "
                    "Document subclass"
                )

    def __init__(
        self,
        name: str | None = None,
        fields: Mapping[str, Any] | Iterable[tuple[str, Any]] | None = None,
        /,
        **kwargs: Any,
    ):
        super().__init__(name)
        #: The raw pairs, keys upper-case, in file order. Writing to it
        #: directly bypasses normalization, and bypasses the join of a
        #: section a document handed out but does not hold yet.
        self.section_fields: dict[str, str] = {}
        if fields is not None:
            pairs: Iterable[tuple[str, Any]]
            if isinstance(fields, Mapping):
                pairs = cast("Iterable[tuple[str, Any]]", fields.items())
            else:
                pairs = fields
            for key, value in pairs:
                self[key] = value
        for attr, value in kwargs.items():
            descriptor = getattr(type(self), attr, None)
            if isinstance(descriptor, Field):
                setattr(self, attr, value)
            else:
                self[attr] = value

    # -- container protocol ------------------------------------------------

    def __getitem__(self, key: str) -> str:
        if not isinstance(key, str):
            raise KeyError(key)
        return self.section_fields[_normalize_key(key)]

    def __setitem__(self, key: str, value: Any) -> None:
        """Store ``value`` under ``key``; ``None`` removes the key instead."""
        key = _normalize_key(key)
        if value is None:
            self.section_fields.pop(key, None)
        else:
            self.section_fields[key] = _normalize_value(value)
            self._section_written()

    def __delitem__(self, key: str) -> None:
        if not isinstance(key, str):
            raise KeyError(key)
        del self.section_fields[_normalize_key(key)]

    def __iter__(self) -> Iterator[tuple[str, str]]:
        return iter(self.section_fields.items())

    def __len__(self) -> int:
        return len(self.section_fields)

    def __contains__(self, key: object) -> bool:
        return isinstance(key, str) and _normalize_key(key) in self.section_fields

    @overload
    def section_get(self, key: str) -> str | None: ...

    @overload
    def section_get(self, key: str, *, default: _T) -> str | _T: ...

    def section_get(self, key: str, *, default: Any = None) -> Any:
        """The raw value stored under ``key``, or ``default`` when there is none.

        The lenient counterpart of the subscript: lookups are case-insensitive
        as everywhere, and a key that is not a string counts as absent rather
        than raising. The value is the stored string: no converter runs and no
        field default applies, those belong to the typed attributes.
        """
        if not isinstance(key, str):
            return default
        return self.section_fields.get(_normalize_key(key), default)

    def section_init(self) -> None:
        """Drop every pair and start over; see :meth:`BaseSection.section_init`."""
        self.section_fields.clear()
        super().section_init()

    # -- misc --------------------------------------------------------------

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, Section):
            return NotImplemented
        return (
            self.section_name == other.section_name
            and self.section_fields == other.section_fields
        )

    __hash__ = None  # type: ignore[assignment]

    def __repr__(self) -> str:
        return f"{type(self).__name__}({self.section_name!r}, {self.section_fields!r})"


class TextSection(BaseSection):
    """A named section whose content is free text rather than key/value pairs.

    ``section_text`` holds the lines joined with ``"\\n"``. The reader
    produces these for the sections a schema registers as text. ``name``
    and ``text`` are positional-only.

    Text starts at its first non-blank character: leading whitespace on the
    first line, blank lines at either end and trailing spaces cannot be told
    apart from layout, so a round trip through a file drops them.
    """

    def __init_subclass__(cls, **kwargs: Any) -> None:
        super().__init_subclass__(**kwargs)
        for value in vars(cls).values():
            if isinstance(value, Field):
                raise TypeError(
                    f"{cls.__name__}.{value.attr}: a Field needs a Section subclass, "
                    f"and {cls.__name__} holds free text rather than keys"
                )
            if isinstance(value, Declaration):
                raise TypeError(
                    f"{cls.__name__}.{value.attr}: a SectionField belongs on a "
                    "Document subclass"
                )

    def __init__(self, name: str | None = None, text: str = "", /):
        super().__init__(name)
        if not isinstance(text, str):
            raise TypeError(f"text must be a str, not {type(text).__name__}")
        self.section_text = text

    @property
    def section_text(self) -> str:
        """The text, lines joined with ``"\\n"``."""
        return self._section_text

    @section_text.setter
    def section_text(self, text: str) -> None:
        self._section_text = text
        self._section_written()

    def section_init(self) -> None:
        """Drop the text and start over; see :meth:`BaseSection.section_init`."""
        self._section_text = ""
        super().section_init()

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, TextSection):
            return NotImplemented
        return (
            self.section_name == other.section_name
            and self.section_text == other.section_text
        )

    __hash__ = None  # type: ignore[assignment]

    def __repr__(self) -> str:
        return f"{type(self).__name__}({self.section_name!r}, {self.section_text!r})"


def convert_section(section: BaseSection, target: type[_S]) -> _S:
    """Return ``section`` as an instance of ``target``, copying its content."""
    if isinstance(section, target):
        return section
    if issubclass(target, TextSection):
        if not isinstance(section, TextSection):
            raise TypeError(
                f"section {section.section_name} holds key/value pairs but "
                f"{target.__name__} is a text section"
            )
        return target(section.section_name, section.section_text)
    if issubclass(target, Section):
        if not isinstance(section, Section):
            raise TypeError(
                f"section {section.section_name} is free text but "
                f"{target.__name__} is a key/value section"
            )
        return target(section.section_name, section.section_fields)
    raise TypeError(f"{target.__name__} is not a section class")
