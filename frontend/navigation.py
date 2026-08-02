"""Stable route identifiers for the single-window frontend."""

from enum import StrEnum


class FrontendRoute(StrEnum):
    """Names used by frontend navigation without coupling views together."""

    LOGIN = "login"
    REGISTER = "register"
    MENU = "menu"
    ACADEMIC_LIST = "academic_list"
    ACADEMIC_FORM = "academic_form"


LOGIN_SCREEN = FrontendRoute.LOGIN.value
REGISTER_SCREEN = FrontendRoute.REGISTER.value
MENU_SCREEN = FrontendRoute.MENU.value
ACADEMIC_LIST_SCREEN = FrontendRoute.ACADEMIC_LIST.value
ACADEMIC_FORM_SCREEN = FrontendRoute.ACADEMIC_FORM.value

ACTIVE_ROUTES = frozenset(FrontendRoute)
RESERVED_ROUTES: frozenset[FrontendRoute] = frozenset()
