# kvsections

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
    comments = SectionField(TextSection, "COMMENTS")  # free text, not pairs


doc = Doc.read("tests/samples/golden.txt")

doc["CONFIG"]["BUFFER"]  # '4096'  (values are strings)
doc["SOURCE"]["SIZE"]  # '001024' (leading zeros are kept)
doc["OPTIONS"]["FLAGS"]  # 'A,B,C,D' (lists stay strings here)
list(doc)  # ['HEADER', 'CONFIG', 'SOURCE', ...]
doc["COMMENTS"].text  # 'This is a freeform comment section.'

doc["CONFIG"]["BUFFER"] = "8192"
doc["OPTIONS"]["FLAGS"] = ["A", "B"]  # a list is joined with commas
doc["CONFIG"]["VERBOSE"] = None  # assigning None removes a key
kvsections.write(doc, "out.txt")
```

`kvsections.read` does the same with the generic `Document`, which reads every
section, `COMMENTS` included, as key/value pairs; free text is something a
schema declares. `Document` and `Section` are mutable mappings, so `in`, `get`, `items`,
`del` and friends all work. Keys and section names are normalised to upper
case on the way in, and lookups are case-insensitive. Values are always
strings, commas included; splitting them into lists is the job of typed
fields (below). `loads`/`dumps` work on strings and `load`/`dump` on open
files.

### Reading is tolerant

The reader never rejects a file. Anything it had to guess about is listed in
`doc.warnings` as `(lineno, message)` pairs:

```python
doc = kvsections.loads("header owner=nobody\nheader x=1")
for warning in doc.warnings:
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

text = path.read_text(newline="")
path.write_text(wrap_records(text, width=80, pad=True), newline="")
```

`reorder_records` moves whole sections into a prescribed order the same way:
a block starts at each header record, the order has the same form as for
`Document.reorder` (see below), and every byte inside a block is kept. Pass
a schema class as `document_type` to resolve aliases.

```python
from kvsections import reorder_records

moved = reorder_records(
    text, ["HEADER", ..., "COMMENTS"], document_type=ExampleDocument
)
```

## Typed documents

For a known file layout, describe the sections you care about and get typed
attributes instead of strings:

```python
from kvsections import Document, Section, TextSection, Field, SectionField
from kvsections.converters import HHMMSS, YYYYMMDD, zero_padded


class HeaderSection(Section):
    section_name = "HEADER"
    version = Field("VERSION", int)
    created = Field("CREATED", YYYYMMDD)  # datetime.date
    revision = Field("REVISION", zero_padded(3))  # keeps the leading zeros
    author = Field("AUTHOR")
    owner = Field("OWNER", default="NOBODY")


class ScheduleSection(Section):
    section_name = "SCHEDULE"
    interval = Field("INTERVAL", int)
    start = Field("START", HHMMSS)  # datetime.time
    days = Field("DAYS", list[str])


class ExampleDocument(Document):
    header = SectionField(HeaderSection)
    schedule = SectionField(ScheduleSection)
    comments = SectionField(TextSection, "COMMENTS", aliases=("COMMENT",))


doc = ExampleDocument.read("tests/samples/golden.txt")
doc.header.version  # 1
doc.schedule.days  # ['MON', 'TUE', 'WED', 'THU', 'FRI']
doc["CONFIG"]["BUFFER"]  # sections you did not describe stay generic

new = ExampleDocument()
new.header = {}  # sections are created explicitly; reading never creates
new.header.version = 7
new.header.revision = 12  # written as REVISION=012
new.comments = "Built in code."
new.write("new.txt")
```

- `Field(key, type)` is shorthand for `parse=type, format=str`. Pass `parse`
  and `format` explicitly when the text form matters, or pass a `Converter`,
  which bundles both and can also be used inside `list[...]`.
- Reading a missing key raises `AttributeError` unless `default` is given,
  and so does reading a declared section the document lacks. Assigning
  `None` removes the key or the section.
- `Field(key, list[T])` splits the value on commas, converts each item with
  `T`, and joins on assignment; `parse` and `format` then apply per item.
  An empty value is an empty list. The list is a copy, so assign a new
  list rather than appending to the old one.
- Declaring a `SectionField` registers its class for that name, so the
  reader instantiates it and a generic `Section` added under that name is
  converted. Registrations are inherited by subclasses, including through
  multiple inheritance.
- `aliases` gives a section alternative spellings. With the declaration
  above, a file may say either `COMMENTS` or `COMMENT`: `doc.comments`,
  `doc["COMMENTS"]` and `doc["COMMENT"]` all find it, `list(doc)` reports
  the canonical name, and the section keeps the spelling it was read with
  so a rewrite preserves it. A file containing both spellings is treated as
  a duplicate and merged with a warning. Aliases can also be declared as a
  `section_aliases` table on the class; subclasses inherit and extend them.
  The generic `Document` has no aliases, so for it `COMMENT` and `COMMENTS`
  are two different sections.
- The generic `Document` reads every section as pairs. A schema declares
  free-text sections with `SectionField(TextSection, "COMMENTS")`, as
  `ExampleDocument` does above.

### Section order

The format itself imposes no order, but some files expect one. `reorder` puts
the sections into a prescribed order in place. Names are listed in the wanted
order, `...` stands for every section not named (kept in their current
relative order), and names after `...` go last:

```python
doc = kvsections.read("tests/samples/golden.txt")
doc.reorder(["OUTPUT", "HEADER", ..., "COMMENTS"])
list(doc)  # ['OUTPUT', 'HEADER', 'CONFIG', 'SOURCE', ..., 'COMMENTS']
```

Names absent from the document are ignored, aliases resolve, and without
`...` the unnamed sections follow the named ones. A schema can declare the
order once as `section_order`, after which `doc.reorder()` needs no argument:

```python
class ExampleDocument(Document):
    section_order = ["HEADER", "SCHEDULE", ..., "COMMENTS"]
```

`reorder` works on a parsed document, so a read, reorder, write sequence
normalizes the layout as well. To move sections and change nothing else,
use `reorder_records` from the layout helpers above.

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
