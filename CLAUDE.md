# kvsections

A zero-dependency Python 3.9+ library that reads and writes a fixed-width text
format: records of (conventionally) 80 columns, a section name in column 1,
indented continuation records, and `KEY=VALUE` pairs or free text after the
name. `tests/samples/golden.txt` is the reference file. MIT licensed.

## Commands

Run all four before calling a change done. Coverage fails below 95% and mypy
runs in strict mode; ruff enforces LF line endings on Python files.

```
uv run --group dev pytest --cov
uv run --group dev ruff check
uv run --group dev ruff format --check
uv run --group dev mypy
```

## Layout

- `src/kvsections/records.py`: `Record.from_line` (header vs continuation vs
  blank), `split_records`, the `TOKEN_CHARS`/`TEXT_CHARS` alphabets, `pack`
  (a `textwrap` wrapper), `plan_order`. Every other module builds on these so
  the rules exist once.
- `model.py`: `BaseSection`, `Section` (subscriptable, iterates `(key, value)`
  pairs, deliberately not a `Mapping`; `section_get` is the lenient lookup),
  `TextSection`, `convert_section`.
  `Section.__init_subclass__` and `TextSection.__init_subclass__` validate
  the descriptors declared on subclasses.
- `fields.py`: `Declaration` (the descriptor base that records its attribute
  in `__set_name__`), `Field[T]`, `Converter[T]`, `name_from_attr` and
  `check_declaration` (the reserved-name rules, shared with `SectionField`).
- `errors.py`: `Problem` (the enum of tolerated problems), `ParseWarning`,
  `ParseError`.
- `reader.py`: tolerant parser. `writer.py`: strict renderer.
- `document.py`: `Document` (subscriptable, iterates `(name, section)` pairs,
  not a `Mapping`; `document_get(name, key=None)` is the lenient lookup),
  `SectionField`, schema registry and alias merging, `document_reorder`, the
  I/O methods; every library name on it starts with `document_`.
- `layout.py`: `wrap_records` and `reorder_records`, text-level and
  byte-preserving. `converters.py`: ready-made parse/format pairs.
- `__init__.py`: `loads`/`load`/`read`/`dumps`/`dump`/`write` are bound
  straight from `Document.document_loads` and friends; do not re-wrap them.
- `tests/`: one file per module, shared fixtures in `helpers.py` (including
  `names(doc)`, since documents iterate pairs), `conftest.py` parametrizes
  `sample` over `tests/samples/*.txt` and `golden_sample` over `golden*.txt`.

## Design decisions (confirmed with the owner)

Do not reverse these without asking.

1. Values are always strings, exactly as in the file. Nothing is split on
   commas unless a typed field declares `list[T]`.
2. Section names and keys are upper-cased on insertion; lookups are
   case-insensitive.
3. Assigning `None` removes a key or a declared section.
4. The generic `Document` reads every section as pairs. Free text is a
   schema declaration: `comments = SectionField(TextSection)`. There is no
   default list of free-text names.
5. The reader is maximally tolerant: every tolerated problem goes into
   `doc.document_warnings` with a line number, `strict=True` raises at the
   first. Duplicate sections merge, duplicate keys keep the last value, bare
   tokens get an empty value, undecodable bytes and BOMs are reported.
   Warnings are structured: `ParseWarning(lineno, kind, subject, message)`
   with `kind` a `Problem` member and `subject` the section name (canonical),
   key or token concerned, and `ParseError` carries the same fields. Filter
   on `kind`, never by matching the message. Repeated headers are counted
   from `DUPLICATE_SECTION` warnings (one per merge, so appearances minus
   one, aliases folded); there is deliberately no separate duplicates
   record, so the warnings stay the single record of tolerance.
6. The writer is strict about content (character set, upper case, section
   kind) but record width is a convention: over-long pairs or words go on a
   record of their own and are never refused.
7. The writer normalizes layout (indent = longest name + 1, single spaces,
   padding to 80 with a one-column margin) and never preserves the input's
   layout or order. Byte-preserving edits belong to `wrap_records` and
   `reorder_records`, which never parse.
8. Line endings: read CRLF, LF or CR; write LF unless `newline` says
   otherwise. `dump` writes through a text handle's buffer so platform
   newline translation cannot interfere.
9. Aliases exist only in schemas, never on the generic `Document`. The
   document is keyed by canonical name; a section keeps the spelling it was
   read with; equality is spelling-sensitive. A class's own declarations
   override inherited ones (`_merge_schema`).
10. Typed fields are lazy views over the raw strings: parse on read, format
    on assignment, nothing validated at load time. Converters validate both
    directions; `%y` follows Python's 1969 pivot. The overloads make the
    typing honest: `Field(int)` reads as `int | None`, `required=True` or a
    non-None `default` as `int`.
