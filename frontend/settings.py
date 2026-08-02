"""Typed immutable settings built only from injected in-memory documents."""

from __future__ import annotations

import re
from dataclasses import dataclass
from types import MappingProxyType
from typing import Mapping, TypeVar

SUPPORTED_SCHEMA_VERSION = 1
_HEX_COLOR_PATTERN = re.compile(r"^#[0-9A-Fa-f]{6}$")

_ValueT = TypeVar("_ValueT")


class SettingsError(Exception):
    """Base exception for settings loading failures."""


class SettingsValidationError(SettingsError):
    """Raised when parsed settings do not match the required schema."""


@dataclass(frozen=True, slots=True)
class Dimensions:
    """Positive width and height in logical pixels."""

    width: int
    height: int


@dataclass(frozen=True, slots=True)
class TypographySettings:
    """Font families, sizes and weights used by the interface."""

    preferred_family: str
    fallback_families: tuple[str, ...]
    sizes: Mapping[str, int]
    weights: Mapping[str, int]


@dataclass(frozen=True, slots=True)
class BorderSettings:
    """Border width and reference to a canonical color token."""

    width: int
    color_token: str


@dataclass(frozen=True, slots=True)
class ShadowSettings:
    """Shadow geometry and color."""

    offset_x: int
    offset_y: int
    blur: int
    color: str
    opacity: float


@dataclass(frozen=True, slots=True)
class VisualSettings:
    """Complete validated visual configuration."""

    schema_version: int
    colors: Mapping[str, str]
    typography: TypographySettings
    screens: Mapping[str, Dimensions]
    margins: Mapping[str, int]
    spacing: Mapping[str, int]
    radii: Mapping[str, int]
    borders: Mapping[str, BorderSettings]
    shadows: Mapping[str, ShadowSettings]


@dataclass(frozen=True, slots=True)
class TextParameters:
    """Validated visible texts consumed by active views."""

    schema_version: int
    application_name: str
    headers: Mapping[str, str]
    screen_titles: Mapping[str, str]
    button_labels: Mapping[str, str]
    field_labels: Mapping[str, str]
    table_headers: tuple[str, ...]
    messages: Mapping[str, str]
    out_of_scope_function_texts: Mapping[str, str]


@dataclass(frozen=True, slots=True)
class ApplicationSettings:
    """Visual and textual settings loaded as one immutable value."""

    visual: VisualSettings
    texts: TextParameters


def _immutable_mapping(values: Mapping[str, _ValueT]) -> Mapping[str, _ValueT]:
    """Return a read-only copy of a string-keyed mapping."""
    return MappingProxyType(dict(values))


def _validation_error(location: str, message: str) -> SettingsValidationError:
    return SettingsValidationError(f"Configuración inválida en '{location}': {message}")


def _require_object(value: object, location: str) -> dict[str, object]:
    if not isinstance(value, dict):
        raise _validation_error(location, "se esperaba un objeto JSON")
    if not all(isinstance(key, str) for key in value):
        raise _validation_error(location, "todas las claves deben ser texto")
    return value


def _required(
    values: Mapping[str, object],
    key: str,
    location: str,
) -> object:
    if key not in values:
        raise _validation_error(f"{location}.{key}", "falta la clave obligatoria")
    return values[key]


def _require_string(value: object, location: str) -> str:
    if not isinstance(value, str):
        raise _validation_error(location, "se esperaba texto")
    if not value.strip():
        raise _validation_error(location, "el texto no puede estar vacío")
    return value


def _require_integer(value: object, location: str) -> int:
    if type(value) is not int:
        raise _validation_error(location, "se esperaba un número entero")
    return value


def _require_positive_integer(value: object, location: str) -> int:
    integer = _require_integer(value, location)
    if integer <= 0:
        raise _validation_error(location, "el valor debe ser mayor que cero")
    return integer


def _require_nonnegative_integer(value: object, location: str) -> int:
    integer = _require_integer(value, location)
    if integer < 0:
        raise _validation_error(location, "el valor no puede ser negativo")
    return integer


def _require_number(value: object, location: str) -> float:
    if type(value) not in (int, float):
        raise _validation_error(location, "se esperaba un número")
    return float(value)


