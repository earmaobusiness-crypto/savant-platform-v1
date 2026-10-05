"""Letter-skip unit tests still pin the old 9:30 DNA. Live default is open."""

from __future__ import annotations

import pytest

import room3_matrix as m


@pytest.fixture(autouse=True)
def _pin_letter_skip_dna():
    old = m.OPEN_RTH_930
    m.OPEN_RTH_930 = False
    try:
        yield
    finally:
        m.OPEN_RTH_930 = old
