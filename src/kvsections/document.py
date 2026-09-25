"""The document: an ordered collection of uniquely named sections."""

from __future__ import annotations

import codecs
import io
from collections.abc import Iterable, Iterator, Mapping, Sequence
from typing import IO, Any, ClassVar, Generic, TypeVar, cast, overload

from .errors import ParseWarning
from .fields import Declaration, Field, check_declaration, name_from_attr
from .model import BaseSection, Section, TextSection, _normalize_key, convert_section
from .reader import parse
from .records import plan_order
from .writer import format_document

_D = TypeVar("_D", bound="Document")
_S = TypeVar("_S", bound=BaseSection)
_TS = TypeVar("_TS", bound=TextSection)
_T = TypeVar("_T")

#: Typed empty defaults for the schema lookups on bases that declare none.
_NO_TYPES: Mapping[str, type[BaseSection]] = {}
_NO_ALIASES: Mapping[str, str] = {}

__all__ = ["Document", "SectionField"]


def _decode(data: bytes, encoding: str, errors: str) -> str:
    """Decode file bytes, keeping a UTF-8 byte order mark as U+FEFF for the reader."""
    if data.startswith(codecs.BOM_UTF8):
        return "\ufeff" + data[len(codecs.BOM_UTF8) :].decode(encoding, errors)
    return data.decode(encoding, errors)


class SectionField(Declaration, Generic[_S]):
    """Descriptor exposing one section of a :class:`Document` as an attribute.

    The section's name is the attribute's name in upper case, with one
    trailing underscore dropped, or the ``section_name`` the section class
    declares, which the attribute must then spell. Pass ``name`` only when
    the attribute cannot spell it, such as
    ``SectionField(TextSection, name="MY-NOTES")``; an explicit name must
    still agree with the class.

    Declaring one on a ``Document`` subclass registers ``section_type`` for
    that name, so the reader instantiates it for matching sections, and
    registers each of ``aliases`` as another spelling of the same section.

    Reading the attribute returns the section. When the document has none
    it returns an empty section of the declared class, which joins the
    document on its first write, so ``doc.header.version = 7`` works on a
    fresh document. Until then the document is unchanged: ``"HEADER" in
    doc`` is false, nothing is written out, and every read returns that
    same section. Assigning ``None`` to a field removes a key rather than
    storing one, so it does not make the section join; an empty value or
    empty text does.

    To create a section at once, or start one over, call its
    ``section_init``: ``doc.header.section_init()`` makes an empty HEADER
    in place, without importing the class. Assigning a section stores it.
    A text section also takes a string, its whole content, the way a pair
    section takes values through its typed attributes; a mapping is
    refused, since it would store values raw and skip the converters.
    Assigning ``None`` removes the section. A section handed out or stored
    earlier is stale once another replaces it or it is removed: writing to
    it no longer reaches the document.

    The static types agree with all of this under both mypy and pyright:
    ``SectionField(HeaderSection)`` reads as ``HeaderSection`` and accepts
    a ``HeaderSection`` or ``None``; ``SectionField(TextSection)`` also
    accepts a ``str``.

    A section field may only be declared on a :class:`Document` subclass,
    under an attribute that does not start with ``document_`` and that no
    base class already uses for something else; anything else is a
    ``TypeError`` when the class is created.
    """

    #: The declared section class. Declared without the type parameter so
    #: that an ``isinstance`` check, which gives ``SectionField[Unknown]``
    #: under pyright, still reads it as a section class.
    section_type: type[BaseSection]

    def __init__(
        self,
        section_type: type[_S],
        *,
        name: str | None = None,
        aliases: Iterable[str] = (),
    ):
        if not isinstance(section_type, type) or not issubclass(
            section_type, BaseSection
        ):
            raise TypeError("section_type must be a Section or TextSection subclass")
        self.section_type = section_type
        self.aliases = tuple(_normalize_key(alias) for alias in aliases)
        # Empty until __set_name__ derives the name from the attribute.
        self.name = ""
        self._explicit = name is not None
        declared = getattr(section_type, "section_name", None)
        if name is not None:
            name = _normalize_key(name)
            if declared is not None and _normalize_key(declared) != name:
                raise TypeError(
                    f"{section_type.__name__} is named {_normalize_key(declared)}, "
                    f"not {name}"
                )
            self._set_name(name)
        elif declared is not None:
            self._set_name(declared)
        self.attr = self.name

    def _set_name(self, name: str) -> None:
        name = _normalize_key(name)
        if name in self.aliases:
            raise ValueError(f"{name} cannot be an alias of itself")
        self.name = name

    def _bind(self, owner: type) -> None:
        """Settle the name from the attribute, for ``Document.__init_subclass__``."""
        check_declaration(owner, self.attr, "document_", SectionField, "name")
        if self._explicit:
            return
        derived = name_from_attr(self.attr)
        if not self.name:
            if not derived:
                raise TypeError(
                    f"{owner.__name__}.{self.attr} cannot name a section; "
                    "pass name=... explicitly"
                )
            self._set_name(derived)
        elif derived != self.name:
            raise TypeError(
                f"{owner.__name__}.{self.attr}: {self.section_type.__name__} is named "
                f"{self.name}; name the attribute after it or pass name={self.name!r}"
            )

    @overload
    def __get__(self, doc: None, owner: type) -> SectionField[_S]: ...

    @overload
    def __get__(self, doc: Document, owner: type | None = None) -> _S: ...

    def __get__(self, doc: Document | None, owner: type | None = None) -> Any:
        if doc is None:
            return self
        section = doc.document_sections.get(self.name)
        if section is not None:
            if isinstance(section, self.section_type):
                return section
            return doc.document_add(section)
        pending = doc._document_pending.get(self.name)
        if pending is None:
            pending = self.section_type(self.name)
            pending._section_join = doc.document_add
            doc._document_pending[self.name] = pending
        return pending

    @overload
    def __set__(
        self: SectionField[_TS], doc: Document, value: _TS | str | None
    ) -> None: ...

    @overload
    def __set__(self, doc: Document, value: _S | None) -> None: ...

    def __set__(self, doc: Document, value: Any) -> None:
        if value is None:
            doc._document_forget_pending(self.name)
            doc.document_sections.pop(self.name, None)
            return
        if isinstance(value, BaseSection):
            if type(doc).document_canonical_name(value.section_name) != self.name:
                raise ValueError(
                    f"expected section {self.name}, got {value.section_name}"
                )
            doc.document_add(value)
            return
        if issubclass(self.section_type, TextSection) and isinstance(value, str):
            doc.document_add(self.section_type(self.name, value))
            return
        kind = self.section_type.__name__
        if issubclass(self.section_type, TextSection):
            kind = f"str or {kind}"
        raise TypeError(f"{self.attr} expects a {kind}, not {type(value).__name__}")

    def __delete__(self, doc: Document) -> None:
        del doc.document_sections[self.name]

    def __repr__(self) -> str:
        extra = f", aliases={self.aliases!r}" if self.aliases else ""
        cls_name = self.section_type.__name__
        return f"{type(self).__name__}({cls_name}, {self.name!r}{extra})"