def _parse_schema_version(values: Mapping[str, object], location: str) -> int:
    version = _require_positive_integer(
        _required(values, "schema_version", location),
        f"{location}.schema_version",
    )
    if version != SUPPORTED_SCHEMA_VERSION:
        raise _validation_error(
            f"{location}.schema_version",
            f"versión no soportada: {version}",
        )
    return version


def _parse_dimensions(value: object, location: str) -> Dimensions:
    values = _require_object(value, location)
    width = _require_positive_integer(
        _required(values, "width", location),
        f"{location}.width",
    )
    height = _require_positive_integer(
        _required(values, "height", location),
        f"{location}.height",
    )
    return Dimensions(width=width, height=height)


def _parse_dimensions_mapping(
    value: object,
    location: str,
) -> Mapping[str, Dimensions]:
    values = _require_object(value, location)
    required_screens = (
        "login",
        "register",
        "menu",
        "academic_list",
        "academic_form",
    )
    dimensions = {
        screen: _parse_dimensions(
            _required(values, screen, location),
            f"{location}.{screen}",
        )
        for screen in required_screens
    }
    return _immutable_mapping(dimensions)


def _parse_string_list(
    value: object,
    location: str,
    *,
    reject_duplicates: bool = False,
) -> tuple[str, ...]:
    if not isinstance(value, list):
        raise _validation_error(location, "se esperaba una lista")
    if not value:
        raise _validation_error(location, "la lista no puede estar vacía")

    parsed = tuple(
        _require_string(item, f"{location}[{index}]")
        for index, item in enumerate(value)
    )
    if reject_duplicates and len(parsed) != len(set(parsed)):
        raise _validation_error(location, "la lista contiene valores duplicados")
    return parsed


def _parse_string_mapping(
    value: object,
    location: str,
) -> Mapping[str, str]:
    values = _require_object(value, location)
    if not values:
        raise _validation_error(location, "el objeto no puede estar vacío")
    parsed = {
        _require_string(key, f"{location}.<clave>"): _require_string(
            item,
            f"{location}.{key}",
        )
        for key, item in values.items()
    }
    return _immutable_mapping(parsed)


def _parse_positive_integer_mapping(
    value: object,
    location: str,
) -> Mapping[str, int]:
    values = _require_object(value, location)
    if not values:
        raise _validation_error(location, "el objeto no puede estar vacío")
    parsed = {
        _require_string(key, f"{location}.<clave>"): _require_positive_integer(
            item,
            f"{location}.{key}",
        )
        for key, item in values.items()
    }
    return _immutable_mapping(parsed)


def _parse_colors(value: object, location: str) -> Mapping[str, str]:
    colors = _parse_string_mapping(value, location)
    for name, color in colors.items():
        if _HEX_COLOR_PATTERN.fullmatch(color) is None:
            raise _validation_error(
                f"{location}.{name}",
                "el color debe usar el formato #RRGGBB",
            )
    return colors


def _parse_typography(value: object, location: str) -> TypographySettings:
    values = _require_object(value, location)
    preferred_family = _require_string(
        _required(values, "preferred_family", location),
        f"{location}.preferred_family",
    )
    fallback_families = _parse_string_list(
        _required(values, "fallback_families", location),
        f"{location}.fallback_families",
        reject_duplicates=True,
    )
    sizes = _parse_positive_integer_mapping(
        _required(values, "sizes", location),
        f"{location}.sizes",
    )
    weights = _parse_positive_integer_mapping(
        _required(values, "weights", location),
        f"{location}.weights",
    )
    return TypographySettings(
        preferred_family=preferred_family,
        fallback_families=fallback_families,
        sizes=sizes,
        weights=weights,
    )


def _parse_borders(
    value: object,
    location: str,
    colors: Mapping[str, str],
) -> Mapping[str, BorderSettings]:
    values = _require_object(value, location)
    if not values:
        raise _validation_error(location, "el objeto no puede estar vacío")

    parsed: dict[str, BorderSettings] = {}
    for name, raw_border in values.items():
        border_location = f"{location}.{name}"
        border = _require_object(raw_border, border_location)
        width = _require_positive_integer(
            _required(border, "width", border_location),
            f"{border_location}.width",
        )
        color_token = _require_string(
            _required(border, "color_token", border_location),
            f"{border_location}.color_token",
        )
        if color_token not in colors:
            raise _validation_error(
                f"{border_location}.color_token",
                f"el token de color '{color_token}' no existe",
            )
        parsed[name] = BorderSettings(width=width, color_token=color_token)
    return _immutable_mapping(parsed)


