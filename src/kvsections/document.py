"""The document: an ordered collection of uniquely named sections."""

from __future__ import annotations

import io
from collections.abc import Iterable, Iterator, MutableMapping
from typing import (
    IO,
    Any,
    ClassVar,
    TypeVar,
    Union,
)

from .model import (
    AnySection,
    ParseWarning,
    Section,
    TextSection,
    _normalize_key,
    convert_section,
)
from .reader import parse
from .writer import format_document

_D = TypeVar("_D", bound="Document")
_S = TypeVar("_S", bound=Union[Section, TextSection])

__all__ = ["Document", "SectionField"]


class SectionField:
    """Descriptor exposing one section of a :class:`Document` as an attribute.

    Declaring one on a ``Document`` subclass also registers ``section_type``
    for that name, so the reader instantiates it for matching sections, and
    registers each of ``aliases`` as another spelling of the same section.

    Reading the attribute returns the section, creating an empty one if the
    document has none. Assigning a section replaces it; assigning a mapping
    (or a string, for text sections) builds a new section from it. Assigning
    ``None`` removes it.
    """

    def __init__(
        self,
        section_type: type[AnySection],
        name: str | None = None,
        *,
        aliases: Iterable[str] = (),
    ):
        if not isinstance(section_type, type) or not issubclass(
            section_type, (Section, TextSection)
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
            section = self.section_type(self.name)
        elif isinstance(section, self.section_type):
            return section
        return doc.add(section)

    def __set__(self, doc: Document, value: Any) -> None:
        if value is None:
            doc.sections.pop(self.name, None)
            return
        if isinstance(value, (Section, TextSection)):
            if type(doc).canonical_name(value.name) != self.name:
                raise ValueError(f"expected section {self.name}, got {value.name}")
            doc.add(value)
        else:
            doc.add(self.section_type(self.name, value))

    def __delete__(self, doc: Document) -> None:
        del doc.sections[self.name]

    def __repr__(self) -> str:
        extra = f", aliases={self.aliases!r}" if self.aliases else ""
        cls_name = self.section_type.__name__
        return f"{type(self).__name__}({cls_name}, {self.name!r}{extra})"


class Document(MutableMapping):
    """An ordered mapping of section name to section.

    Subclass it to describe a specific file: declare :class:`SectionField`
    attributes for the sections you care about, give alternative spellings
    with ``aliases`` (or a ``section_aliases`` table), and optionally override
    ``free_text_sections`` to change which names are read as free text.

    Sections are keyed by canonical name, so one read under an alias is found
    under either spelling. The section itself keeps the spelling it was read
    with, and the writer preserves it.
    """

    #: Names read as :class:`TextSection` when no section type is registered.
    free_text_sections: ClassVar[frozenset[str]] = frozenset({"COMMENT", "COMMENTS"})

    #: Section classes to instantiate by name, collected from SectionField
    #: declarations on subclasses.
    section_types: ClassVar[dict[str, type[AnySection]]] = {}

    #: Alternative spellings mapped to their canonical name. Empty on the
    #: generic document; schemas declare their own, and subclasses inherit
    #: and extend them.
    section_aliases: ClassVar[dict[str, str]] = {}

    def __init_subclass__(cls, **kwargs: Any) -> None:
        super().__init_subclass__(**kwargs)
        registry = dict(cls.section_types)
        aliases: dict[str, str] = {}
        for base in reversed(cls.__mro__[1:]):
            aliases.update(getattr(base, "section_aliases", {}))
        for alias, canonical in cls.__dict__.get("section_aliases", {}).items():
            aliases[_normalize_key(alias)] = _normalize_key(canonical)
        for value in cls.__dict__.values():
            if isinstance(value, SectionField):
                registry[value.name] = value.section_type
                for alias in value.aliases:
                    if alias in aliases and aliases[alias] != value.name:
                        raise TypeError(
                            f"{alias} is already an alias of {aliases[alias]}"
                        )
                    aliases[alias] = value.name
        for alias, canonical in aliases.items():
            if alias in registry:
                raise TypeError(
                    f"{alias} is registered as a section and as an alias of {canonical}"
                )
            if canonical in aliases:
                raise TypeError(
                    f"{canonical} is an alias itself, so {alias} cannot map to it"
                )
        cls.section_types = registry
        cls.section_aliases = aliases
        cls.free_text_sections = frozenset(
            _normalize_key(name) for name in cls.free_text_sections
        )

    def __init__(self, sections: Iterable[AnySection] = ()):
        self.sections: dict[str, AnySection] = {}
        #: Problems the reader tolerated, in file order. Empty for documents
        #: built in code.
        self.warnings: list[ParseWarning] = []
        for section in sections:
            self.add(section)

    # -- section types -----------------------------------------------------

    @classmethod
    def canonical_name(cls, name: str) -> str:
        """The name a section called ``name`` is stored under."""
        name = _normalize_key(name)
        return cls.section_aliases.get(name, name)

    @classmethod
    def section_type_for(cls, name: str) -> type[AnySection]:
        """The class used for a section called ``name``."""
        name = cls.canonical_name(name)
        registered = cls.section_types.get(name)
        if registered is not None:
            return registered
        return TextSection if name in cls.free_text_sections else Section

    @classmethod
    def new_section(cls, name: str) -> AnySection:
        """An empty section called ``name`` of the appropriate class."""
        return cls.section_type_for(name)(_normalize_key(name))

    def add(self, section: _S) -> _S:
        """Store ``section`` under its canonical name, replacing any existing one.

        If a different class is registered for the name the section is
        converted to it; the stored (possibly converted) section is returned.
        """
        if not isinstance(section, (Section, TextSection)):
            raise TypeError(f"{section!r} is not a Section or TextSection")
        key = self.canonical_name(section.name)
        target = self.section_types.get(key)
        if target is not None:
            section = convert_section(section, target)
        self.sections[key] = section
        return section

    # -- MutableMapping ----------------------------------------------------

    def __getitem__(self, name: str) -> AnySection:
        return self.sections[self.canonical_name(name)]

    def __setitem__(self, name: str, section: AnySection) -> None:
        key = self.canonical_name(name)
        if not isinstance(section, (Section, TextSection)):
            raise TypeError(f"{section!r} is not a Section or TextSection")
        if self.canonical_name(section.name) != key:
            raise ValueError(
                f"cannot store section {section.name} under the name {name}"
            )
        self.add(section)

    def __delitem__(self, name: str) -> None:
        del self.sections[self.canonical_name(name)]

    def __iter__(self) -> Iterator[str]:
        return iter(self.sections)

    def __len__(self) -> int:
        return len(self.sections)

    def __contains__(self, name: object) -> bool:
        return isinstance(name, str) and self.canonical_name(name) in self.sections

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
        """Parse ``text``. With ``strict`` the first problem raises ParseError."""
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
        """Parse the contents of an open text or binary file."""
        data = fp.read()
        if isinstance(data, bytes):
            data = data.decode(encoding, errors)
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
        """Parse the file at ``path``."""
        with open(path, encoding=encoding, errors=errors, newline="") as fp:
            return cls.loads(fp.read(), strict=strict)

    # -- writing -----------------------------------------------------------

    def dumps(
        self,
        *,
        width: int | None = 80,
        margin: int = 1,
        indent: int | None = None,
        newline: str = "\r\n",
    ) -> str:
        """Render the document as text. See :func:`kvsections.dumps`."""
        return format_document(
            self, width=width, margin=margin, indent=indent, newline=newline
        )

    def dump(self, fp: IO[Any], **kwargs: Any) -> None:
        """Write the document to an open text or binary file."""
        data = self.dumps(**kwargs)
        if isinstance(fp, (io.RawIOBase, io.BufferedIOBase)):
            fp.write(data.encode("ascii"))
        else:
            fp.write(data)

    def write(self, path: Any, *, encoding: str = "ascii", **kwargs: Any) -> None:
        """Write the document to the file at ``path``."""
        with open(path, "w", encoding=encoding, newline="") as fp:
            fp.write(self.dumps(**kwargs))
