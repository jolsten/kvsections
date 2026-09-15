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
- `model.py`: `BaseSection`, `Section` (a `MutableMapping[str, str]`),
  `TextSection`, `convert_section`.
- `fields.py`: `Field[T]` descriptor, `Converter[T]`, `MISSING`.
- `errors.py`: `ParseWarning`, `ParseError`.
- `reader.py`: tolerant parser. `writer.py`: strict renderer.
- `document.py`: `Document` (a `MutableMapping[str, BaseSection]`),
  `SectionField`, schema registry and alias merging, `reorder`, I/O methods.
- `layout.py`: `wrap_records` and `reorder_records`, text-level and
  byte-preserving. `converters.py`: ready-made parse/format pairs.
- `__init__.py`: `loads`/`load`/`read`/`dumps`/`dump`/`write` are bound
  straight from `Document`; do not re-wrap them.
- `tests/`: one file per module, shared fixtures in `helpers.py`,
  `conftest.py` parametrizes `sample` over `tests/samples/*.txt` and
  `golden_sample` over `golden*.txt`.

## Design decisions (confirmed with the owner)

Do not reverse these without asking.

1. Values are always strings, exactly as in the file. Nothing is split on
   commas unless a typed field declares `list[T]`.
2. Section names and keys are upper-cased on insertion; lookups are
   case-insensitive.
3. Assigning `None` removes a key or a declared section.
4. The generic `Document` reads every section as pairs. Free text is a
   schema declaration: `SectionField(TextSection, "COMMENTS")`. There is no
   default list of free-text names.
5. The reader is maximally tolerant: every tolerated problem goes into
   `doc.warnings` with a line number, `strict=True` raises at the first.
   Duplicate sections merge, duplicate keys keep the last value, bare tokens
   get an empty value, undecodable bytes and BOMs are reported.
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
    directions; `%y` follows Python's 1969 pivot.
11. Reading a declared section the document lacks raises `AttributeError`,
    exactly like a missing typed key. Reading never mutates. Create with
    `doc.header = {}` or `doc.add(...)`.
12. Section order is not part of the format; `reorder` and `section_order`
    are opt-in and the writer never reorders.
13. Python 3.9 minimum, zero runtime dependencies, no pydantic/attrs, stdlib
    where it fits (`textwrap`). No CLI; the old entry point was removed on
    purpose.

## Conventions and pitfalls

- Sample files: any `tests/samples/*.txt` is picked up automatically and
  must parse, round-trip through the model, and survive the layout helpers.
  Files named `golden*` must also reproduce byte for byte from their detected
  layout. Samples keep their own line endings (`golden.txt` is CRLF).
- Source files are LF. When writing files from a script on Windows, open
  them with `newline="\n"`; a plain text-mode write converts to CRLF
  silently, and this has bitten the project before.
- Keep README examples runnable against `tests/samples/golden.txt`; they
  have been executed after every change so far.
- The README and the docstrings are the user documentation; update both
  when behaviour changes.
