"""Typed access to section values: the :class:`Field` descriptor and converters."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from typing import (
    TYPE_CHECKING,
    Any,
    Generic,
    Literal,
    TypeVar,
    get_args,
    get_origin,
    overload,
)

if TYPE_CHECKING:
    from .model import Section

__all__ = ["Converter", "Field"]

T = TypeVar("T")


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


def name_from_attr(attr: str) -> str:
    """The key or section name an attribute stands for.

    The attribute is upper-cased, and one trailing underscore is dropped so
    that ``class_`` stands for ``CLASS``, the PEP 8 spelling for a name that
    is a Python keyword.
    """
    if attr.endswith("_") and not attr.endswith("__"):
        attr = attr[:-1]
    return attr.upper()


def check_declaration(
    owner: type, attr: str, prefix: str, allowed: type, keyword: str
) -> None:
    """Refuse a descriptor whose attribute name the library needs for itself.

    ``prefix`` is the namespace reserved on ``owner`` (``section_`` on a
    section, ``document_`` on a document). Any other attribute may be
    declared unless a base class already defines it as something other
    than an ``allowed`` descriptor, which may be redeclared. ``keyword`` is
    the argument that binds a name explicitly when the attribute cannot
    spell it.
    """
    where = f"{owner.__name__}.{attr}"
    hint = f"declare it under another attribute and pass {keyword}=... explicitly"
    if attr.startswith(prefix):
        raise TypeError(
            f"{where}: attribute names starting with {prefix!r} are reserved; {hint}"
        )
    for base in owner.__mro__[1:]:
        if attr in vars(base):
            if not isinstance(vars(base)[attr], allowed):
                raise TypeError(f"{where} would shadow {base.__name__}.{attr}; {hint}")
            break


class Declaration:
    """What :class:`Field` and ``SectionField`` share: a schema descriptor.

    ``__set_name__`` records the attribute the descriptor was declared under.
    The owning class validates the declaration in ``__init_subclass__``, so a
    bad one is a plain ``TypeError``; Python 3.11 and earlier wrap anything
    raised from ``__set_name__`` in a ``RuntimeError``.
    """

    attr: str = ""

    def __set_name__(self, owner: type, attr: str) -> None:
        self.attr = attr


class Field(Declaration, Generic[T]):
    """Descriptor exposing one key of a :class:`Section` as a typed attribute.

    The key is the attribute's name in upper case, with one trailing
    underscore dropped (``class_`` stands for ``CLASS``). Pass ``key`` only
    when the attribute cannot spell it, such as ``Field(int, key="MAX-SIZE")``.

    ``parse`` converts the stored string to the attribute's type on read and
    ``format`` converts it back to a string on write. Passing ``type`` is
    shorthand for ``parse=type, format=str``; a :class:`Converter` supplies
    both. Values with leading zeros need an explicit ``format`` to survive a
    round trip, for example ``Field(int, format="{:05d}".format)`` or
    ``Field(zero_padded(5))``.

    A ``type`` of ``list[T]`` (or bare ``list``) makes the attribute a list:
    the stored value is split on commas, each item converted with ``T``, and
    joined again on assignment. ``parse`` and ``format`` then apply to each
    item, an empty value is an empty list, and the list returned is a copy,
    so assign a new list rather than mutating it.

    A key the section lacks reads as ``default``, which is ``None`` unless
    given, so an absent key reads back as the ``None`` that removes it on
    assignment. ``required=True`` makes such a read raise
    :class:`AttributeError` instead, for keys a file must carry; a required
    field cannot have a default. Assigning ``None`` removes the key, and so
    does ``del``, silently when the key is already absent.

    A field may only be declared on a :class:`Section` subclass, under an
    attribute that does not start with ``section_`` and that no base class
    already uses for something else; anything else is a ``TypeError`` when
    the class is created.
    """

    key: str
    attr: str

    # -- no type: the raw string -------------------------------------------

    @overload
    def __init__(
        self: Field[str | None],
        type: None = None,
        *,
        key: str | None = None,
        parse: None = None,
        format: Callable[[Any], str] | None = None,
        default: None = None,
        required: Literal[False] = False,
    ) -> None: ...

    @overload
    def __init__(
        self: Field[str],
        type: None = None,
        *,
        key: str | None = None,
        parse: None = None,
        format: Callable[[Any], str] | None = None,
        required: Literal[True],
    ) -> None: ...

    @overload
    def __init__(
        self: Field[str],
        type: None = None,
        *,
        key: str | None = None,
        parse: None = None,
        format: Callable[[Any], str] | None = None,
        default: str,
    ) -> None: ...

    # -- list[T] -----------------------------------------------------------

    @overload
    def __init__(
        self: Field[list[T] | None],
        type: type[list[T]],
        *,
        key: str | None = None,
        parse: Callable[[str], T] | None = None,
        format: Callable[[T], str] | None = None,
        default: None = None,
        required: Literal[False] = False,
    ) -> None: ...

    @overload
    def __init__(
        self: Field[list[T]],
        type: type[list[T]],
        *,
        key: str | None = None,
        parse: Callable[[str], T] | None = None,
        format: Callable[[T], str] | None = None,
        required: Literal[True],
    ) -> None: ...

    @overload
    def __init__(
        self: Field[list[T]],
        type: type[list[T]],
        *,
        key: str | None = None,
        parse: Callable[[str], T] | None = None,
        format: Callable[[T], str] | None = None,
        default: Iterable[T],
    ) -> None: ...

    # -- a type, converter or parse callable -------------------------------

    @overload
    def __init__(
        self: Field[T | None],
        type: Converter[T] | Callable[[str], T],
        *,
        key: str | None = None,
        parse: Callable[[str], T] | None = None,
        format: Callable[[T], str] | None = None,
        default: None = None,
        required: Literal[False] = False,
    ) -> None: ...

    @overload
    def __init__(
        self: Field[T],
        type: Converter[T] | Callable[[str], T],
        *,
        key: str | None = None,
        parse: Callable[[str], T] | None = None,
        format: Callable[[T], str] | None = None,
        required: Literal[True],
    ) -> None: ...

    @overload
    def __init__(
        self: Field[T],
        type: Converter[T] | Callable[[str], T],
        *,
        key: str | None = None,
        parse: Callable[[str], T] | None = None,
        format: Callable[[T], str] | None = None,
        default: T,
    ) -> None: ...

    # -- parse= on its own -------------------------------------------------

    @overload
    def __init__(
        self: Field[T | None],
        type: None = None,
        *,
        key: str | None = None,
        parse: Callable[[str], T],
        format: Callable[[T], str] | None = None,
        default: None = None,
        required: Literal[False] = False,
    ) -> None: ...

    @overload
    def __init__(
        self: Field[T],
        type: None = None,
        *,
        key: str | None = None,
        parse: Callable[[str], T],
        format: Callable[[T], str] | None = None,
        required: Literal[True],
    ) -> None: ...

    @overload
    def __init__(
        self: Field[T],
        type: None = None,
        *,
        key: str | None = None,
        parse: Callable[[str], T],
        format: Callable[[T], str] | None = None,
        default: T,
    ) -> None: ...

    def __init__(
        self,
        type: Any = None,
        *,
        key: str | None = None,
        parse: Any = None,
        format: Any = None,
        default: Any = None,
        required: bool = False,
    ) -> None:
        if isinstance(type, str):
            raise TypeError(
                "the key is keyword-only: name the attribute after the key, "
                f"or pass key={type!r}"
            )
        if key is not None:
            if not isinstance(key, str):
                raise TypeError(f"key must be a str, not {builtins_type(key).__name__}")
            if not key:
                raise ValueError("key must not be empty")
            key = key.upper()
        if required and default is not None:
            raise TypeError("a required field cannot have a default")
        # An empty key means "take it from the attribute" in __set_name__.
        self.key = key or ""
        self.attr = self.key
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
        self.required = required

    def __set_name__(self, owner: type, attr: str) -> None:
        super().__set_name__(owner, attr)
        if not self.key:
            self.key = name_from_attr(attr)

    def _check(self, owner: type) -> None:
        """Validate the declaration; ``Section.__init_subclass__`` calls this."""
        check_declaration(owner, self.attr, "section_", Field, "key")
        if not self.key:
            raise TypeError(
                f"{owner.__name__}.{self.attr} cannot name a key; "
                "pass key=... explicitly"
            )

    def _describe(self, section: Section) -> str:
        return f"{builtins_type(section).__name__}.{self.attr} ({self.key})"

    @overload
    def __get__(self, section: None, owner: type) -> Field[T]: ...

    @overload
    def __get__(self, section: Section, owner: type | None = None) -> T: ...

    def __get__(self, section: Section | None, owner: type | None = None) -> Any:
        if section is None:
            return self
        raw = section.section_fields.get(self.key)
        if raw is None:
            if self.required:
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
            section.section_fields.pop(self.key, None)
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
        section.section_fields.pop(self.key, None)

    def __repr__(self) -> str:
        return f"{builtins_type(self).__name__}({self.key!r})"


# ``type`` is a parameter name above; keep the builtin reachable.
builtins_type = type
