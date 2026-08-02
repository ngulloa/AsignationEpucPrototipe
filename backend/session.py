"""Port for process-local, in-memory session state."""

from __future__ import annotations

from typing import Protocol

from backend.contracts import AuthenticatedSession


class SessionMemory(Protocol):
    """Define session state without selecting an authentication implementation."""

    @property
    def current_session(self) -> AuthenticatedSession | None:
        """Return the active session, if one exists."""
        ...

    def establish_session(self, session: AuthenticatedSession) -> None:
        """Store an authenticated session for the current process."""
        ...

    def clear_session(self) -> None:
        """Remove the current process session."""
        ...


class InMemorySession:
    """Hold exactly one authenticated identity for this process instance."""

    __slots__ = ("_current_session",)

    def __init__(self) -> None:
        self._current_session: AuthenticatedSession | None = None

    @property
    def current_session(self) -> AuthenticatedSession | None:
        return self._current_session

    def establish_session(self, session: AuthenticatedSession) -> None:
        self._current_session = session

    def clear_session(self) -> None:
        self._current_session = None
