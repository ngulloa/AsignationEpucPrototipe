"""Tests for strict JSON settings loading and validation."""

from __future__ import annotations

import json
from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest

from frontend.settings import (
    SettingsValidationError,
    parse_visual_settings,
)
from persistence.paths import DEFAULT_PATHS
from persistence.settings_repository import (
    SettingsFileNotFoundError,
    SettingsJSONError,
    load_application_settings,
)

DEFAULT_CONFIG_PATH = DEFAULT_PATHS.frontend_visual_settings_path
DEFAULT_PARAMETERS_PATH = DEFAULT_PATHS.frontend_text_settings_path


def _read_document(path: Path) -> dict[str, object]:
    document = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(document, dict)
    return document


def _write_document(path: Path, document: object) -> Path:
    path.write_text(
        json.dumps(document, ensure_ascii=False),
        encoding="utf-8",
    )
    return path


def test_loads_both_valid_json_documents() -> None:
    settings = load_application_settings()

    assert settings.visual.schema_version == 1
    assert settings.visual.screens["menu"].width == 768
    assert settings.visual.screens["academic_list"].width == 1080
    assert settings.visual.screens["academic_form"].height == 768
    assert settings.visual.validation_viewport.height == 768
    assert settings.texts.application_name
    assert settings.texts.button_labels["add_academic"] == "Agregar"
    assert settings.texts.button_labels["owner_approvals"] == "Aprobar"
    assert settings.texts.button_labels["approvals"] == "Administrar aprobaciones"
    assert settings.texts.button_labels["overwrite"] == "Sobrescribir"
    assert settings.texts.working_hours.unit is None
    assert settings.texts.working_hours.required is None


def test_default_paths_work_from_a_different_working_directory(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(tmp_path)

    settings = load_application_settings()

    assert settings.visual.typography.preferred_family == "Roboto"
    assert settings.texts.screen_titles["academic_list"] == "Académicos"


def test_missing_file_has_specific_error(tmp_path: Path) -> None:
    missing_path = tmp_path / "missing.json"

    with pytest.raises(SettingsFileNotFoundError, match="No se encontró"):
        load_application_settings(visual_path=missing_path)


def test_invalid_json_has_specific_error(tmp_path: Path) -> None:
    invalid_path = tmp_path / "invalid.json"
    invalid_path.write_text("{", encoding="utf-8")

    with pytest.raises(SettingsJSONError, match="JSON inválido"):
        load_application_settings(visual_path=invalid_path)


def test_missing_required_key_is_rejected(tmp_path: Path) -> None:
    document = _read_document(DEFAULT_CONFIG_PATH)
    document.pop("schema_version")
    path = _write_document(tmp_path / "missing-key.json", document)

    with pytest.raises(SettingsValidationError, match="schema_version"):
        parse_visual_settings(_read_document(path))


def test_incorrect_type_is_rejected(tmp_path: Path) -> None:
    document = _read_document(DEFAULT_CONFIG_PATH)
    document["schema_version"] = "one"
    path = _write_document(tmp_path / "wrong-type.json", document)

    with pytest.raises(SettingsValidationError, match="número entero"):
        parse_visual_settings(_read_document(path))


def test_invalid_hex_color_is_rejected(tmp_path: Path) -> None:
    document = _read_document(DEFAULT_CONFIG_PATH)
    colors = document["colors"]
    assert isinstance(colors, dict)
    colors["brand_blue"] = "invalid-color"
    path = _write_document(tmp_path / "invalid-color.json", document)

    with pytest.raises(SettingsValidationError, match="formato"):
        parse_visual_settings(_read_document(path))


def test_nonpositive_dimension_is_rejected(tmp_path: Path) -> None:
    document = _read_document(DEFAULT_CONFIG_PATH)
    screens = document["screens"]
    assert isinstance(screens, dict)
    menu = screens["menu"]
    assert isinstance(menu, dict)
    menu["width"] = 0
    path = _write_document(tmp_path / "invalid-dimension.json", document)

    with pytest.raises(SettingsValidationError, match="mayor que cero"):
        parse_visual_settings(_read_document(path))


def test_frontend_texts_do_not_duplicate_backend_academic_catalogs() -> None:
    document = _read_document(DEFAULT_PARAMETERS_PATH)

    assert "catalogs" not in document


def test_missing_nested_value_does_not_receive_a_silent_default(
    tmp_path: Path,
) -> None:
    document = _read_document(DEFAULT_CONFIG_PATH)
    typography = document["typography"]
    assert isinstance(typography, dict)
    typography.pop("preferred_family")
    path = _write_document(tmp_path / "no-default.json", document)

    with pytest.raises(SettingsValidationError, match="preferred_family"):
        parse_visual_settings(_read_document(path))


def test_loaded_settings_are_structurally_immutable() -> None:
    settings = load_application_settings()

    with pytest.raises(FrozenInstanceError):
        settings.visual.schema_version = 2  # type: ignore[misc]
    with pytest.raises(TypeError):
        settings.visual.colors["brand_blue"] = "blue"  # type: ignore[index]
