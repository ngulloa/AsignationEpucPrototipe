"""Application views used by the frontend orchestrator."""

from frontend.views.academic_form_view import AcademicFormView
from frontend.views.academics_list_view import AcademicsListView
from frontend.views.login_view import LoginView
from frontend.views.main_menu_view import MainMenuView
from frontend.views.register_view import RegisterView

__all__ = [
    "AcademicFormView",
    "AcademicsListView",
    "LoginView",
    "MainMenuView",
    "RegisterView",
]
