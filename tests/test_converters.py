"""The ready-made converters in kvsections.converters."""

from datetime import date, datetime, time
from enum import Enum

import pytest

from helpers import (
    GOLDEN,
    CommentDocument,
)
from kvsections import (
    Field,
    Section,
    SectionField,
)
from kvsections.converters import (
    HHMM,
    HHMMSS,
    ON_OFF,
    TRUE_FALSE,
    Y_N,
    YES_NO,
    YYMMDD,
    YYYYMMDD,
    YYYYMMDDHHMMSS,
    date_format,
    enum_by_name,
    enum_by_value,
    flag,
    one_of,
    time_format,
    zero_padded,
)


def test_date_and_time_converters_round_trip():
    class Header(Section):
        section_name = "HEADER"
        created = Field("CREATED", YYYYMMDD)
        short = Field("SHORT", YYMMDD)

    class Schedule(Section):
        section_name = "SCHEDULE"
        start = Field("START", HHMMSS)
        stop = Field("STOP", HHMM)
        dates = Field("DATES", list[YYYYMMDD], default=())

    header = Header(fields={"CREATED": "20240101", "SHORT": "001210"})
    assert header.created == date(2024, 1, 1)
    assert header.short == date(2000, 12, 10)
    header.created = date(2025, 2, 3)
    header.short = date(1999, 12, 31)
    assert header.fields == {"CREATED": "20250203", "SHORT": "991231"}

    schedule = Schedule(fields={"START": "080000", "STOP": "1730"})
    assert schedule.start == time(8, 0, 0)
    assert schedule.stop == time(17, 30)
    assert schedule.dates == []
    schedule.dates = [date(2024, 1, 1), date(2024, 1, 2)]
    assert schedule.fields["DATES"] == "20240101,20240102"
    assert schedule.dates == [date(2024, 1, 1), date(2024, 1, 2)]
    with pytest.raises(ValueError):
        _ = Schedule(fields={"START": "8am"}).start


def test_two_digit_years_follow_pythons_pivot_in_both_directions():
    class H(Section):
        section_name = "H"
        d = Field("D", YYMMDD)

    assert H(fields={"D": "690101"}).d == date(1969, 1, 1)
    assert H(fields={"D": "680101"}).d == date(2068, 1, 1)
    h = H()
    h.d = date(2068, 12, 31)
    assert h["D"] == "681231"
    h.d = date(1969, 1, 1)
    assert h["D"] == "690101"
    for bad in (date(1968, 12, 31), date(2069, 1, 1), date(1950, 1, 1)):
        with pytest.raises(ValueError, match="reads back"):
            h.d = bad


def test_time_and_datetime_converters_reject_lossy_values():
    class S(Section):
        section_name = "S"
        t = Field("T", HHMMSS)
        m = Field("M", HHMM)
        dt = Field("DT", YYYYMMDDHHMMSS)

    s = S()
    s.t = time(8, 0, 0)
    s.dt = datetime(2024, 1, 1, 8, 0, 0)
    assert s.fields == {"T": "080000", "DT": "20240101080000"}
    assert S(fields={"DT": "20240101080000"}).dt == datetime(2024, 1, 1, 8)
    with pytest.raises(ValueError, match="reads back"):
        s.t = time(8, 0, 0, 500)
    with pytest.raises(ValueError, match="reads back"):
        s.m = time(8, 0, 30)


def test_custom_strftime_patterns():
    class S(Section):
        section_name = "S"
        d = Field("D", date_format("%d/%m/%Y"))
        t = Field("T", time_format("%H:%M"))

    s = S(fields={"D": "31/12/2024", "T": "17:30"})
    assert (s.d, s.t) == (date(2024, 12, 31), time(17, 30))
    s.d = date(2025, 1, 2)
    s.t = time(8, 5)
    assert s.fields == {"D": "02/01/2025", "T": "08:05"}
    with pytest.raises(ValueError, match="reads back"):
        s.t = time(8, 5, 30)


