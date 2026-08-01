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
    ("legacy", "canonical"),
    [
        ("Mixta", "Especial"),
        ("Planta especial", "Especial"),
        ("estándar", "Standard"),
        ("Gestion", "Gestión"),
        ("Sabatico", "Sabático"),
    ],
)
def test_recognizable_historical_aliases_have_canonical_read_keys(
    legacy: str,
    canonical: str,
) -> None:
    catalogs = get_academic_catalogs()
    resolvers = (
        catalogs.read_plant_key,
        catalogs.read_profile_key,
        catalogs.read_status_key,
    )

    assert canonical in {resolver(legacy) for resolver in resolvers}


def test_legacy_aliases_are_not_accepted_as_strict_write_keys() -> None:
    catalogs = get_academic_catalogs()

    assert catalogs.strict_plant_key("Mixta") is None
    assert catalogs.strict_profile_key("Estándar") is None
    assert catalogs.strict_status_key("Sabatico") is None
