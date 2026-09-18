"""Shared fixtures for the test suite: sample paths and the golden schema."""

from pathlib import Path

from kvsections import Document, Field, Section, SectionField, TextSection

SAMPLES = Path(__file__).resolve().parent / "samples"
GOLDEN = SAMPLES / "golden.txt"


def names(doc):
    """The section names of a document in order; documents iterate as pairs."""
    return [name for name, _ in doc]


# Everything golden.txt contains, in file order. Values stay strings, so
# leading zeros and comma-separated lists survive verbatim.
class CommentDocument(Document):
    """The generic document plus COMMENT and COMMENTS as free text."""

    comment = SectionField(TextSection)
    comments = SectionField(TextSection)


GOLDEN_DOCUMENT = CommentDocument(
    [
        Section(
            "HEADER",
            VERSION="1",
            FORMAT="TEXT",
            CREATED="20240101",
            REVISION="003",
            AUTHOR="EXAMPLE",
            OWNER="NOBODY",  # from a continuation record
        ),
        Section(
            "CONFIG",
            NAME="DEFAULT",
            MODE="NORMAL",
            LEVEL="2",
            ENABLED="YES",
            TIMEOUT="30",
            RETRIES="3",
            BUFFER="4096",
            VERBOSE="NO",
        ),
        Section(
            "SOURCE", TYPE="FILE", PATH="INPUT.DAT", ENCODING="ASCII", SIZE="001024"
        ),
        Section("TARGET", TYPE="STREAM", NAME="MAIN", RATE="12.5", LIMIT="100"),
        Section("OPTIONS", FLAGS="A,B,C,D", COMPRESS="NONE", CHECKSUM="CRC32"),
        Section("FILTER", MINIMUM="0.5", MAXIMUM="99.5", WINDOW="10"),
        Section(
            "SCHEDULE",
            START="080000",
            STOP="173000",
            INTERVAL="15",
            DAYS="MON,TUE,WED,THU,FRI",
            TIMEZONE="UTC",
        ),
        Section(
            "PARAMETERS",
            ALPHA="1.0",
            BETA="0.25",
            GAMMA="100",
            DELTA="0.001",
            EPSILON="5",
            ZETA="42",
            ETA="7",
            THETA="3.14",
        ),
        Section("OUTPUT", TYPE="REPORT", FORMAT="TABLE"),
        TextSection("COMMENTS", "This is a freeform comment section."),
    ]
)


class HeaderSection(Section):
    section_name = "HEADER"
    version = Field(int, required=True)
    revision = Field(int, format="{:03d}".format)
    author = Field()
    owner = Field(default="NOBODY")


class ScheduleSection(Section):
    section_name = "SCHEDULE"
    interval = Field(int)
    days = Field(list[str])
    counts = Field(list[int])


class SampleDocument(Document):
    header = SectionField(HeaderSection)
    schedule = SectionField(ScheduleSection)
    comments = SectionField(TextSection, aliases=("COMMENT",))
