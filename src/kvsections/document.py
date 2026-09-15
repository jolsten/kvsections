"""The document: an ordered collection of uniquely named sections."""

from __future__ import annotations

import codecs
import io
from collections.abc import Iterable, Iterator, Mapping, MutableMapping, Sequence
from typing import IO, Any, ClassVar, TypeVar, cast

from .errors import ParseWarning
from .model import BaseSection, Section, TextSection, _normalize_key, convert_section
from .reader import parse
from .records import plan_order
from .writer import format_document

_D = TypeVar("_D", bound="Document")

__all__ = ["Document", "SectionField"]


def _decode(data: bytes, encoding: str, errors: str) -> str:
    """Decode file bytes, keeping a UTF-8 byte order mark as U+FEFF for the reader."""
    if data.startswith(codecs.BOM_UTF8):
        return "\ufeff" + data[len(codecs.BOM_UTF8) :].decode(encoding, errors)
    return data.decode(encoding, errors)


class SectionField:
    """Descriptor exposing one section of a :class:`Document` as an attribute.

    Declaring one on a ``Document`` subclass also registers ``section_type``
    for that name, so the reader instantiates it for matching sections, and
    registers each of ``aliases`` as another spelling of the same section.

    Reading the attribute returns the section, or raises ``AttributeError``
    if the document has none; reading never changes the document. Assigning
    a section stores it; assigning a mapping (or a string, for text sections)
    builds a new section from it, so ``doc.header = {}`` creates an empty
    one. Assigning ``None`` removes it.
    """

    def __init__(
        self,
        section_type: type[BaseSection],
        name: str | None = None,
        *,
        aliases: Iterable[str] = (),
    ):
        if not isinstance(section_type, type) or not issubclass(
            section_type, BaseSection
        ):
            raise TypeError("section_type must be a Section or TextSection subclass")
        if name is None:
            name = section_type.section_name
        if name is None:
            raise TypeError(
                f"{section_type.__name__} has no section_name; pass name= explicitly"
            )
        self.section_type = section_type
        self.name = _normalize_key(name)
        self.aliases = tuple(_normalize_key(alias) for alias in aliases)
        if self.name in self.aliases:
            raise ValueError(f"{self.name} cannot be an alias of itself")
        self.attr = self.name

    def __set_name__(self, owner: type, attr: str) -> None:
        self.attr = attr

    def __get__(self, doc: Document | None, owner: type | None = None) -> Any:
        if doc is None:
            return self
        section = doc.sections.get(self.name)
        if section is None:
            raise AttributeError(
                f"{type(doc).__name__}.{self.attr} ({self.name}) is not present; "
                f"assign {self.attr} = {{}} to create it"
            )
        if isinstance(section, self.section_type):
            return section
        return doc.add(section)

    def __set__(self, doc: Document, value: Any) -> None:
        if value is None:
            doc.sections.pop(self.name, None)
            return
        if isinstance(value, BaseSection):
            if type(doc).canonical_name(value.name) != self.name:
                raise ValueError(f"expected section {self.name}, got {value.name}")
            doc.add(value)
            return
        text = issubclass(self.section_type, TextSection)
        if text and not isinstance(value, str):
            raise TypeError(
                f"{self.attr} expects a str or a TextSection, "
                f"not {type(value).__name__}"
            )
        if not text and not isinstance(value, Mapping):
            raise TypeError(
                f"{self.attr} expects a mapping of fields or a Section, "
                f"not {type(value).__name__}"
            )
        if text:
            doc.add(cast("type[TextSection]", self.section_type)(self.name, value))
        else:
            doc.add(cast("type[Section]", self.section_type)(self.name, value))

    def __delete__(self, doc: Document) -> None:
        del doc.sections[self.name]

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
    for base in reversed(cls.__mro__[1:]):
        _merge_schema(
            registry,
            aliases,
            getattr(base, "section_types", {}),
            getattr(base, "section_aliases", {}),
        )

    own_registry: dict[str, type[BaseSection]] = {}
    own_aliases: dict[str, str] = {}
    for alias, canonical in cls.__dict__.get("section_aliases", {}).items():
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


