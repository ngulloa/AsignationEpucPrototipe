"""Stable route identifiers for the single-window frontend."""

from enum import StrEnum


class FrontendRoute(StrEnum):
    """Names used by frontend navigation without coupling views together."""

    LOGIN = "login"
    REGISTER = "register"
    MENU = "menu"
    ACADEMIC_LIST = "academic_list"
    ACADEMIC_FORM = "academic_form"
    APPROVAL = "approval"
    ERROR_NOTIFICATION = "error_notification"
    UPDATE = "update"
    ALERTS = "alerts"


LOGIN_SCREEN = FrontendRoute.LOGIN.value
REGISTER_SCREEN = FrontendRoute.REGISTER.value
MENU_SCREEN = FrontendRoute.MENU.value
ACADEMIC_LIST_SCREEN = FrontendRoute.ACADEMIC_LIST.value
ACADEMIC_FORM_SCREEN = FrontendRoute.ACADEMIC_FORM.value
APPROVAL_SCREEN = FrontendRoute.APPROVAL.value
ERROR_NOTIFICATION_SCREEN = FrontendRoute.ERROR_NOTIFICATION.value
UPDATE_SCREEN = FrontendRoute.UPDATE.value
ALERTS_SCREEN = FrontendRoute.ALERTS.value

ACTIVE_ROUTES = frozenset(FrontendRoute)
RESERVED_ROUTES: frozenset[FrontendRoute] = frozenset()
