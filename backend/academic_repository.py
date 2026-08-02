"""Persistence abstraction and repository-specific failures for academics."""

from __future__ import annotations

from typing import Protocol

from backend.contracts import AcademicRecord


class AcademicRepositoryError(RuntimeError):
    """Base class for expected academic persistence failures."""


class AcademicRepositorySchemaError(AcademicRepositoryError):
    """The persisted representation does not match the required schema."""


class AcademicRepositoryIOError(AcademicRepositoryError):
    """An operating-system or encoding error prevented repository access."""


class AcademicRepositoryNotFoundError(AcademicRepositoryError):
    """The requested academic record does not exist."""


class AcademicRepository(Protocol):
    """Minimal persistence operations required by the academic use cases."""

    def list_all(self) -> list[AcademicRecord]:
        """Return every record in insertion order."""
        ...

    def find_by_rut(self, rut: str) -> AcademicRecord | None:
        """Return the record matching a canonical-equivalent RUT, if any."""
        ...

    def add(self, record: AcademicRecord) -> None:
        """Persist one record or raise an ``AcademicRepositoryError``."""
        ...

    def update(self, record: AcademicRecord) -> None:
        """Replace the record with the same stable identifier."""
        ...

    def delete(self, academic_id: str) -> None:
        """Delete the record matching one stable identifier."""
        ...

    def replace_all(self, records: list[AcademicRecord]) -> None:
        """Atomically replace all records after validating the schema."""
        ...
