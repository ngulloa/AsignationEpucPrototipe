"""Presentation-only contracts used by the injectable frontend controller."""

from __future__ import annotations

from dataclasses import dataclass, field

from backend.contracts import AcademicRecord


@dataclass(frozen=True, slots=True)
class UiResult:
    """A result that a view can present without interpreting business rules."""

    success: bool
    message: str
    field_errors: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class LoginRequest:
    username: str
    password: str


@dataclass(frozen=True, slots=True)
class AuthenticationResult:
    success: bool
    message: str
    username: str = ""
    is_owner: bool = False
    is_approved: bool = False


@dataclass(frozen=True, slots=True)
class RegistrationRequest:
    username: str
    password: str
    password_confirmation: str


@dataclass(frozen=True, slots=True)
class ErrorNotificationRequest:
    source_screen: str
    category: str
    error_code: str
    description: str


@dataclass(frozen=True, slots=True)
class ShareTableRequest:
    name: str


@dataclass(frozen=True, slots=True)
class UpdateRequest:
    username: str
    update_name: str


@dataclass(frozen=True, slots=True)
class SharedAcademicTable:
    username: str
    academics: tuple[AcademicRecord, ...]
    table_number: int | None = None
    name: str = ""
    publication_state: str | None = None


@dataclass(frozen=True, slots=True)
class ApprovalItem:
    request_id: str
    username: str
    requested_at: str
    status: str
    can_withdraw: bool = False
    can_approve: bool = True


@dataclass(frozen=True, slots=True)
class OwnerAlert:
    alert_id: str
    source_screen: str
    created_at: str
    category: str
    error_code: str
    status: str
    description: str


@dataclass(frozen=True, slots=True)
class SessionPresentation:
    username: str
    is_owner: bool
    is_approved: bool = False
