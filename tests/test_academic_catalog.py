"""Tests for the backend-owned academic catalogs."""

from __future__ import annotations

import pytest

from backend.academic_catalog import get_academic_catalogs


def test_visible_status_catalog_contains_the_four_mvp_values() -> None:
    catalogs = get_academic_catalogs()

    assert [(option.key, option.label) for option in catalogs.statuses] == [
        ("Activo", "Activo"),
        ("Inactivo", "Inactivo"),
        ("Sabático", "Sabático"),
        ("Terminado", "Terminado"),
    ]


def test_profiles_are_exposed_by_compatible_plant() -> None:
    catalogs = get_academic_catalogs()

    assert [option.key for option in catalogs.profiles_for_plant("Ordinaria")] == [
        "Investigador",
        "Mixto",
    ]
    assert [option.key for option in catalogs.profiles_for_plant("Especial")] == [
        "Standard",
        "Docente",
        "Gestión",
    ]
    assert [option.label for option in catalogs.plants] == [
        "Planta Ordinaria",
        "Planta Especial",
    ]


@pytest.mark.parametrize(
    ("catalog", "historical", "canonical"),
    [
        ("plant", "Mixta", "Especial"),
        ("plant", "Planta Mixta", "Especial"),
        ("plant", "Planta especial", "Especial"),
        ("profile", "Investigadora", "Investigador"),
        ("profile", "Mixta", "Mixto"),
        ("profile", "estándar", "Standard"),
        ("profile", "Estandar", "Standard"),
        ("profile", "Gestion", "Gestión"),
        ("status", "Activa", "Activo"),
        ("status", "Inactiva", "Inactivo"),
        ("status", "Sabatico", "Sabático"),
        ("status", "Terminada", "Terminado"),
    ],
)
def test_recognizable_historical_aliases_have_canonical_read_keys(
    catalog: str,
    historical: str,
    canonical: str,
) -> None:
    catalogs = get_academic_catalogs()
    resolver = {
        "plant": catalogs.read_plant_key,
        "profile": catalogs.read_profile_key,
        "status": catalogs.read_status_key,
    }[catalog]

    assert resolver(historical) == canonical


def test_historical_aliases_are_not_accepted_as_strict_write_keys() -> None:
    catalogs = get_academic_catalogs()

    assert catalogs.strict_plant_key("Mixta") is None
    assert catalogs.strict_profile_key("Estándar") is None
    assert catalogs.strict_status_key("Sabatico") is None
