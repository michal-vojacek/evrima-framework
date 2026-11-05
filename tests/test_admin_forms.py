"""Helpers for reading admin forms (evrima.admin.forms)."""

import pytest

from evrima.admin.forms import MAX_ID, parse_id, parse_ids


@pytest.mark.parametrize("value, expected", [
    ("12", 12), (" 7 ", 7), (str(MAX_ID), MAX_ID),
    ("0", None), ("-1", None), ("", None), (None, None), ("abc", None),
    ("²", None), ("١٢", None), ("1.5", None), (str(MAX_ID + 1), None),
])
def test_parse_id(value, expected):
    assert parse_id(value) == expected


def test_parse_ids_keeps_the_order_and_drops_invalid_parts():
    assert parse_ids("3, 1,x,²,2") == [3, 1, 2]
    assert parse_ids(None) == []