11. A typed key the section lacks reads as `None`, or as the field's
    `default`, mirroring decision 3 so that an absent key round-trips as
    `None`. `Field(..., required=True)` raises `AttributeError` instead and
    cannot have a default; the reader stays tolerant, required-ness is the
    schema author's call. `del section.field` on an absent key is a no-op,
    like assigning `None`. Reading a declared section the document lacks
    always raises `AttributeError`, because `None` would turn
    `doc.header.x = 1` into an obscure `NoneType` error. Reading never
    mutates. Create with `doc.header = {}` or `doc.document_add(...)`;
    section defaults do not exist, on purpose.
12. Section order is not part of the format; `document_reorder` and
    `document_order` are opt-in and the writer never reorders.
13. Python 3.9 minimum, zero runtime dependencies, no pydantic/attrs, stdlib
    where it fits (`textwrap`). No CLI; the old entry point was removed on
    purpose.
14. The attribute names the key or section. `version = Field(int)` is the key
    VERSION and `header = SectionField(HeaderSection)` the section HEADER;
    one trailing underscore is dropped (`class_` is CLASS). `key=` and
    `name=` are keyword-only and exist for names that are not identifiers,
    never as a workaround for a name the library took. A section class's
    `section_name` must agree with the attribute unless `name=` is explicit.
    The owner considers an attribute that silently differs from its key a
    footgun.
15. The library's own names live in prefixed namespaces, pydantic's
    `model_*` pattern: `section_*` on `Section`/`TextSection`
    (`section_name`, `section_fields`, `section_text`) and `document_*` on
    `Document` (`document_sections`, `document_warnings`, `document_add`,
    `document_reorder`, `document_loads/load/read/dumps/dump/write`,
    `document_canonical_name`, `document_section_type`,
    `document_new_section`, and the class config `document_section_types`,
    `document_aliases`, `document_order`). Every other attribute of a
    subclass is the user's. Never add an unprefixed public name to either
    class, and never make them mappings again: the mixin's method names are
    unprefixed and mypy rejects a field that overrides one. The owner's
    files never use underscores in keys or section names, which is what
    makes the prefixes collision-free.
16. Bad declarations fail when the class is created, as a plain `TypeError`
    raised from `__init_subclass__`, never from `__set_name__` (Python 3.11
    and earlier wrap those in `RuntimeError`). Rejected: a prefixed
    attribute, an attribute a base class defines as something other than
    the same descriptor kind, a `Field` on a `TextSection` or `Document`, a
    `SectionField` on a section class or on a plain mixin, and a
    `SectionField` whose attribute disagrees with the class's `section_name`.
    Redeclaring an inherited `Field` and `Field` mixins are allowed.
17. Constructor parameters `name`, `fields`, `text` and `sections` are
    positional-only, so every keyword argument to a section is a key
    (`HeaderSection(name="X")` stores NAME).
18. Lenient raw lookups are explicit: `section.section_get(key, *, default=None)`,
    `doc.document_get(name, key=None, *, default=None)` and the presence test
    `doc.document_has(name, key=None)`. With a key, `document_get` returns
    the default when the section is absent, holds free text, or lacks the
    key, so no `None` ever sits in the middle of a chain; `document_has` is
    false in the same cases and true for an empty value. `default` is
    keyword-only. All of them are raw: no converter runs and no field default
    applies, those belong to typed attributes. There is no `section_has`,
    since `key in section` already is that test. The subscript stays strict
    at both levels, and nothing else from the old mapping interface comes
    back without a need.

## CI and releases

- `.github/workflows/ci.yml` runs the four commands above on every push and
  pull request: lint and mypy on Ubuntu, pytest across Ubuntu, Windows and
  macOS on Python 3.9 to 3.13, plus a wheel build and import. It uses
  `uv sync --locked`, so commit `uv.lock` whenever `pyproject.toml` changes.
- `.github/workflows/release.yml` publishes to PyPI on a `v*` tag through
  trusted publishing (no token). Release = `git tag vX.Y.Z && git push --tags`.
- The version is derived from git tags by hatch-vcs (hatchling backend);
  nothing in the repo states it, `__version__` reads installed metadata, and
  `uv version` does not apply. Checkouts that build need the tags
  (`fetch-depth: 0` in workflows).
- `.gitattributes` stores source as LF and `tests/samples/**` verbatim.
  The owner's git uses `core.autocrlf=input`, so without that rule CRLF
  samples would be committed as LF and the byte-exact tests would fail on
  a fresh clone.

## Conventions and pitfalls

- Sample files: any `tests/samples/*.txt` is picked up automatically and
  must parse, round-trip through the model, and survive the layout helpers.
  Files named `golden*` must also reproduce byte for byte from their detected
  layout. Samples keep their own line endings (`golden.txt` is CRLF).
- Source files are LF. When writing files from a script on Windows, open
  them with `newline="\n"`; a plain text-mode write converts to CRLF
  silently, and this has bitten the project before.
- `dict(x)` calls `x.keys()` when the attribute exists, so a section or
  document declaring a field or section called `keys` converts with
  `dict(iter(x))`. This is CPython's rule and is documented in the README.
- Keep README examples runnable against `tests/samples/golden.txt`; they
  have been executed after every change so far.
- The README and the docstrings are the user documentation; update both
  when behaviour changes.
