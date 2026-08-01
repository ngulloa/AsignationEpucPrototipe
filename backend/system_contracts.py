"""Data contracts for the reserved user, sharing and update workflows."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

DESCRIPTION_MAX_LENGTH = 1000
SENSITIVE_DESCRIPTION_MESSAGE = (
    "La descripción contiene información que no puede enviarse."
)
DESCRIPTION_REQUIRED_MESSAGE = "Ingrese una descripción del problema."
DESCRIPTION_PRIVACY_WARNING = (
    "No copie credenciales, rutas personales ni trazas completas."
)

_SENSITIVE_PATTERNS = tuple(
    re.compile(pattern, re.IGNORECASE | re.MULTILINE)
    for pattern in (
        r"\b(?:contrase(?:ñ|n)a|password|passwd|pwd)\s*[:=]\s*\S+",
        r"\b(?:access[_ -]?token|refresh[_ -]?token|token)\s*[:=]\s*\S+",
        r"\b(?:api[_ -]?key|apikey|clave\s+api)\s*[:=]\s*\S+",
        r"\b(?:sk-[A-Za-z0-9_-]{8,}|gh[pousr]_[A-Za-z0-9]{8,})\b",
        r"\bAKIA[A-Z0-9]{16}\b",
        r"\beyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\b",
        r"^\s*authorization\s*:\s*(?:bearer|basic)\s+\S+",
        r"-----BEGIN(?: [A-Z0-9]+)? PRIVATE KEY-----",
        r"\b[a-z][a-z0-9+.-]*://[^\s/:@]+:[^\s/@]+@",
        r"(?:^|\s)/(?:home|Users)/[^/\s]+/(?:[^\s]+)",
        r"(?:^|\s)[A-Za-z]:\\Users\\[^\\\s]+\\(?:[^\s]+)",
        r"Traceback \(most recent call last\):[\s\S]+(?:Error|Exception):",
    )
)


def normalize_notification_description(value: str) -> str:
    """Normalize paragraphs without flattening meaningful line breaks."""
    if not isinstance(value, str):
        raise ValueError(DESCRIPTION_REQUIRED_MESSAGE)
    normalized_newlines = value.replace("\r\n", "\n").replace("\r", "\n")
    lines = [
        re.sub(r"[ \t]+", " ", line.strip()) for line in normalized_newlines.split("\n")
    ]
    while lines and not lines[0]:
        lines.pop(0)
    while lines and not lines[-1]:
        lines.pop()
    collapsed: list[str] = []
    for line in lines:
        if line or not collapsed or collapsed[-1]:
            collapsed.append(line)
    return "\n".join(collapsed)


def validate_notification_description(value: str) -> str:
    """Return safe normalized text or a generic, non-reflective error."""
    normalized = normalize_notification_description(value)
    if not normalized or not any(not character.isspace() for character in normalized):
        raise ValueError(DESCRIPTION_REQUIRED_MESSAGE)
    if len(normalized) > DESCRIPTION_MAX_LENGTH:
        raise ValueError("La descripción no puede superar 1000 caracteres.")
    if any(pattern.search(normalized) for pattern in _SENSITIVE_PATTERNS):
        raise ValueError(SENSITIVE_DESCRIPTION_MESSAGE)
    return normalized


def normalize_table_name(value: str) -> str:
    """Return the canonical visible table name, never a path component."""
    if not isinstance(value, str):
        raise ValueError("Ingrese un nombre para la tabla.")
    normalized = unicodedata.normalize("NFKC", value)
    if any(
        character in "\r\n" or unicodedata.category(character).startswith("C")
        for character in normalized
    ):
        raise ValueError(
            "El nombre de la tabla no admite saltos de línea ni controles."
        )
    clean = " ".join(normalized.strip().split())
    if not clean:
        raise ValueError("Ingrese un nombre para la tabla.")
    if len(clean) > 80:
        raise ValueError("El nombre de la tabla no puede superar 80 caracteres.")
    return clean


def table_name_key(value: str) -> str:
    """Return the Unicode-aware comparison key for a valid table name."""
    return normalize_table_name(value).casefold()


@dataclass(frozen=True, slots=True)
class AuthenticatedSession:
    """Identity held by the process-local session after authentication."""

    username: str


@dataclass(frozen=True, slots=True)
class UserPermissions:
    """Permission state exposed to the frontend for one user."""

    username: str
    approved: bool
    owner: bool


@dataclass(frozen=True, slots=True)
class SharedTable:
    """Metadata needed to identify a table in the shared index."""

    table_id: str
    name: str
    owner_username: str
    path: Path
    table_number: int | None = None
    updated_at: str | None = None


@dataclass(frozen=True, slots=True)
class TablePublication:
    """Local source selected for publication under a shared table name."""

    name: str
    source_path: Path


@dataclass(frozen=True, slots=True)
class ErrorNotification:
    """Allowlisted, presentation-independent error classification."""

    source_screen: str
    category: str
    error_code: str
    description: str

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "description",
            validate_notification_description(self.description),
        )


@dataclass(frozen=True, slots=True)
class UpdateResult:
    """Observable result of a requested Git-backed update."""

    changed: bool
    message: str


class PublicationState(StrEnum):
    """Durable states of one recoverable Git publication operation."""

    PREPARED = "prepared"
    COMMITTED_LOCAL = "committed_local"
    PUBLISHED = "published"
    RETRY_PENDING = "retry_pending"
    FAILED_BEFORE_COMMIT = "failed_before_commit"


class PublicationKind(StrEnum):
    """Origin of the private dataset that an operation will publish."""

    PUBLIC_EDIT = "public_edit"
    PERSONAL_UPDATE = "personal_update"


@dataclass(frozen=True, slots=True)
class PublicationOperation:
    """Private, non-secret audit record for one exact publication unit."""

    operation_id: str
    username: str
    kind: PublicationKind
    table_number: int
    table_name: str
    owner_username: str
    filename: str
    authorized_paths: tuple[str, ...]
    base_fingerprint: str
    state: PublicationState
    commit: str | None
    error: str | None
    prepared_at: str
