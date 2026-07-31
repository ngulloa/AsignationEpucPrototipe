"""Filesystem adapter for the frontend's immutable presentation settings."""

from __future__ import annotations

import json
from json import JSONDecodeError
from pathlib import Path

from frontend.settings import ApplicationSettings, SettingsError, build_settings
from persistence.paths import DEFAULT_PATHS, ProjectPaths


class SettingsFileNotFoundError(SettingsError):
    """Raised when a required settings file does not exist."""


class SettingsFileReadError(SettingsError):
    """Raised when a settings file cannot be read."""


class SettingsJSONError(SettingsError):
    """Raised when a settings file is not valid JSON."""


def _read_document(path: Path) -> dict[str, object]:
    try:
        content = path.read_text(encoding="utf-8")
    except FileNotFoundError as error:
        raise SettingsFileNotFoundError(
            f"No se encontró el archivo de configuración requerido: {path}"
        ) from error
    except OSError as error:
        raise SettingsFileReadError(
            f"No se pudo leer el archivo de configuración '{path}': {error}"
        ) from error

    try:
        parsed: object = json.loads(content)
    except JSONDecodeError as error:
        raise SettingsJSONError(
            f"JSON inválido en '{path}', línea {error.lineno}, "
            f"columna {error.colno}: {error.msg}"
        ) from error
    if not isinstance(parsed, dict) or not all(isinstance(key, str) for key in parsed):
        raise SettingsJSONError(
            f"El documento de configuración '{path}' debe ser un objeto JSON."
        )
    return parsed


def load_application_settings(
    paths: ProjectPaths = DEFAULT_PATHS,
    *,
    visual_path: Path | None = None,
    texts_path: Path | None = None,
) -> ApplicationSettings:
    """Read both documents outside the frontend and return validated settings."""
    return build_settings(
        _read_document(visual_path or paths.frontend_visual_settings_path),
        _read_document(texts_path or paths.frontend_text_settings_path),
    )
