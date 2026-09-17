# kvsections

[![CI](https://github.com/jolsten/kvsections/actions/workflows/ci.yml/badge.svg)](https://github.com/jolsten/kvsections/actions/workflows/ci.yml)

Read and write files made of named sections holding `KEY=VALUE` pairs.

```
HEADER      VERSION=1 FORMAT=TEXT CREATED=20240101 REVISION=003 AUTHOR=EXAMPLE
            OWNER=NOBODY
CONFIG      NAME=DEFAULT MODE=NORMAL LEVEL=2 ENABLED=YES TIMEOUT=30 RETRIES=3
            BUFFER=4096 VERBOSE=NO
SCHEDULE    START=080000 STOP=173000 INTERVAL=15 DAYS=MON,TUE,WED,THU,FRI
COMMENTS    Free text, which may run onto
            as many lines as it needs.
```

## The format

- A file is a sequence of records, conventionally 80 columns wide and padded
  with spaces. Any of CRLF, LF or CR terminates a record on input; the
  writer emits LF unless told otherwise.
- A record that starts in column 1 begins a section; its first token is the
  section name. A record that starts with whitespace continues the section
  above it.
- The rest of a record holds space-separated `KEY=VALUE` pairs. A pair never
  spans records. Values contain no spaces; lists are written as
  comma-separated values.
- Section names and keys are upper-case. Each section name appears once per
  file and each key once per section.
- A section may hold free text instead of pairs, conventionally `COMMENTS`;
  a schema declares which ones. The text starts at its first non-blank
  character: leading whitespace on the first line, blank lines at either
  end and trailing spaces are layout, not content, and are not preserved.

## Usage

```python
import kvsections
from kvsections import Document, SectionField, TextSection


class Doc(Document):
    comments = SectionField(TextSection)  # free text, not pairs


doc = Doc.document_read("tests/samples/golden.txt")

doc["CONFIG"]["BUFFER"]  # '4096'  (values are strings)
doc["SOURCE"]["SIZE"]  # '001024' (leading zeros are kept)
doc["OPTIONS"]["FLAGS"]  # 'A,B,C,D' (lists stay strings here)
[name for name, section in doc]  # ['HEADER', 'CONFIG', 'SOURCE', ...]
dict(doc["OUTPUT"])  # {'TYPE': 'REPORT', 'FORMAT': 'TABLE'}
doc["COMMENTS"].section_text  # 'This is a freeform comment section.'

doc["CONFIG"]["BUFFER"] = "8192"
doc["OPTIONS"]["FLAGS"] = ["A", "B"]  # a list is joined with commas
doc["CONFIG"]["VERBOSE"] = None  # assigning None removes a key
kvsections.write(doc, "out.txt")
```

`kvsections.read` does the same with the generic `Document`, which reads every
section, `COMMENTS` included, as key/value pairs; free text is something a
schema declares. `Document` and `Section` support `[]`, `in`, `len` and
`del`, and iterate as `(name, section)` and `(key, value)` pairs, so
`dict(section)` and `for key, value in section` work. They are deliberately
not mappings: on a section every attribute that does not start with
`section_` is a key, and on a document every attribute that does not start
with `document_` is a section (see [Typed documents](#typed-documents)).
Keys and section names are normalised to upper case on the way in, and
lookups are case-insensitive. Values are always strings, commas included;
splitting them into lists is the job of typed fields (below).
`loads`/`dumps` work on strings and `load`/`dump` on open files; a schema
class offers the same as `document_loads`, `document_read` and so on.

### Reading is tolerant

The reader never rejects a file. Anything it had to guess about is listed in
`doc.document_warnings` as `(lineno, message)` pairs:

```python
doc = kvsections.loads("header owner=nobody\nheader x=1")
for warning in doc.document_warnings:
    print(warning)
# line 1: section name 'header' is not upper-case; normalized
# line 1: key 'owner' is not upper-case; normalized
# line 2: section name 'header' is not upper-case; normalized
# line 2: duplicate section HEADER; merged into the earlier one
# line 2: key 'x' is not upper-case; normalized
```

Line length, padding and line endings are not checked, and the layout is
inferred rather than assumed, so any indent width reads correctly, and a
UTF-8 byte order mark is dropped with a warning, as is any character that
could not be written back, such as the replacement character an undecodable
byte becomes. Pass `strict=True` to raise `ParseError` at the first problem
instead.

### Writing is strict

`dumps`/`write` raise `ValueError` for anything that would not read back:
lower-case or empty names and keys, whitespace or non-ASCII characters in
values, or a section of the wrong kind for its name, such as pairs under
`COMMENT`. Record width is a convention rather than a limit: a pair or word
that cannot fit is written on a record of its own, longer than `width`.

Layout options, all keyword-only:

| option    | default  | meaning                                                        |
|-----------|----------|----------------------------------------------------------------|
| `width`   | `80`     | padded record length; `None` disables padding and wrapping     |
| `margin`  | `1`      | columns left blank at the end of every record                  |
| `indent`  | `None`   | column where content starts; default is longest name plus one  |
| `newline` | `"\n"`   | record terminator; pass `"\r\n"` for consumers that need CRLF   |

Pairs that would cross `width - margin` wrap onto an indented continuation
record. Long free-text lines are word-wrapped. With the defaults the sample
file is written with an 11-column indent, because its longest section name
is `PARAMETERS`; `indent=12, newline="\r\n"` reproduces the file byte for
byte.

`dump` takes a file opened in text or binary mode. A text file may be opened
with a plain `open(path, "w")`: the records are written through the file's
underlying buffer, so newline translation never alters the terminators.

### Fixing layout without parsing

`wrap_records` takes the text of a file whose records are too long and
re-flows only those records onto continuation records, leaving every other
byte as it was. It does not parse, so names, keys, values, spelling and
order are untouched, and it never raises for content. Pass `pad=True` to
also pad every record to `width`.

```python
from kvsections import wrap_records

text = path.read_bytes().decode("ascii")
path.write_bytes(wrap_records(text, width=80, pad=True).encode("ascii"))
```

`reorder_records` moves whole sections into a prescribed order the same way:
a block starts at each header record, the order has the same form as for
`Document.document_reorder` (see below), and every byte inside a block is
kept. Pass a schema class as `document_type` to resolve aliases.

```python
from kvsections import reorder_records

moved = reorder_records(
    text, ["HEADER", ..., "COMMENTS"], document_type=ExampleDocument
)
```

## Typed documents

For a known file layout, describe the sections you care about and get typed
attributes instead of strings. The attribute names the key or the section:

```python
from kvsections import Document, Section, TextSection, Field, SectionField
from kvsections.converters import HHMMSS, YYYYMMDD, zero_padded


class HeaderSection(Section):
    section_name = "HEADER"
    version = Field(int)
    created = Field(YYYYMMDD)  # datetime.date
    revision = Field(zero_padded(3))  # keeps the leading zeros
    author = Field()
    owner = Field(default="NOBODY")


class ScheduleSection(Section):
    section_name = "SCHEDULE"
    interval = Field(int)
    start = Field(HHMMSS)  # datetime.time
    days = Field(list[str])


class ExampleDocument(Document):
    header = SectionField(HeaderSection)
    schedule = SectionField(ScheduleSection)
    comments = SectionField(TextSection, aliases=("COMMENT",))


doc = ExampleDocument.document_read("tests/samples/golden.txt")
doc.header.version  # 1
doc.schedule.days  # ['MON', 'TUE', 'WED', 'THU', 'FRI']
doc["CONFIG"]["BUFFER"]  # sections you did not describe stay generic

new = ExampleDocument()
new.header = {}  # sections are created explicitly; reading never creates
new.header.version = 7
new.header.revision = 12  # written as REVISION=012
new.schedule = ScheduleSection(interval=15, days=["MON", "FRI"])
new.comments = "Built in code."
new.document_write("new.txt")
```

- The attribute names the key: `version = Field(int)` reads and writes
  `VERSION`, and `header = SectionField(HeaderSection)` is the section
  `HEADER`. One trailing underscore is dropped, so `class_ = Field()` is the
  key `CLASS`. Only a name that is not a Python identifier needs spelling
  out, as in `max_size = Field(int, key="MAX-SIZE")` or
  `SectionField(TextSection, name="MY-NOTES")`. A section class's own
  `section_name` must agree with the attribute, or with the explicit name.
- Nothing is reserved except two prefixes. Everything the library puts on a
  section starts with `section_` (`section_name`, `section_fields`,
  `section_text`) and everything on a document starts with `document_`
  (`document_warnings`, `document_read`, `document_dumps`,
  `document_reorder`, ...). Every other attribute of your subclass is a key
  or a section, `name`, `items` and `values` included. Declaring one under
  a prefixed name, under a name a base class already uses for something
  else, or on the wrong kind of class raises `TypeError` when the class is
  created. One quirk is Python's rather than the library's: `dict()` treats
  any object with a `keys` attribute as a mapping, so a section or document
  that declares `keys` converts with `dict(iter(x))`.
- Constructor names are positional-only, so every keyword argument is a
  key: `Section("HEADER", VERSION="1")` stores `VERSION`, and on a typed
  section `HeaderSection(version=1, name="X")` formats `version` through
  its field and stores `NAME=X` as it is.
- `Field(type)` is shorthand for `parse=type, format=str`. Pass `parse` and
  `format` explicitly when the text form matters, or pass a `Converter`,
  which bundles both and can also be used inside `list[...]`.
- Reading a missing key raises `AttributeError` unless `default` is given,
  and so does reading a declared section the document lacks. Assigning
  `None` removes the key or the section.
- `Field(list[T])` splits the value on commas, converts each item with `T`,
  and joins on assignment; `parse` and `format` then apply per item. An
  empty value is an empty list. The list is a copy, so assign a new list
  rather than appending to the old one.
- Declaring a `SectionField` registers its class for that name, so the
  reader instantiates it and a generic `Section` added under that name is
  converted. Registrations are inherited by subclasses, including through
  multiple inheritance of document classes; a `SectionField` on a plain
  mixin is an error, because it would never be registered.
- `aliases` gives a section alternative spellings. With the declaration
  above, a file may say either `COMMENTS` or `COMMENT`: `doc.comments`,
  `doc["COMMENTS"]` and `doc["COMMENT"]` all find it, iteration reports
  the canonical name, and the section keeps the spelling it was read with
  so a rewrite preserves it. A file containing both spellings is treated as
  a duplicate and merged with a warning. Aliases can also be declared as a
  `document_aliases` table on the class; subclasses inherit and extend them.
  The generic `Document` has no aliases, so for it `COMMENT` and `COMMENTS`
  are two different sections.
- The generic `Document` reads every section as pairs. A schema declares
  free-text sections with `SectionField(TextSection)`, as `ExampleDocument`
  does above.

### Section order

The format itself imposes no order, but some files expect one.
`document_reorder` puts the sections into a prescribed order in place. Names
are listed in the wanted order, `...` stands for every section not named
(kept in their current relative order), and names after `...` go last:

```python
doc = kvsections.read("tests/samples/golden.txt")
doc.document_reorder(["OUTPUT", "HEADER", ..., "COMMENTS"])
[name for name, section in doc]  # ['OUTPUT', 'HEADER', 'CONFIG', ..., 'COMMENTS']
```

Names absent from the document are ignored, aliases resolve, and without
`...` the unnamed sections follow the named ones. A schema can declare the
order once as `document_order`, after which `doc.document_reorder()` needs
no argument:

```python
class ExampleDocument(Document):
    document_order = ["HEADER", "SCHEDULE", ..., "COMMENTS"]
```

`document_reorder` works on a parsed document, so a read, reorder, write
sequence normalizes the layout as well. To move sections and change nothing
else, use `reorder_records` from the layout helpers above.

### Ready-made converters

`kvsections.converters` bundles parse/format pairs for encodings this
format tends to use. Each validates in both directions and raises
`ValueError` for text or values it cannot handle.

| converter | text | Python value |
|---|---|---|
| `YYMMDD`, `YYYYMMDD` | `240101`, `20240101` | `datetime.date`; `%y` follows Python's rule, 69 to 99 being 19xx |
| `HHMMSS`, `HHMM` | `080000`, `0800` | `datetime.time` |
| `YYYYMMDDHHMMSS` | `20240101080000` | `datetime.datetime` |
| `date_format(fmt)`, `time_format(fmt)`, `datetime_format(fmt)` | any `strftime` pattern | as above |
| `zero_padded(width)` | `003` | non-negative `int`; digits only |
| `YES_NO`, `Y_N`, `ON_OFF`, `TRUE_FALSE`, `flag(true, false)` | `YES` | `bool`; writing also accepts the two words |
| `one_of("A", "B")` | `A` | `str`, restricted to the choices |
| `enum_by_value(E)`, `enum_by_name(E)` | the member's value or name | member of `E` |

The date and time converters also refuse values that would not read back,
such as a year outside 1969 to 2068 for `YYMMDD` or a time with
microseconds for `HHMMSS`.

A custom pair is one line: `Converter(parse, format)`.

## Development

```
uv run --group dev pytest
uv run --group dev pytest --cov      # branch coverage; fails below 95%
uv run --group dev ruff check
uv run --group dev ruff format --check
uv run --group dev mypy               # strict type checking
```

Tests are split by module under `tests/`, with shared fixtures in
`tests/helpers.py`. Every `tests/samples/*.txt` file is picked up
automatically and must parse without raising, round-trip through the model,
and survive the layout helpers unchanged in content; a sample whose name
starts with `golden` must also be reproduced byte for byte from its detected
layout. Drop a file into the directory to add it to the suite.

CI runs the same four commands on every push and pull request, across
Linux, Windows and macOS on Python 3.9 to 3.13, and builds the wheel.

### Releasing

Releases publish to PyPI from GitHub Actions through trusted publishing, so
no API token is stored. The version is derived from the git tag by
hatch-vcs, so nothing in the repository needs bumping. To cut one:

```
git tag v0.2.0 && git push --tags
```

Untagged commits build as development versions such as `0.2.1.dev3+g1a2b3c4`.
