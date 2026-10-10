from ui.components.portal import format_portal_datetime
from ui.technical_case import _display_timestamp


def test_portal_datetime_displays_utc_storage_in_tokyo():
    assert format_portal_datetime("2026-10-10T00:15:59+00:00") == "2026/10/10 09:15"
    assert format_portal_datetime("2026-10-10T00:15:59Z") == "2026/10/10 09:15"
    assert format_portal_datetime("2026-10-10T00:15:59") == "2026/10/10 09:15"
    assert format_portal_datetime("not-a-timestamp") == "not-a-timestamp"


def test_closed_timestamp_uses_tokyo_formatter():
    assert _display_timestamp("2026-10-10T00:09:00+00:00") == "2026/10/10 09:09"
    assert _display_timestamp(None) == "-"