def test_zero_padded_flag_choice_and_enum_converters():
    class Mode(Enum):
        NORMAL = "N"
        FAST = "F"

    class Items(Section):
        section_name = "ITEMS"
        size = Field("SIZE", zero_padded(6))
        on = Field("ON", flag("ON", "OFF"))
        level = Field("LEVEL", one_of("LOW", "HIGH"))
        by_value = Field("BYVALUE", enum_by_value(Mode))
        by_name = Field("BYNAME", enum_by_name(Mode))

    items = Items(
        size=1024, on=False, level="LOW", by_value=Mode.FAST, by_name=Mode.FAST
    )
    assert items.fields == {
        "SIZE": "001024",
        "ON": "OFF",
        "LEVEL": "LOW",
        "BYVALUE": "F",
        "BYNAME": "FAST",
    }
    assert items.size == 1024 and items.on is False
    assert items.by_value is Mode.FAST and items.by_name is Mode.FAST
    with pytest.raises(ValueError, match="digits"):
        items.size = 1234567
    with pytest.raises(ValueError, match="expected"):
        items.level = "MEDIUM"
    items["LEVEL"] = "MEDIUM"
    with pytest.raises(ValueError, match="expected"):
        _ = items.level
    items["ON"] = "MAYBE"
    with pytest.raises(ValueError, match="expected ON or OFF"):
        _ = items.on
    items["BYNAME"] = "SLOW"
    with pytest.raises(ValueError, match="expected one of NORMAL, FAST"):
        _ = items.by_name


def test_zero_padded_requires_digits_that_fit_the_width():
    class Z(Section):
        section_name = "Z"
        n = Field("N", zero_padded(3))

    assert Z(fields={"N": "007"}).n == 7
    assert Z(fields={"N": "7"}).n == 7  # narrower than declared still reads
    for bad in ("1234", "1_2", "-12", "1.5", "abc", ""):
        with pytest.raises(ValueError, match="digits"):
            _ = Z(fields={"N": bad}).n
    z = Z()
    z.n = 7
    assert z["N"] == "007"
    with pytest.raises(ValueError, match="digits"):
        z.n = 1234
    with pytest.raises(ValueError, match="negative"):
        z.n = -1
    with pytest.raises(TypeError):
        z.n = 3.9


def test_flag_accepts_bools_and_its_own_spellings_only():
    class Cfg(Section):
        section_name = "CONFIG"
        enabled = Field("ENABLED", YES_NO)

    cfg = Cfg()
    cfg.enabled = True
    assert cfg["ENABLED"] == "YES"
    cfg.enabled = "NO"
    assert cfg["ENABLED"] == "NO" and cfg.enabled is False
    with pytest.raises(ValueError, match="expected YES or NO"):
        cfg.enabled = "MAYBE"
    with pytest.raises(TypeError):
        cfg.enabled = 1
    for converter, true, false in (
        (Y_N, "Y", "N"),
        (ON_OFF, "ON", "OFF"),
        (TRUE_FALSE, "TRUE", "FALSE"),
    ):
        assert converter.parse(true) is True and converter.parse(false) is False
        assert converter.format(True) == true and converter.format(False) == false


def test_enum_by_value_rejects_non_members_on_assignment():
    class Mode(Enum):
        NORMAL = "N"

    class S(Section):
        section_name = "S"
        mode = Field("MODE", enum_by_value(Mode))

    s = S()
    s.mode = "N"  # the value itself is accepted
    assert s["MODE"] == "N" and s.mode is Mode.NORMAL
    with pytest.raises(ValueError):
        s.mode = "X"


def test_converters_on_the_sample():
    class Header(Section):
        section_name = "HEADER"
        created = Field("CREATED", YYYYMMDD)
        revision = Field("REVISION", zero_padded(3))

    class Config(Section):
        section_name = "CONFIG"
        enabled = Field("ENABLED", YES_NO)
        mode = Field("MODE", one_of("NORMAL", "FAST"))

    class Schedule(Section):
        section_name = "SCHEDULE"
        start = Field("START", HHMMSS)
        stop = Field("STOP", HHMMSS)

    class Doc(CommentDocument):
        header = SectionField(Header)
        config = SectionField(Config)
        schedule = SectionField(Schedule)

    doc = Doc.read(GOLDEN)
    assert doc.header.created == date(2024, 1, 1)
    assert doc.header.revision == 3
    assert doc.config.enabled is True
    assert doc.config.mode == "NORMAL"
    assert (doc.schedule.start, doc.schedule.stop) == (time(8, 0), time(17, 30))
    # reading through converters changes nothing on disk
    assert doc.dumps(indent=12, newline="\r\n").encode("ascii") == GOLDEN.read_bytes()


def test_enum_by_name_accepts_the_name_on_assignment():
    class Mode(Enum):
        NORMAL = "N"
        FAST = "F"

    class S(Section):
        section_name = "S"
        mode = Field("MODE", enum_by_name(Mode))

    s = S()
    s.mode = "FAST"  # the name itself, symmetric with enum_by_value
    assert s["MODE"] == "FAST" and s.mode is Mode.FAST
    s.mode = Mode.NORMAL
    assert s["MODE"] == "NORMAL"
    with pytest.raises(ValueError, match="expected one of"):
        s.mode = "SLOW"
