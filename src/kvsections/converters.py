"""Ready-made :class:`Converter` pairs for common value encodings.

Pass one as the type of a :class:`~kvsections.Field`::

    from kvsections import Field, Section
    from kvsections.converters import HHMMSS, YYYYMMDD, zero_padded

    class HeaderSection(Section):
        section_name = "HEADER"
        created = Field(YYYYMMDD)          # datetime.date
        start = Field(HHMMSS)              # datetime.time
        revision = Field(zero_padded(3))

Every converter validates on both sides: a value the text does not fit
raises ``ValueError`` when read, and a value that cannot be written raises
``ValueError`` when assigned.
"""

from __future__ import annotations

import operator
from collections.abc import Callable
from datetime import date, datetime, time
from enum import Enum
from typing import Any, TypeVar

from .fields import Converter

E = TypeVar("E", bound=Enum)

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


def _checked(fmt: str, parse: Callable[[str], Any]) -> Callable[[Any], str]:
    """A ``strftime`` formatter that refuses values which would not read back."""

    def format(value: Any) -> str:
        text: str = value.strftime(fmt)
        if parse(text) != value:
            raise ValueError(
                f"{value!r} cannot be written with {fmt!r}: {text!r} reads back "
                f"as {parse(text)!r}"
            )
        return text

    return format


def date_format(fmt: str, name: str | None = None) -> Converter[date]:
    """Dates written with a ``strftime`` pattern, e.g. ``date_format("%y%m%d")``.

    Two-digit years follow Python's rule: ``69`` to ``99`` are 1969 to 1999
    and ``00`` to ``68`` are 2000 to 2068, in both directions. Writing a date
    the pattern cannot represent raises ``ValueError``.
    """

    def parse(text: str) -> date:
        return datetime.strptime(text, fmt).date()

    return Converter(parse, _checked(fmt, parse), name or f"date_format({fmt!r})")


def time_format(fmt: str, name: str | None = None) -> Converter[time]:
    """Times of day written with a ``strftime`` pattern, e.g. ``"%H%M%S"``.

    Writing a time the pattern cannot represent, such as one with microseconds
    under ``%H%M%S``, raises ``ValueError``.
    """

    def parse(text: str) -> time:
        return datetime.strptime(text, fmt).time()

    return Converter(parse, _checked(fmt, parse), name or f"time_format({fmt!r})")


def datetime_format(fmt: str, name: str | None = None) -> Converter[datetime]:
    """Timestamps written with a ``strftime`` pattern, e.g. ``"%Y%m%d%H%M%S"``.

    Two-digit years follow the same rule as :func:`date_format`, and values
    the pattern cannot represent raise ``ValueError`` when written.
    """

    def parse(text: str) -> datetime:
        return datetime.strptime(text, fmt)

    return Converter(parse, _checked(fmt, parse), name or f"datetime_format({fmt!r})")


#: Two-digit year with Python's pivot: ``240101`` is 2024-01-01 and ``690101``
#: is 1969-01-01. Years outside 1969 to 2068 cannot be written.
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


def zero_padded(width: int) -> Converter[int]:
    """Non-negative integers padded with zeros to ``width`` digits, e.g. ``003``.

    Reading requires digits only and at most ``width`` of them, so a value
    written without its padding still reads. Writing requires an integer
    that fits in ``width`` digits.
    """

    def parse(text: str) -> int:
        if not (text.isascii() and text.isdigit()) or len(text) > width:
            raise ValueError(f"expected up to {width} digits, got {text!r}")
        return int(text)

    def format(value: int) -> str:
        number = operator.index(value)
        if number < 0:
            raise ValueError(f"{number} is negative")
        text = f"{number:0{width}d}"
        if len(text) > width:
            raise ValueError(f"{number} does not fit in {width} digits")
        return text

    return Converter(parse, format, f"zero_padded({width})")


# -- flags and choices -------------------------------------------------------


def flag(true: str = "YES", false: str = "NO") -> Converter[bool]:
    """Booleans written as one of two words, e.g. ``flag("ON", "OFF")``.

    Reading accepts exactly the two words. Writing accepts a ``bool`` or one
    of the two words themselves; anything else raises.
    """

    def parse(text: str) -> bool:
        if text == true:
            return True
        if text == false:
            return False
        raise ValueError(f"expected {true} or {false}, got {text!r}")

    def format(value: Any) -> str:
        if isinstance(value, bool):
            return true if value else false
        if isinstance(value, str):
            parse(value)
            return value
        raise TypeError(f"expected a bool or {true!r}/{false!r}, got {value!r}")

    return Converter(parse, format, f"flag({true!r}, {false!r})")


YES_NO = flag("YES", "NO")
Y_N = flag("Y", "N")
ON_OFF = flag("ON", "OFF")
TRUE_FALSE = flag("TRUE", "FALSE")


def one_of(*allowed: str) -> Converter[str]:
    """Strings restricted to a fixed set of spellings, kept as strings."""
    choices = tuple(allowed)

    def check(text: str) -> str:
        if text not in choices:
            raise ValueError(f"expected one of {', '.join(choices)}, got {text!r}")
        return text

    return Converter(check, check, f"one_of{choices!r}")


def enum_by_value(enum_type: type[E]) -> Converter[E]:
    """Enum members written as their ``value``, which must be a string."""

    def format(member: Enum) -> str:
        return str(enum_type(member).value)

    return Converter(enum_type, format, f"enum_by_value({enum_type.__name__})")


def enum_by_name(enum_type: type[E]) -> Converter[E]:
    """Enum members written as their ``name``."""

    def parse(text: str) -> E:
        try:
            return enum_type[text]
        except KeyError:
            names = ", ".join(member.name for member in enum_type)
            raise ValueError(f"expected one of {names}, got {text!r}") from None

    def format(member: Any) -> str:
        if isinstance(member, str):
            parse(member)
            return member
        return enum_type(member).name

    return Converter(parse, format, f"enum_by_name({enum_type.__name__})")
