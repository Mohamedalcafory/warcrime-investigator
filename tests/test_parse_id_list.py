"""Tests for CLI --ids parsing (comma-separated and inclusive ranges)."""

import pytest

from investigation_agent.cli import _parse_id_list


def test_single_id():
    assert _parse_id_list("42") == [42]


def test_comma_separated():
    assert _parse_id_list("58,55,56") == [58, 55, 56]


def test_inclusive_range():
    assert _parse_id_list("50:52") == [50, 51, 52]


def test_mixed_commas_and_ranges():
    assert _parse_id_list("10,12:14,20") == [10, 12, 13, 14, 20]


def test_dedup_preserves_first_occurrence_order():
    assert _parse_id_list("5,3:5,7") == [5, 3, 4, 7]


def test_single_element_range():
    assert _parse_id_list("9:9") == [9]


def test_empty_and_whitespace():
    assert _parse_id_list(None) == []
    assert _parse_id_list("") == []
    assert _parse_id_list("  ") == []


def test_invalid_range_descending():
    with pytest.raises(ValueError, match="start must be"):
        _parse_id_list("7:3")


def test_invalid_range_extra_colon():
    with pytest.raises(ValueError, match="invalid range token"):
        _parse_id_list("1:2:3")


def test_invalid_range_empty_side():
    with pytest.raises(ValueError, match="invalid range token"):
        _parse_id_list("5:")


def test_invalid_id_token():
    with pytest.raises(ValueError, match="invalid id token"):
        _parse_id_list("abc")

