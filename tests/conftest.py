"""Every file in tests/samples is a test subject for the checks in test_samples.py.

A test taking a ``sample`` argument runs once per ``*.txt`` file; one taking a
``golden_sample`` argument runs only over ``golden*.txt``, the files expected to
be in canonical layout.
"""

from helpers import SAMPLES


def pytest_generate_tests(metafunc):
    for fixture, pattern in (("sample", "*.txt"), ("golden_sample", "golden*.txt")):
        if fixture in metafunc.fixturenames:
            paths = sorted(SAMPLES.glob(pattern))
            metafunc.parametrize(fixture, paths, ids=[path.name for path in paths])
