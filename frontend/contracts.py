"""Presentation-only contracts used by the injectable frontend controller."""

from __future__ import annotations

from dataclasses import dataclass, field


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


@dataclass(frozen=True, slots=True)
class RegistrationRequest:
    username: str
    password: str
    password_confirmation: str


@dataclass(frozen=True, slots=True)
class RegistrationResult(UiResult):
    """Successful registration also carries the established session identity."""

    username: str = ""


@dataclass(frozen=True, slots=True)
class SessionPresentation:
    username: str