def _merge_schema(
    registry: dict[str, type[BaseSection]],
    aliases: dict[str, str],
    more_registry: Mapping[str, type[BaseSection]],
    more_aliases: Mapping[str, str],
) -> None:
    """Layer one schema over another: the newer declarations win.

    An alias in the newer schema removes an older registration of that
    name, and a registration removes an older alias.
    """
    for name in more_registry:
        aliases.pop(name, None)
    for alias in more_aliases:
        registry.pop(alias, None)
    registry.update(more_registry)
    aliases.update(more_aliases)


def _collect_schema(
    cls: type[Document],
) -> tuple[dict[str, type[BaseSection]], dict[str, str]]:
    """Merge the inherited registry and aliases with a class's own declarations.

    A class's own declarations win over inherited ones of either kind: an
    alias declared here removes an inherited registration of the same name,
    and a registration here removes an inherited alias.
    """
    registry: dict[str, type[BaseSection]] = {}
    aliases: dict[str, str] = {}
    # __mro__ is tuple[type, ...], which pyright reads as type[Unknown].
    bases = cast("Sequence[type[object]]", cls.__mro__[1:])
    for base in reversed(bases):
        if not issubclass(base, Document):
            for value in vars(base).values():
                if isinstance(value, SectionField):
                    raise TypeError(
                        f"{base.__name__}.{value.attr}: a SectionField belongs on a "
                        "Document subclass; on a plain mixin it is never registered"
                    )
        inherited_registry: Mapping[str, type[BaseSection]] = getattr(
            base, "document_section_types", _NO_TYPES
        )
        inherited_aliases: Mapping[str, str] = getattr(
            base, "document_aliases", _NO_ALIASES
        )
        _merge_schema(registry, aliases, inherited_registry, inherited_aliases)

    own_registry: dict[str, type[BaseSection]] = {}
    own_aliases: dict[str, str] = {}
    declared_aliases: Mapping[str, str] = cls.__dict__.get(
        "document_aliases", _NO_ALIASES
    )
    for alias, canonical in declared_aliases.items():
        own_aliases[_normalize_key(alias)] = _normalize_key(canonical)
    for value in cls.__dict__.values():
        if isinstance(value, SectionField):
            own_registry[value.name] = value.section_type
            for alias in value.aliases:
                if own_aliases.get(alias, value.name) != value.name:
                    raise TypeError(
                        f"{alias} is already an alias of {own_aliases[alias]}"
                    )
                own_aliases[alias] = value.name

    _merge_schema(registry, aliases, own_registry, own_aliases)
    for alias, canonical in aliases.items():
        if alias in registry:
            raise TypeError(
                f"{alias} is registered as a section and as an alias of {canonical}"
            )
        if canonical in aliases:
            raise TypeError(
                f"{canonical} is an alias itself, so {alias} cannot map to it"
            )
    return registry, aliases


