"""Unit tests for pure Chilean RUT normalization and validation."""

from __future__ import annotations

import pytest

from backend.rut_validator import (
    calculate_check_digit,
    canonicalize_rut,
    has_valid_rut_structure,
    is_valid_rut,
    normalize_rut,
)


def test_valid_rut_with_dots_and_hyphen() -> None:
    assert is_valid_rut("12.345.678-5") is True


def test_valid_rut_without_dots() -> None:
    assert is_valid_rut("12345678-5") is True


@pytest.mark.parametrize("check_digit", ["K", "k"])
def test_accepts_uppercase_and_lowercase_k(check_digit: str) -> None:
    assert is_valid_rut(f"40.000.000-{check_digit}") is True


def test_normalizes_to_canonical_format() -> None:
    assert canonicalize_rut(" 12.345.678 - 5 ") == "12345678-5"


def test_rejects_incorrect_check_digit() -> None:
    assert is_valid_rut("12.345.678-4") is False


def test_rejects_empty_string() -> None:
    assert is_valid_rut("") is False


def test_rejects_non_numeric_body() -> None:
    assert is_valid_rut("12A45678-5") is False


@pytest.mark.parametrize("value", ["12345678-X", "12345678-Á", "12345678-10"])
def test_rejects_invalid_check_digit(value: str) -> None:
    assert is_valid_rut(value) is False


def test_rejects_missing_hyphen() -> None:
    assert is_valid_rut("123456785") is False


def test_rejects_multiple_hyphens() -> None:
    assert is_valid_rut("12-345678-5") is False


def test_accepts_admissible_outer_and_inner_spaces() -> None:
    assert is_valid_rut("  12.345 . 678  -  5  ") is True


@pytest.mark.parametrize("value", ["-", "12345678-", "-5", "12.345.678"])
def test_rejects_evidently_incomplete_values(value: str) -> None:
    assert is_valid_rut(value) is False


def test_calculates_expected_zero_check_digit() -> None:
    assert calculate_check_digit("11000003") == "0"
    assert is_valid_rut("11.000.003-0") is True


def test_calculates_expected_k_check_digit() -> None:
    assert calculate_check_digit("40000000") == "K"
    assert is_valid_rut("40.000.000-K") is True


@pytest.mark.parametrize("body", ["", "123A", "１２３"])
def test_check_digit_requires_ascii_numeric_body(body: str) -> None:
    with pytest.raises(ValueError):
        calculate_check_digit(body)


def test_structure_check_has_one_specific_responsibility() -> None:
    assert has_valid_rut_structure("12345678-5") is True
    assert has_valid_rut_structure("12.345.678-5") is False


def test_functions_do_not_modify_input_or_print(
    capsys: pytest.CaptureFixture[str],
) -> None:
    original = " 40.000.000-k "

    assert normalize_rut(original) == "40000000-K"
    assert is_valid_rut(original) is True
    assert original == " 40.000.000-k "
    assert capsys.readouterr().out == ""
