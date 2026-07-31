"""Application views used by the frontend orchestrator."""

from frontend.views.academic_form_view import AcademicFormView
from frontend.views.academics_list_view import AcademicsListView
from frontend.views.alerts_view import AlertsView
from frontend.views.approval_view import ApprovalView
from frontend.views.error_notification_view import ErrorNotificationView
from frontend.views.login_view import LoginView
from frontend.views.main_menu_view import MainMenuView
from frontend.views.register_view import RegisterView
from frontend.views.update_view import UpdateView

__all__ = [
    "AcademicFormView",
    "AcademicsListView",
    "AlertsView",
    "ApprovalView",
    "ErrorNotificationView",
    "LoginView",
    "MainMenuView",
    "RegisterView",
    "UpdateView",
]
