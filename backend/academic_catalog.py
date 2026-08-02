"""Versioned academic reference catalogs and historical read aliases."""

from __future__ import annotations

import csv
import unicodedata
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from types import MappingProxyType
from typing import Mapping

from backend.contracts import (
    ACADEMIC_STATUSES,
    AcademicProfile,
    AcademicStaff,
)

STAFF_CSV_FIELDS = ("staff_id", "key", "name", "active")
PROFILE_CSV_FIELDS = (
    "profile_id",
    "staff_id",
    "key",
    "name",
    "teaching_percentage",
    "management_percentage",
    "research_percentage",
    "allows_extra_courses",
    "active",
)


class AcademicCatalogSchemaError(ValueError):
    """A versioned catalog is missing, malformed or referentially invalid."""


@dataclass(frozen=True, slots=True)
class CatalogOption:
    """Backend key, visible label and stable reference identifier."""

    key: str
    label: str
    identifier: str = ""
    active: bool = True


@dataclass(frozen=True, slots=True)
class AcademicCatalogs:
    """Validated reference tables exposed as compatibility-friendly options."""

    staff: tuple[AcademicStaff, ...]
    profile_entities: tuple[AcademicProfile, ...]
    plants: tuple[CatalogOption, ...]
    profiles: tuple[CatalogOption, ...]
    statuses: tuple[CatalogOption, ...]
    compatible_profile_keys: Mapping[str, tuple[str, ...]]
    _staff_by_key: Mapping[str, AcademicStaff]
    _profiles_by_key: Mapping[str, AcademicProfile]
    _plant_aliases: Mapping[str, str]
    _profile_aliases: Mapping[str, str]
    _status_aliases: Mapping[str, str]

    @staticmethod
    def _strict_key(value: str, options: tuple[CatalogOption, ...]) -> str | None:
        return next((option.key for option in options if option.key == value), None)

    @staticmethod
    def _read_key(value: str, aliases: Mapping[str, str]) -> str | None:
        return aliases.get(_alias_key(value))

    def strict_plant_key(self, value: str) -> str | None:
        return self._strict_key(value, self.plants)

    def strict_profile_key(self, value: str) -> str | None:
        return self._strict_key(value, self.profiles)

    def strict_status_key(self, value: str) -> str | None:
        return self._strict_key(value, self.statuses)

    def read_plant_key(self, value: str) -> str | None:
        return self._read_key(value, self._plant_aliases)

    def read_profile_key(self, value: str) -> str | None:
        return self._read_key(value, self._profile_aliases)

    def read_status_key(self, value: str) -> str | None:
        return self._read_key(value, self._status_aliases)

    def normalize_plant_for_read(self, value: str) -> str:
        return self.read_plant_key(value) or value

    def normalize_profile_for_read(self, value: str) -> str:
        return self.read_profile_key(value) or value

    def normalize_status_for_read(self, value: str) -> str:
        return self.read_status_key(value) or value

    def profiles_for_plant(self, plant_key: str) -> tuple[CatalogOption, ...]:
        allowed = self.compatible_profile_keys.get(plant_key, ())
        by_key = {option.key: option for option in self.profiles}
        return tuple(by_key[key] for key in allowed if key in by_key)

    def is_compatible(self, plant_key: str, profile_key: str) -> bool:
        profile = self._profiles_by_key.get(profile_key)
        staff = self._staff_by_key.get(plant_key)
        return (
            profile is not None
            and staff is not None
            and profile.staff_id == staff.staff_id
        )


def _alias_key(value: str) -> str:
    collapsed = " ".join(value.strip().split()).casefold()
    decomposed = unicodedata.normalize("NFKD", collapsed)
    return "".join(
        character for character in decomposed if not unicodedata.combining(character)
    )


def _aliases(values: Mapping[str, str]) -> Mapping[str, str]:
    return MappingProxyType({_alias_key(alias): key for alias, key in values.items()})


def _read_bool(value: str, *, field: str, line_number: int) -> bool:
    normalized = value.strip().casefold()
    if normalized == "true":
        return True
    if normalized == "false":
        return False
    raise AcademicCatalogSchemaError(
        f"{field} debe ser true o false en la línea {line_number}."
    )


