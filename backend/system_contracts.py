"""Data contracts for the reserved user, sharing and update workflows."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


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


@dataclass(frozen=True, slots=True)
class UpdateResult:
    """Observable result of a requested Git-backed update."""

    changed: bool
    message: str
