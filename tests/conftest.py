"""Shared test defaults."""

from datetime import date, datetime, time, timedelta

import pytest

from condor.data import store as _store


@pytest.fixture(autouse=True)
def _store_clock_after_close(monkeypatch):
    """Fake price histories end on today's date; pin the store's clock to
    tomorrow noon in New York so today's bar is final whatever time the
    suite runs. Tests of the final-bar rule set their own clock."""
    noon = datetime.combine(date.today() + timedelta(days=1), time(12),
                            _store._NY)
    monkeypatch.setattr(_store, "_now", lambda: noon)
