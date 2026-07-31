"""Pure normalization and validation functions for Chilean RUT values."""

from __future__ import annotations

import re

_RUT_STRUCTURE = re.compile(r"^(?P<body>[0-9]+)-(?P<check_digit>[0-9K])$")


def normalize_rut(value: str) -> str:
    """Remove dots and whitespace, and uppercase the check digit."""
    return "".join(value.split()).replace(".", "").upper()


def has_valid_rut_structure(normalized_rut: str) -> bool:
    """Return whether an already normalized RUT has the BODY-CHECK_DIGIT shape."""
    return _RUT_STRUCTURE.fullmatch(normalized_rut) is not None


def calculate_check_digit(body: str) -> str:
    """Calculate the modulus-11 check digit for a numeric RUT body."""
    if not body or not body.isascii() or not body.isdigit():
        raise ValueError("El cuerpo del RUT debe contener solo dígitos.")

    factor = 2
    weighted_sum = 0
    for digit in reversed(body):
        weighted_sum += int(digit) * factor
        factor = 2 if factor == 7 else factor + 1

    result = 11 - (weighted_sum % 11)
    if result == 11:
        return "0"
    if result == 10:
        return "K"
    return str(result)


def is_valid_rut(value: str) -> bool:
    """Normalize and validate a complete Chilean RUT."""
    normalized_rut = normalize_rut(value)
    match = _RUT_STRUCTURE.fullmatch(normalized_rut)
    if match is None:
        return False

    body = match.group("body")
    return calculate_check_digit(body) == match.group("check_digit")


def canonicalize_rut(value: str) -> str:
    """Return a structurally valid RUT in canonical BODY-CHECK_DIGIT form."""
    normalized_rut = normalize_rut(value)
    if not has_valid_rut_structure(normalized_rut):
        raise ValueError("El RUT no tiene una estructura válida.")
    return normalized_rut