class Document(MutableMapping[str, BaseSection]):
    """An ordered mapping of section name to section.

    Subclass it to describe a specific file: declare :class:`SectionField`
    attributes for the sections you care about, give alternative spellings
    with ``aliases`` (or a ``section_aliases`` table), and set
    ``section_order`` if the file expects sections in a particular order
    (see :meth:`reorder`). The generic document reads every section as
    key/value pairs; a schema declares free-text sections with
    ``SectionField(TextSection, ...)``.

    Sections are keyed by canonical name, so one read under an alias is found
    under either spelling. The section itself keeps the spelling it was read
    with, and the writer preserves it.
    """

    #: Section classes to instantiate by name, collected from SectionField
    #: declarations. Empty on the generic document, which reads every section
    #: as key/value pairs; subclasses inherit and extend it.
    section_types: ClassVar[dict[str, type[BaseSection]]] = {}

    #: Alternative spellings mapped to their canonical name. Empty on the
    #: generic document; schemas declare their own, and subclasses inherit
    #: and extend them.
    section_aliases: ClassVar[dict[str, str]] = {}

    #: Default order for :meth:`reorder`: section names, with ``...`` marking
    #: where sections not listed go. Empty on the generic document.
    section_order: ClassVar[Sequence[Any]] = ()

    def __init_subclass__(cls, **kwargs: Any) -> None:
        super().__init_subclass__(**kwargs)
        cls.section_types, cls.section_aliases = _collect_schema(cls)

    def __init__(
        self, sections: Iterable[BaseSection] | Mapping[str, BaseSection] = ()
    ):
        self.sections: dict[str, BaseSection] = {}
        #: Problems the reader tolerated, in file order. Empty for documents
        #: built in code.
        self.warnings: list[ParseWarning] = []
        if isinstance(sections, Mapping):
            sections = sections.values()
        for section in sections:
            self.add(section)

    # -- section types -----------------------------------------------------

    @classmethod
    def canonical_name(cls, name: str) -> str:
        """The name a section called ``name`` is stored under."""
        name = _normalize_key(name)
        return cls.section_aliases.get(name, name)

    @classmethod
    def section_type_for(cls, name: str) -> type[BaseSection]:
        """The class used for a section called ``name``."""
        return cls.section_types.get(cls.canonical_name(name), Section)

    @classmethod
    def new_section(cls, name: str) -> BaseSection:
        """An empty section called ``name`` of the appropriate class."""
        return cls.section_type_for(name)(_normalize_key(name))

    def add(self, section: BaseSection) -> BaseSection:
        """Store ``section`` under its canonical name, replacing any existing one.

        If a different class is registered for the name the section is
        converted to it; the stored (possibly converted) section is returned.
        """
        if not isinstance(section, BaseSection):
            raise TypeError(f"{section!r} is not a section")
        key = self.canonical_name(section.name)
        target = self.section_types.get(key)
        if target is not None:
            section = convert_section(section, target)
        self.sections[key] = section
        return section

    # -- ordering ----------------------------------------------------------

    def reorder(self, order: Iterable[Any] | None = None) -> None:
        """Put the sections into a prescribed order, in place.

        ``order`` lists section names (aliases allowed) in the wanted order.
        One entry may be ``...``, standing for every section not named, kept
        in their current relative order; names after it form the tail of the
        document. Without ``...`` the unnamed sections follow the named ones.
        Names absent from the document are ignored. When ``order`` is omitted
        the class's ``section_order`` is used.
        """
        if order is None:
            order = self.section_order
        head, tail = plan_order(order, self.canonical_name)
        named = set(head) | set(tail)
        ordered = (
            [name for name in head if name in self.sections]
            + [name for name in self.sections if name not in named]
            + [name for name in tail if name in self.sections]
        )
        sections = {name: self.sections[name] for name in ordered}
        self.sections.clear()
        self.sections.update(sections)

    # -- MutableMapping ----------------------------------------------------

    def __getitem__(self, name: str) -> BaseSection:
        if not isinstance(name, str):
            raise KeyError(name)
        return self.sections[self.canonical_name(name)]

    def __setitem__(self, name: str, section: BaseSection) -> None:
        key = self.canonical_name(name)
        if not isinstance(section, BaseSection):
            raise TypeError(f"{section!r} is not a section")
        if self.canonical_name(section.name) != key:
            raise ValueError(
                f"cannot store section {section.name} under the name {name}"
            )
        self.add(section)

    def __delitem__(self, name: str) -> None:
        if not isinstance(name, str):
            raise KeyError(name)
        del self.sections[self.canonical_name(name)]

    def __iter__(self) -> Iterator[str]:
        return iter(self.sections)

    def __len__(self) -> int:
        return len(self.sections)

    def __contains__(self, name: object) -> bool:
        return isinstance(name, str) and self.canonical_name(name) in self.sections

    def setdefault(self, name: str, default: Any = None) -> BaseSection:
        """Return the section called ``name``, storing ``default`` first if absent.

        The stored object is returned, which may be a converted copy of
        ``default`` when a section class is registered for the name.
        """
        if name in self:
            return self[name]
        self[name] = default
        return self[name]

    def update(self, other: Any = (), /, **kwargs: Any) -> None:
        """Add sections from another document, a mapping, or pairs.

        Sections from a mapping (another document included) are stored under
        their own names, so alias tables need not match between documents.
        """
        if isinstance(other, Mapping):
            for section in other.values():
                self.add(section)
        else:
            for name, section in other:
                self[name] = section
        for name, section in kwargs.items():
            self[name] = section

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, Document):
            return NotImplemented
        return self.sections == other.sections

    __hash__ = None  # type: ignore[assignment]

    def __repr__(self) -> str:
        return f"{type(self).__name__}({list(self.sections.values())!r})"

    # -- reading -----------------------------------------------------------

    @classmethod
    def loads(cls: type[_D], text: str, *, strict: bool = False) -> _D:
        """Parse ``text``.

        Reading is tolerant: problems are recorded in ``doc.warnings``. With
        ``strict=True`` the first problem raises :class:`ParseError` instead.
        """
        return parse(cls, text, strict=strict)

    @classmethod
    def load(
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
        return cls.loads(data, strict=strict)

    @classmethod
    def read(
        cls: type[_D],
        path: Any,
        *,
        strict: bool = False,
        encoding: str = "ascii",
        errors: str = "replace",
    ) -> _D:
        """Parse the file at ``path``. See :meth:`load`."""
        with open(path, "rb") as fp:
            return cls.load(fp, strict=strict, encoding=encoding, errors=errors)

    # -- writing -----------------------------------------------------------

    def dumps(
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

    def dump(self, fp: IO[Any], **kwargs: Any) -> None:
        """Write the document to an open text or binary file.

        Accepts the :meth:`dumps` options. Records end exactly as ``newline``
        says whatever mode the file was opened in: for a text file the bytes
        go to its underlying buffer, bypassing newline translation, so a
        plain ``open(path, "w")`` gives the same result on every platform.
        """
        data = self.dumps(**kwargs)
        if not isinstance(fp, io.TextIOBase):
            fp.write(data.encode("ascii"))
            return
        buffer = getattr(fp, "buffer", None)
        if buffer is None:
            fp.write(data)
            return
        fp.flush()
        buffer.write(data.encode(fp.encoding or "ascii"))

    def write(self, path: Any, *, encoding: str = "ascii", **kwargs: Any) -> None:
        """Write the document to ``path``. Accepts the :meth:`dumps` options."""
        with open(path, "w", encoding=encoding, newline="") as fp:
            fp.write(self.dumps(**kwargs))