def _parse_shadows(
    value: object,
    location: str,
) -> Mapping[str, ShadowSettings]:
    values = _require_object(value, location)
    if not values:
        raise _validation_error(location, "el objeto no puede estar vacío")

    parsed: dict[str, ShadowSettings] = {}
    for name, raw_shadow in values.items():
        shadow_location = f"{location}.{name}"
        shadow = _require_object(raw_shadow, shadow_location)
        color = _require_string(
            _required(shadow, "color", shadow_location),
            f"{shadow_location}.color",
        )
        if _HEX_COLOR_PATTERN.fullmatch(color) is None:
            raise _validation_error(
                f"{shadow_location}.color",
                "el color debe usar el formato #RRGGBB",
            )
        opacity = _require_number(
            _required(shadow, "opacity", shadow_location),
            f"{shadow_location}.opacity",
        )
        if not 0.0 <= opacity <= 1.0:
            raise _validation_error(
                f"{shadow_location}.opacity",
                "la opacidad debe estar entre cero y uno",
            )
        parsed[name] = ShadowSettings(
            offset_x=_require_integer(
                _required(shadow, "offset_x", shadow_location),
                f"{shadow_location}.offset_x",
            ),
            offset_y=_require_integer(
                _required(shadow, "offset_y", shadow_location),
                f"{shadow_location}.offset_y",
            ),
            blur=_require_nonnegative_integer(
                _required(shadow, "blur", shadow_location),
                f"{shadow_location}.blur",
            ),
            color=color,
            opacity=opacity,
        )
    return _immutable_mapping(parsed)


def parse_visual_settings(values: Mapping[str, object]) -> VisualSettings:
    location = "config"
    schema_version = _parse_schema_version(values, location)
    colors = _parse_colors(
        _required(values, "colors", location),
        f"{location}.colors",
    )
    return VisualSettings(
        schema_version=schema_version,
        colors=colors,
        typography=_parse_typography(
            _required(values, "typography", location),
            f"{location}.typography",
        ),
        screens=_parse_dimensions_mapping(
            _required(values, "screens", location),
            f"{location}.screens",
        ),
        margins=_parse_positive_integer_mapping(
            _required(values, "margins", location),
            f"{location}.margins",
        ),
        spacing=_parse_positive_integer_mapping(
            _required(values, "spacing", location),
            f"{location}.spacing",
        ),
        radii=_parse_positive_integer_mapping(
            _required(values, "radii", location),
            f"{location}.radii",
        ),
        borders=_parse_borders(
            _required(values, "borders", location),
            f"{location}.borders",
            colors,
        ),
        shadows=_parse_shadows(
            _required(values, "shadows", location),
            f"{location}.shadows",
        ),
    )


def parse_text_parameters(values: Mapping[str, object]) -> TextParameters:
    location = "parameters"
    return TextParameters(
        schema_version=_parse_schema_version(values, location),
        application_name=_require_string(
            _required(values, "application_name", location),
            f"{location}.application_name",
        ),
        headers=_parse_string_mapping(
            _required(values, "headers", location),
            f"{location}.headers",
        ),
        screen_titles=_parse_string_mapping(
            _required(values, "screen_titles", location),
            f"{location}.screen_titles",
        ),
        button_labels=_parse_string_mapping(
            _required(values, "button_labels", location),
            f"{location}.button_labels",
        ),
        field_labels=_parse_string_mapping(
            _required(values, "field_labels", location),
            f"{location}.field_labels",
        ),
        table_headers=_parse_string_list(
            _required(values, "table_headers", location),
            f"{location}.table_headers",
        ),
        messages=_parse_string_mapping(
            _required(values, "messages", location),
            f"{location}.messages",
        ),
        out_of_scope_function_texts=_parse_string_mapping(
            _required(values, "out_of_scope_function_texts", location),
            f"{location}.out_of_scope_function_texts",
        ),
    )


def build_settings(
    visual_document: Mapping[str, object],
    texts_document: Mapping[str, object],
) -> ApplicationSettings:
    """Validate injected documents and return one immutable typed value."""
    return ApplicationSettings(
        visual=parse_visual_settings(visual_document),
        texts=parse_text_parameters(texts_document),
    )
