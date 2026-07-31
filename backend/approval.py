"""Backend boundary for user approval and permission queries."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from backend.session import SessionMemory
from backend.system_contracts import UserPermissions
from persistence.approval_repository import (
    ApprovalEntry,
    JsonApprovalRepository,
    OwnerConfigurationError,
    load_owner_username,
)
from persistence.paths import DEFAULT_PATHS, ProjectPaths, normalize_username
from persistence.user_repository import JsonUserRepository


class AuthorizationError(RuntimeError):
    """The current process session cannot perform the requested operation."""


class ApprovalError(RuntimeError):
    """An approval request cannot be completed safely."""


class ApprovalService:
    """Enforce owner-first approval and transitive approval permissions."""

    def __init__(
        self,
        sessions: SessionMemory,
        users: JsonUserRepository,
        approvals: JsonApprovalRepository,
        *,
        paths: ProjectPaths = DEFAULT_PATHS,
    ) -> None:
        self._sessions = sessions
        self._users = users
        self._approvals = approvals
        self._paths = paths

    def request_approval(self) -> ApprovalEntry:
        username = self._authenticated_username()
        if self._owner_username(required=False) == username:
            raise ApprovalError("El propietario ya cuenta con permisos de aprobación.")
        existing = self._approvals.find_username(username)
        if existing is not None:
            return existing
        entry = ApprovalEntry(
            request_id=str(uuid4()),
            username=username,
            status="pending",
            requested_at=datetime.now(UTC).isoformat(),
        )
        self._approvals.save(entry)
        return entry

    def grant_approval(self, username: str) -> ApprovalEntry:
        approver = self._authenticated_username()
        permissions = self.get_permissions()
        if not permissions.approved:
            raise AuthorizationError("No tiene permiso para aprobar usuarios.")
        target = normalize_username(username)
        if target == approver:
            raise ApprovalError("No puede aprobar su propio usuario.")
        if not self._users.exists(target):
            raise ApprovalError("El usuario solicitado no existe localmente.")
        existing = self._approvals.find_username(target)
        if existing is not None and existing.status == "approved":
            return existing
        now = datetime.now(UTC).isoformat()
        entry = ApprovalEntry(
            request_id=existing.request_id if existing else str(uuid4()),
            username=target,
            status="approved",
            requested_at=existing.requested_at if existing else now,
            approved_at=now,
            approved_by=approver,
        )
        self._approvals.save(entry)
        return entry

    def grant_request(self, request_id: str) -> ApprovalEntry:
        entry = self._approvals.find_request(request_id)
        if entry is None:
            raise ApprovalError("La solicitud de aprobación no existe.")
        return self.grant_approval(entry.username)

    def list_requests(self) -> list[ApprovalEntry]:
        if not self.get_permissions().approved:
            raise AuthorizationError("No tiene permiso para consultar solicitudes.")
        return self._approvals.list_all()

    def get_permissions(self) -> UserPermissions:
        username = self._authenticated_username()
        owner = self._owner_username(required=False) == username
        entry = self._approvals.find_username(username)
        approved = owner or (entry is not None and entry.status == "approved")
        return UserPermissions(username=username, approved=approved, owner=owner)

    def require_approved(self) -> UserPermissions:
        permissions = self.get_permissions()
        if not permissions.approved:
            raise AuthorizationError(
                "Su usuario debe estar aprobado para acceder a datos compartidos."
            )
        return permissions

    def require_owner(self) -> UserPermissions:
        permissions = self.get_permissions()
        if not permissions.owner:
            raise AuthorizationError("Solo el propietario puede realizar esta acción.")
        return permissions

    def _authenticated_username(self) -> str:
        session = self._sessions.current_session
        if session is None:
            raise AuthorizationError("Debe iniciar sesión para realizar esta acción.")
        return session.username

    def _owner_username(self, *, required: bool) -> str | None:
        try:
            return load_owner_username(self._paths)
        except OwnerConfigurationError:
            if required:
                raise
            return None