class Document:
    """An ordered collection of sections, keyed by name.

    ``doc[name]`` reads, stores and deletes sections, ``name in doc`` tests
    for one, and iterating yields ``(name, section)`` pairs, so ``dict(doc)``
    and ``for name, section in doc`` both work. Names are case-insensitive
    and aliases resolve.

    Subclass it to describe a specific file: declare :class:`SectionField`
    attributes for the sections you care about, give alternative spellings
    with ``aliases`` (or a ``document_aliases`` table), and set
    ``document_order`` if the file expects sections in a particular order
    (see :meth:`document_reorder`). The generic document reads every section
    as key/value pairs; a schema declares free-text sections with
    ``SectionField(TextSection)``.

    Everything the library puts on a document is named ``document_...``, so
    every other attribute of a subclass can be a section. Sections are keyed
    by canonical name, so one read under an alias is found under either
    spelling. The section itself keeps the spelling it was read with, and
    the writer preserves it.
    """

    #: Section classes to instantiate by name, collected from SectionField
    #: declarations. Empty on the generic document, which reads every section
    #: as key/value pairs; subclasses inherit and extend it.
    document_section_types: ClassVar[dict[str, type[BaseSection]]] = {}

    #: Alternative spellings mapped to their canonical name. Empty on the
    #: generic document; schemas declare their own, and subclasses inherit
    #: and extend them.
    document_aliases: ClassVar[dict[str, str]] = {}

    #: Default order for :meth:`document_reorder`: section names, with ``...``
    #: marking where sections not listed go. Empty on the generic document.
    document_order: ClassVar[Sequence[Any]] = ()

    def __init_subclass__(cls, **kwargs: Any) -> None:
        super().__init_subclass__(**kwargs)
        for value in vars(cls).values():
            if isinstance(value, SectionField):
                value._bind(cls)
            elif isinstance(value, Field):
                raise TypeError(
                    f"{cls.__name__}.{value.attr}: a Field declares a key of a "
                    "Section; a document declares its sections with SectionField"
                )
        cls.document_section_types, cls.document_aliases = _collect_schema(cls)

    def __init__(
        self,
        sections: Iterable[BaseSection] | Mapping[str, BaseSection] | Document = (),
        /,
    ):
        self.document_sections: dict[str, BaseSection] = {}
        #: Problems the reader tolerated, in file order. Empty for documents
        #: built in code.
        self.document_warnings: list[ParseWarning] = []
        # The empty sections SectionField handed out for names the document
        # lacks, so that repeated reads agree; a first write moves one into
        # document_sections, a store or removal under its name forgets it.
        self._document_pending: dict[str, BaseSection] = {}
        items: Iterable[BaseSection]
        if isinstance(sections, Document):
            items = sections.document_sections.values()
        elif isinstance(sections, Mapping):
            items = cast("Iterable[BaseSection]", sections.values())
        else:
            items = sections
        for section in items:
            self.document_add(section)

    # -- section types -----------------------------------------------------

    @classmethod
    def document_canonical_name(cls, name: str) -> str:
        """The name a section called ``name`` is stored under."""
        name = _normalize_key(name)
        return cls.document_aliases.get(name, name)

    @classmethod
    def document_section_type(cls, name: str) -> type[BaseSection]:
        """The class used for a section called ``name``."""
        canonical = cls.document_canonical_name(name)
        return cls.document_section_types.get(canonical, Section)

    @classmethod
    def document_new_section(cls, name: str) -> BaseSection:
        """An empty section called ``name`` of the appropriate class."""
        return cls.document_section_type(name)(_normalize_key(name))

    def document_add(self, section: BaseSection) -> BaseSection:
        """Store ``section`` under its canonical name, replacing any existing one.

        If a different class is registered for the name the section is
        converted to it; the stored (possibly converted) section is returned.
        An empty section handed out for the name but not written yet is
        forgotten, so writing to it no longer reaches the document.
        """
        if not isinstance(section, BaseSection):
            raise TypeError(f"{section!r} is not a section")
        key = self.document_canonical_name(section.section_name)
        target = self.document_section_types.get(key)
        if target is not None:
            section = convert_section(section, target)
        self._document_forget_pending(key)
        self.document_sections[key] = section
        return section

    def _document_forget_pending(self, key: str) -> None:
        """Drop the empty section handed out for ``key``, if any: it is stale now."""
        pending = self._document_pending.pop(key, None)
        if pending is not None:
            pending._section_join = None

    # -- ordering ----------------------------------------------------------

    def document_reorder(self, order: Iterable[Any] | None = None) -> None:
        """Put the sections into a prescribed order, in place.

        ``order`` lists section names (aliases allowed) in the wanted order.
        One entry may be ``...``, standing for every section not named, kept
        in their current relative order; names after it form the tail of the
        document. Without ``...`` the unnamed sections follow the named ones.
        Names absent from the document are ignored. When ``order`` is omitted
        the class's ``document_order`` is used.
        """
        if order is None:
            order = self.document_order
        head, tail = plan_order(order, self.document_canonical_name)
        named = set(head) | set(tail)
        sections = self.document_sections
        ordered = (
            [name for name in head if name in sections]
            + [name for name in sections if name not in named]
            + [name for name in tail if name in sections]
        )
        reordered = {name: sections[name] for name in ordered}
        sections.clear()
        sections.update(reordered)

    # -- container protocol ------------------------------------------------

    def __getitem__(self, name: str) -> BaseSection:
        if not isinstance(name, str):
            raise KeyError(name)
        return self.document_sections[self.document_canonical_name(name)]

    def __setitem__(self, name: str, section: BaseSection) -> None:
        key = self.document_canonical_name(name)
        if not isinstance(section, BaseSection):
            raise TypeError(f"{section!r} is not a section")
        if self.document_canonical_name(section.section_name) != key:
            raise ValueError(
                f"cannot store section {section.section_name} under the name {name}"
            )
        self.document_add(section)

    def __delitem__(self, name: str) -> None:
        if not isinstance(name, str):
            raise KeyError(name)
        del self.document_sections[self.document_canonical_name(name)]

    def __iter__(self) -> Iterator[tuple[str, BaseSection]]:
        return iter(self.document_sections.items())

    def __len__(self) -> int:
        return len(self.document_sections)

    def __contains__(self, name: object) -> bool:
        return (
            isinstance(name, str)
            and self.document_canonical_name(name) in self.document_sections
        )

    @overload
    def document_get(self, name: str) -> BaseSection | None: ...

    @overload
    def document_get(self, name: str, *, default: _T) -> BaseSection | _T: ...

    @overload
    def document_get(self, name: str, key: str) -> str | None: ...

    @overload
    def document_get(self, name: str, key: str, *, default: _T) -> str | _T: ...

    def document_get(
        self, name: str, key: str | None = None, *, default: Any = None
    ) -> Any:
        """The section called ``name``, or with ``key`` the raw value it holds.

        The lenient counterpart of ``doc[name][key]``: aliases resolve and
        lookups are case-insensitive as for the subscript, but nothing
        raises. Without ``key`` the result is the section or ``default``.
        With ``key`` it is the stored string, or ``default`` when the section
        is absent, holds free text rather than pairs, or lacks the key. A
        name or key that is not a string counts as absent. Only ``default``
        applies: no converter runs and no field default does, those belong
        to the typed attributes.
        """
        if not isinstance(name, str):
            return default
        section = self.document_sections.get(self.document_canonical_name(name))
        if key is None:
            return default if section is None else section
        if not isinstance(section, Section):
            return default
        return section.section_get(key, default=default)

    def document_has(self, name: str, key: str | None = None) -> bool:
        """Whether a section called ``name`` exists, and with ``key`` holds that key.

        The two-level counterpart of ``in``: aliases resolve and lookups are
        case-insensitive, an empty value counts as present, and a name or key
        that is not a string, or a section that holds free text, gives
        ``False`` rather than raising. Like the ``get`` family it looks at
        the stored pairs only, so a field default does not count as present.
        """
        if not isinstance(name, str):
            return False
        section = self.document_sections.get(self.document_canonical_name(name))
        if key is None:
            return section is not None
        return isinstance(section, Section) and key in section

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, Document):
            return NotImplemented
        return self.document_sections == other.document_sections

    __hash__ = None  # type: ignore[assignment]

    def __repr__(self) -> str:
        return f"{type(self).__name__}({list(self.document_sections.values())!r})"

    # -- reading -----------------------------------------------------------

    @classmethod
    def document_loads(cls: type[_D], text: str, *, strict: bool = False) -> _D:
        """Parse ``text``.

        Reading is tolerant: problems are recorded in ``document_warnings``.
        With ``strict=True`` the first problem raises :class:`ParseError`
        instead.
        """
        return parse(cls, text, strict=strict)

    @classmethod
    def document_load(
        cls: type[_D],
        fp: IO[Any],
        *,
        strict: bool = False,
        encoding: str = "ascii",
        errors: str = "replace",
    ) -> _D:
        """Parse the contents of an open text or binary file.

        ``encoding`` and ``errors`` apply to binary files only. A UTF-8 byte
        order mark at the start is dropped with a warning.
        """
        data = fp.read()
        if isinstance(data, bytes):
            data = _decode(data, encoding, errors)
        return cls.document_loads(data, strict=strict)

    @classmethod
    def document_read(
        cls: type[_D],
        path: Any,
        *,
        strict: bool = False,
        encoding: str = "ascii",
        errors: str = "replace",
    ) -> _D:
        """Parse the file at ``path``. See :meth:`document_load`."""
        with open(path, "rb") as fp:
            return cls.document_load(
                fp, strict=strict, encoding=encoding, errors=errors
            )

    # -- writing -----------------------------------------------------------

    def document_dumps(
        self,
        *,
        width: int | None = 80,
        margin: int = 1,
        indent: int | None = None,
        newline: str = "\n",
    ) -> str:
        """Render the document as text.

        Every record is padded to ``width`` columns, of which the last
        ``margin`` stay blank; pairs that would cross that limit wrap onto an
        indented continuation record. ``width=None`` disables wrapping and
        padding. ``indent`` is the column where content starts and defaults
        to one more than the longest section name. Records end with LF unless
        ``newline`` says otherwise, whatever ending the input had. Raises
        :class:`ValueError` for content that cannot be written faithfully.
        """
        return format_document(
            self, width=width, margin=margin, indent=indent, newline=newline
        )

    def document_dump(self, fp: IO[Any], **kwargs: Any) -> None:
        """Write the document to an open text or binary file.

        Accepts the :meth:`document_dumps` options. Records end exactly as
        ``newline`` says whatever mode the file was opened in: for a text
        file the bytes go to its underlying buffer, bypassing newline
        translation, so a plain ``open(path, "w")`` gives the same result
        on every platform.
        """
        data = self.document_dumps(**kwargs)
        if not isinstance(fp, io.TextIOBase):
            fp.write(data.encode("ascii"))
            return
        buffer = getattr(fp, "buffer", None)
        if buffer is None:
            fp.write(data)
            return
        fp.flush()
        buffer.write(data.encode(fp.encoding or "ascii"))

    def document_write(
        self, path: Any, *, encoding: str = "ascii", **kwargs: Any
    ) -> None:
        """Write the document to ``path``, with the :meth:`document_dumps` options."""
        with open(path, "w", encoding=encoding, newline="") as fp:
            fp.write(self.document_dumps(**kwargs))
