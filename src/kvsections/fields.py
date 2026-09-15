"""Typed access to section values: the :class:`Field` descriptor and converters."""

from __future__ import annotations

from collections.abc import Callable
from typing import (
    TYPE_CHECKING,
    Any,
    Generic,
    TypeVar,
    get_args,
    get_origin,
    overload,
)

if TYPE_CHECKING:
    from .model import Section

__all__ = ["MISSING", "Converter", "Field"]

T = TypeVar("T")


class _Missing:
    def __repr__(self) -> str:
        return "<missing>"


#: Sentinel meaning "no default was given".
MISSING: Any = _Missing()


class Converter(Generic[T]):
    """A ``parse``/``format`` pair that a :class:`Field` accepts as its type.

    ``parse`` turns the stored string into a value and ``format`` turns a
    value back into the string to store. Ready-made converters for common
    encodings live in :mod:`kvsections.converters`.
    """

    __slots__ = ("parse", "format", "name")

    def __init__(
        self,
        parse: Callable[[str], T],
        format: Callable[[T], str],
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
    if type_ is bool:
        raise TypeError(
            "bool cannot parse text (bool('NO') is True); use a flag converter "
            "such as kvsections.converters.YES_NO"
        )
    return type_, None


class Field(Generic[T]):
    """Descriptor exposing one key of a :class:`Section` as a typed attribute.

    ``parse`` converts the stored string to the attribute's type on read and
    ``format`` converts it back to a string on write. Passing ``type`` is
    shorthand for ``parse=type, format=str``; a :class:`Converter` supplies
    both. Values with leading zeros need an explicit ``format`` to survive a
    round trip, for example ``Field("APPLES", int, format="{:05d}".format)``
    or ``Field("APPLES", zero_padded(5))``.

    A ``type`` of ``list[T]`` (or bare ``list``) makes the attribute a list:
    the stored value is split on commas, each item converted with ``T``, and
    joined again on assignment. ``parse`` and ``format`` then apply to each
    item, an empty value is an empty list, and the list returned is a copy,
    so assign a new list rather than mutating it.

    Reading a missing key raises :class:`AttributeError` unless ``default`` is
    given. Assigning ``None`` removes the key.
    """

    key: str
    attr: str

    @overload
    def __init__(
        self: Field[str],
        key: str,
        type: None = None,
        *,
        parse: None = None,
        format: Callable[[Any], str] | None = None,
        default: Any = ...,
    ) -> None: ...

    @overload
    def __init__(
        self: Field[list[T]],
        key: str,
        type: type[list[T]],
        *,
        parse: Callable[[str], T] | None = None,
        format: Callable[[T], str] | None = None,
        default: Any = ...,
    ) -> None: ...

    @overload
    def __init__(
        self: Field[T],
        key: str,
        type: Converter[T] | Callable[[str], T],
        *,
        parse: Callable[[str], T] | None = None,
        format: Callable[[T], str] | None = None,
        default: Any = ...,
    ) -> None: ...

    @overload
    def __init__(
        self: Field[T],
        key: str,
        type: None = None,
        *,
        parse: Callable[[str], T],
        format: Callable[[T], str] | None = None,
        default: Any = ...,
    ) -> None: ...

    def __init__(
        self,
        key: str,
        type: Any = None,
        *,
        parse: Any = None,
        format: Any = None,
        default: Any = MISSING,
    ) -> None:
        if not isinstance(key, str):
            raise TypeError(f"key must be a str, not {builtins_type(key).__name__}")
        self.key = key.upper()
        self.attr = key
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

    def __set_name__(self, owner: type, attr: str) -> None:
        self.attr = attr

    def _describe(self, section: Section) -> str:
        return f"{builtins_type(section).__name__}.{self.attr} ({self.key})"

    @overload
    def __get__(self, section: None, owner: type) -> Field[T]: ...

    @overload
    def __get__(self, section: Section, owner: type | None = None) -> T: ...

    def __get__(self, section: Section | None, owner: type | None = None) -> Any:
        if section is None:
            return self
        raw = section.fields.get(self.key)
        if raw is None:
            if self.default is MISSING:
                raise AttributeError(f"{self._describe(section)} is not set")
            if self.is_list and self.default is not None:
                return list(self.default)
            return self.default
        if self.is_list:
            items = raw.split(",") if raw else []
            if self.parse is not None:
                return [self.parse(item) for item in items]
            return items
        return self.parse(raw) if self.parse is not None else raw

    def __set__(self, section: Section, value: T | None) -> None:
        if value is None:
            section.fields.pop(self.key, None)
            return
        if self.is_list:
            if isinstance(value, str):
                raise TypeError(f"{self._describe(section)} expects a list, not a str")
            items: Any = value
            if self.format is not None:
                items = [self.format(item) for item in items]
            section[self.key] = list(items)
        else:
            section[self.key] = self.format(value) if self.format is not None else value

    def __delete__(self, section: Section) -> None:
        if self.key not in section.fields:
            raise AttributeError(f"{self._describe(section)} is not set")
        del section[self.key]

    def __repr__(self) -> str:
        return f"{builtins_type(self).__name__}({self.key!r})"


# ``type`` is a parameter name above; keep the builtin reachable.
builtins_type = type