def _read_exact_rows(path: Path, fields: tuple[str, ...]) -> list[dict[str, str]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as csv_file:
            reader = csv.DictReader(csv_file, strict=True)
            if tuple(reader.fieldnames or ()) != fields:
                raise AcademicCatalogSchemaError(
                    f"La cabecera del catálogo {path.name} no es compatible."
                )
            rows: list[dict[str, str]] = []
            for line_number, row in enumerate(reader, start=2):
                if None in row or any(row[field] is None for field in fields):
                    raise AcademicCatalogSchemaError(
                        f"El catálogo {path.name} contiene una fila inválida "
                        f"en la línea {line_number}."
                    )
                rows.append({field: str(row[field]) for field in fields})
            return rows
    except AcademicCatalogSchemaError:
        raise
    except (OSError, UnicodeError, csv.Error) as error:
        raise AcademicCatalogSchemaError(
            f"No fue posible leer el catálogo {path.name}."
        ) from error


def load_academic_catalogs(staff_path: Path, profiles_path: Path) -> AcademicCatalogs:
    """Load and validate both versioned reference tables as one catalog."""
    staff_rows = _read_exact_rows(staff_path, STAFF_CSV_FIELDS)
    profile_rows = _read_exact_rows(profiles_path, PROFILE_CSV_FIELDS)
    staff: list[AcademicStaff] = []
    staff_keys: dict[str, str] = {}
    staff_by_key: dict[str, AcademicStaff] = {}
    for line_number, row in enumerate(staff_rows, start=2):
        entity = AcademicStaff(
            staff_id=row["staff_id"],
            name=row["name"],
            active=_read_bool(row["active"], field="active", line_number=line_number),
        )
        key = row["key"]
        if entity.staff_id in staff_keys or key in staff_by_key or not key:
            raise AcademicCatalogSchemaError(
                "El catálogo de plantas duplica una identidad."
            )
        staff.append(entity)
        staff_keys[entity.staff_id] = key
        staff_by_key[key] = entity

    profile_entities: list[AcademicProfile] = []
    profile_keys: dict[str, str] = {}
    profiles_by_key: dict[str, AcademicProfile] = {}
    for line_number, row in enumerate(profile_rows, start=2):
        if row["staff_id"] not in staff_keys:
            raise AcademicCatalogSchemaError(
                "Un perfil referencia una planta inexistente."
            )
        try:
            entity = AcademicProfile(
                profile_id=row["profile_id"],
                staff_id=row["staff_id"],
                name=row["name"],
                teaching_percentage=Decimal(row["teaching_percentage"]),
                management_percentage=Decimal(row["management_percentage"]),
                research_percentage=Decimal(row["research_percentage"]),
                allows_extra_courses=_read_bool(
                    row["allows_extra_courses"],
                    field="allows_extra_courses",
                    line_number=line_number,
                ),
                active=_read_bool(
                    row["active"], field="active", line_number=line_number
                ),
            )
        except (ValueError, TypeError) as error:
            raise AcademicCatalogSchemaError(
                f"El perfil de la línea {line_number} no es válido."
            ) from error
        key = row["key"]
        if entity.profile_id in profile_keys or key in profiles_by_key or not key:
            raise AcademicCatalogSchemaError(
                "El catálogo de perfiles duplica una identidad."
            )
        profile_entities.append(entity)
        profile_keys[entity.profile_id] = key
        profiles_by_key[key] = entity

    plants = tuple(
        CatalogOption(key, entity.name, entity.staff_id, entity.active)
        for entity in staff
        if entity.active
        for key in (staff_keys[entity.staff_id],)
    )
    profiles = tuple(
        CatalogOption(
            profile_keys[item.profile_id], item.name, item.profile_id, item.active
        )
        for item in profile_entities
        if item.active
        and next(
            staff_item for staff_item in staff if staff_item.staff_id == item.staff_id
        ).active
    )
    compatible = {
        staff_keys[item.staff_id]: tuple(
            profile_keys[profile.profile_id]
            for profile in profile_entities
            if profile.staff_id == item.staff_id and profile.active and item.active
        )
        for item in staff
    }
    plant_alias_values = {key: key for key in staff_by_key}
    plant_alias_values.update({item.name: staff_keys[item.staff_id] for item in staff})
    plant_alias_values.update({"Mixta": "Especial", "Planta Mixta": "Especial"})
    profile_alias_values = {key: key for key in profiles_by_key}
    profile_alias_values.update(
        {item.name: profile_keys[item.profile_id] for item in profile_entities}
    )
    profile_alias_values.update(
        {
            "Investigadora": "Investigador",
            "Mixta": "Mixto",
            "Estándar": "Standard",
            "Estandar": "Standard",
            "Gestion": "Gestión",
        }
    )
    status_alias_values = {status: status for status in ACADEMIC_STATUSES}
    status_alias_values.update(
        {
            "Activa": "Activo",
            "Inactiva": "Inactivo",
            "Sabatico": "Sabático",
            "Terminada": "Terminado",
        }
    )
    return AcademicCatalogs(
        staff=tuple(staff),
        profile_entities=tuple(profile_entities),
        plants=plants,
        profiles=profiles,
        statuses=tuple(CatalogOption(status, status) for status in ACADEMIC_STATUSES),
        compatible_profile_keys=MappingProxyType(compatible),
        _staff_by_key=MappingProxyType(staff_by_key),
        _profiles_by_key=MappingProxyType(profiles_by_key),
        _plant_aliases=_aliases(plant_alias_values),
        _profile_aliases=_aliases(profile_alias_values),
        _status_aliases=_aliases(status_alias_values),
    )


def get_academic_catalogs(paths=None) -> AcademicCatalogs:
    """Resolve the sole production catalog source through ``ProjectPaths``."""
    from persistence.paths import DEFAULT_PATHS

    resolved_paths = paths or DEFAULT_PATHS
    staff_path = resolved_paths.academic_staff_catalog_path
    profiles_path = resolved_paths.academic_profiles_catalog_path
    if not staff_path.exists() and not profiles_path.exists() and paths is not None:
        # Isolated application roots reuse the versioned production reference data.
        staff_path = DEFAULT_PATHS.academic_staff_catalog_path
        profiles_path = DEFAULT_PATHS.academic_profiles_catalog_path
    if staff_path.exists() != profiles_path.exists():
        raise AcademicCatalogSchemaError(
            "El par de catálogos académicos está incompleto."
        )
    return load_academic_catalogs(staff_path, profiles_path)


ACADEMIC_CATALOGS = get_academic_catalogs()
