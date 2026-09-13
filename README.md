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

- A file is a sequence of records, conventionally 80 columns wide, padded
  with spaces and terminated by CRLF.
- A record that starts in column 1 begins a section; its first token is the
  section name. A record that starts with whitespace continues the section
  above it.
- The rest of a record holds space-separated `KEY=VALUE` pairs. A pair never
  spans records. Values contain no spaces; lists are written as
  comma-separated values.
- Section names and keys are upper-case. Each section name appears once per
  file and each key once per section.
- `COMMENT` and `COMMENTS` sections hold free text instead of pairs.

## Usage

```python
import kvsections

doc = kvsections.read("tests/sample1.txt")

doc["CONFIG"]["BUFFER"]  # '4096'  (values are strings)
doc["SOURCE"]["SIZE"]  # '001024' (leading zeros are kept)
doc["OPTIONS"]["FLAGS"]  # 'A,B,C,D' (lists stay strings here)
list(doc)  # ['HEADER', 'CONFIG', 'SOURCE', ...]
doc["COMMENTS"].text  # free text

doc["CONFIG"]["BUFFER"] = "8192"
doc["OPTIONS"]["FLAGS"] = ["A", "B"]  # a list is joined with commas
kvsections.write(doc, "out.txt")
```

`Document` and `Section` are mutable mappings, so `in`, `get`, `items`,
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
inferred rather than assumed, so any indent width reads correctly. Pass
`strict=True` to raise `ParseError` at the first problem instead.

### Writing is strict

`dumps`/`write` raise `ValueError` for anything that would not read back:
lower-case or empty names and keys, whitespace or non-ASCII characters in
values, or a single pair too long for a record.

Layout options, all keyword-only:

| option    | default  | meaning                                                        |
|-----------|----------|----------------------------------------------------------------|
| `width`   | `80`     | padded record length; `None` disables padding and wrapping     |
| `margin`  | `1`      | columns left blank at the end of every record                  |
| `indent`  | `None`   | column where content starts; default is longest name plus one  |
| `newline` | `"\r\n"` | record terminator                                              |

Pairs that would cross `width - margin` wrap onto an indented continuation
record. Long free-text lines are word-wrapped. With the defaults the sample
file is written with an 11-column indent, because its longest section name
is `PARAMETERS`; `indent=12` reproduces the file byte for byte.

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


doc = ExampleDocument.read("tests/sample1.txt")
doc.header.version  # 1
doc.schedule.days  # ['MON', 'TUE', 'WED', 'THU', 'FRI']
doc["CONFIG"]["BUFFER"]  # sections you did not describe stay generic

new = ExampleDocument()
new.header.version = 7  # sections are created on first access
new.header.revision = 12  # written as REVISION=012
new.comments = "Built in code."
new.write("new.txt")
```

- `Field(key, type)` is shorthand for `parse=type, format=str`. Pass `parse`
  and `format` explicitly when the text form matters, or pass a `Converter`,
  which bundles both and can also be used inside `list[...]`.
- Reading a missing key raises `AttributeError` unless `default` is given.
  Assigning `None` removes the key.
- `Field(key, list[T])` splits the value on commas, converts each item with
  `T`, and joins on assignment; `parse` and `format` then apply per item.
  An empty value is an empty list. The list is a copy, so assign a new
  list rather than appending to the old one.
- Declaring a `SectionField` registers its class for that name, so the
  reader instantiates it and a generic `Section` added under that name is
  converted. Registrations are inherited by subclasses.
- `aliases` gives a section alternative spellings. With the declaration
  above, a file may say either `COMMENTS` or `COMMENT`: `doc.comments`,
  `doc["COMMENTS"]` and `doc["COMMENT"]` all find it, `list(doc)` reports
  the canonical name, and the section keeps the spelling it was read with
  so a rewrite preserves it. A file containing both spellings is treated as
  a duplicate and merged with a warning. Aliases can also be declared as a
  `section_aliases` table on the class; subclasses inherit and extend them.
  The generic `Document` has no aliases, so for it `COMMENT` and `COMMENTS`
  are two different sections.
- Override `free_text_sections` on a `Document` subclass to change which
  names are read as free text.

### Ready-made converters

`kvsections.converters` bundles parse/format pairs for encodings this
format tends to use. Each validates in both directions and raises
`ValueError` for text or values it cannot handle.

| converter | text | Python value |
|---|---|---|
| `YYMMDD`, `YYYYMMDD` | `240101`, `20240101` | `datetime.date` |
| `HHMMSS`, `HHMM` | `080000`, `0800` | `datetime.time` |
| `YYYYMMDDHHMMSS` | `20240101080000` | `datetime.datetime` |
| `date_format(fmt)`, `time_format(fmt)`, `datetime_format(fmt)` | any `strftime` pattern | as above |
| `zero_padded(width)` | `003` | `int` |
| `YES_NO`, `Y_N`, `ON_OFF`, `TRUE_FALSE`, `flag(true, false)` | `YES` | `bool` |
| `one_of("A", "B")` | `A` | `str`, restricted to the choices |
| `enum_by_value(E)`, `enum_by_name(E)` | the member's value or name | member of `E` |

A custom pair is one line: `Converter(parse, format)`.

## Development

```
uv run --group dev pytest
uv run --group dev ruff check
uv run --group dev ruff format --check
```
