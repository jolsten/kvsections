"""Ready-made :class:`Converter` pairs for common value encodings.

Pass one as the type of a :class:`~kvsections.Field`::

    from kvsections import Field, Section
    from kvsections.converters import HHMMSS, YYYYMMDD, zero_padded

    class HeaderSection(Section):
        section_name = "HEADER"
        created = Field("CREATED", YYYYMMDD)      # datetime.date
        start = Field("START", HHMMSS)            # datetime.time
        revision = Field("REVISION", zero_padded(3))

Every converter validates on both sides: a value the text does not fit
raises ``ValueError`` when read, and a value that cannot be written raises
``ValueError`` when assigned.
"""

from __future__ import annotations

from datetime import date, datetime, time
from enum import Enum
from typing import Any

from .model import Converter

__all__ = [
    "date_format",
    "time_format",
    "datetime_format",
    "YYMMDD",
    "YYYYMMDD",
    "HHMMSS",
    "HHMM",
    "YYYYMMDDHHMMSS",
    "zero_padded",
    "flag",
    "YES_NO",
    "Y_N",
    "ON_OFF",
    "TRUE_FALSE",
    "one_of",
    "enum_by_value",
    "enum_by_name",
]


# -- dates and times ---------------------------------------------------------


def date_format(fmt: str, name: str | None = None) -> Converter:
    """Dates written with a ``strftime`` pattern, e.g. ``date_format("%y%m%d")``."""

    def parse(text: str) -> date:
        return datetime.strptime(text, fmt).date()

    def format(value: date) -> str:
        return value.strftime(fmt)

    return Converter(parse, format, name or f"date_format({fmt!r})")


def time_format(fmt: str, name: str | None = None) -> Converter:
    """Times of day written with a ``strftime`` pattern, e.g. ``"%H%M%S"``."""

    def parse(text: str) -> time:
        return datetime.strptime(text, fmt).time()

    def format(value: time) -> str:
        return value.strftime(fmt)

    return Converter(parse, format, name or f"time_format({fmt!r})")


def datetime_format(fmt: str, name: str | None = None) -> Converter:
    """Timestamps written with a ``strftime`` pattern, e.g. ``"%Y%m%d%H%M%S"``."""

    def parse(text: str) -> datetime:
        return datetime.strptime(text, fmt)

    def format(value: datetime) -> str:
        return value.strftime(fmt)

    return Converter(parse, format, name or f"datetime_format({fmt!r})")


#: Two-digit year, e.g. ``240101`` is 2024-01-01 (``strptime`` maps 00-68 to
#: 2000-2068 and 69-99 to 1969-1999).
YYMMDD = date_format("%y%m%d", "YYMMDD")
#: Four-digit year, e.g. ``20240101``.
YYYYMMDD = date_format("%Y%m%d", "YYYYMMDD")
#: Time of day to the second, e.g. ``080000`` is 08:00:00.
HHMMSS = time_format("%H%M%S", "HHMMSS")
#: Time of day to the minute, e.g. ``1730``.
HHMM = time_format("%H%M", "HHMM")
#: Full timestamp, e.g. ``20240101080000``.
YYYYMMDDHHMMSS = datetime_format("%Y%m%d%H%M%S", "YYYYMMDDHHMMSS")


# -- numbers -----------------------------------------------------------------


def zero_padded(width: int) -> Converter:
    """Integers written with leading zeros to exactly ``width`` digits, e.g. ``003``."""

    def format(value: int) -> str:
        text = f"{int(value):0{width}d}"
        if len(text) > width:
            raise ValueError(f"{value} does not fit in {width} digits")
        return text

    return Converter(int, format, f"zero_padded({width})")


# -- flags and choices -------------------------------------------------------


def flag(true: str = "YES", false: str = "NO") -> Converter:
    """Booleans written as one of two words, e.g. ``flag("ON", "OFF")``."""

    def parse(text: str) -> bool:
        if text == true:
            return True
        if text == false:
            return False
        raise ValueError(f"expected {true} or {false}, got {text!r}")

    def format(value: bool) -> str:
        return true if value else false

    return Converter(parse, format, f"flag({true!r}, {false!r})")


YES_NO = flag("YES", "NO")
Y_N = flag("Y", "N")
ON_OFF = flag("ON", "OFF")
TRUE_FALSE = flag("TRUE", "FALSE")


def one_of(*allowed: str) -> Converter:
    """Strings restricted to a fixed set of spellings, kept as strings."""
    choices = tuple(allowed)

    def check(text: Any) -> str:
        if text not in choices:
            raise ValueError(f"expected one of {', '.join(choices)}, got {text!r}")
        return text

    return Converter(check, check, f"one_of{choices!r}")


def enum_by_value(enum_type: type[Enum]) -> Converter:
    """Enum members written as their ``value``, which must be a string."""

    def format(member: Enum) -> str:
        return str(enum_type(member).value)

    return Converter(enum_type, format, f"enum_by_value({enum_type.__name__})")


def enum_by_name(enum_type: type[Enum]) -> Converter:
    """Enum members written as their ``name``."""

    def parse(text: str) -> Enum:
        try:
            return enum_type[text]
        except KeyError:
            names = ", ".join(member.name for member in enum_type)
            raise ValueError(f"expected one of {names}, got {text!r}") from None

    def format(member: Enum) -> str:
        return enum_type(member).name

    return Converter(parse, format, f"enum_by_name({enum_type.__name__})")
