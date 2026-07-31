"""Single-window PySide6 frontend composed with injectable presentation contracts."""

from __future__ import annotations

from collections.abc import Callable, Iterable, Sequence

from PySide6.QtCore import QSize
from PySide6.QtWidgets import QMainWindow, QStackedWidget, QWidget

from backend.contracts import (
    AcademicFormData,
    AcademicListingError,
    AcademicRecord,
    SubmissionResult,
)
from frontend.contracts import SessionPresentation
from frontend.controller import FrontendController
from frontend.navigation import (
    ACADEMIC_FORM_SCREEN,
    ACADEMIC_LIST_SCREEN,
    ALERTS_SCREEN,
    APPROVAL_SCREEN,
    ERROR_NOTIFICATION_SCREEN,
    LOGIN_SCREEN,
    MENU_SCREEN,
    REGISTER_SCREEN,
    UPDATE_SCREEN,
)
from frontend.settings import ApplicationSettings
from frontend.style_manager import StyleManager
from frontend.views import (
    AcademicFormView,
    AcademicsListView,
    AlertsView,
    ApprovalView,
    ErrorNotificationView,
    LoginView,
    MainMenuView,
    RegisterView,
    UpdateView,
)

SubmissionCallback = Callable[[AcademicFormData], SubmissionResult]
AcademicsProvider = Callable[[], Sequence[AcademicRecord]]


class MainWindow(QMainWindow):
    """The sole top-level window, coordinating one instance of every page."""

    def __init__(
        self,
        controller: FrontendController,
        settings: ApplicationSettings,
        submit_callback: SubmissionCallback | None = None,
        academics: Iterable[AcademicRecord] = (),
        academics_provider: AcademicsProvider | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        initial_academics = tuple(academics)
        self.controller = controller
        self._submit_callback = submit_callback or self.controller.submit_academic
        self._academics_provider = academics_provider or self.controller.list_academics
        self.settings = settings
        self.style_manager = StyleManager(self.settings.visual)
        self._session = SessionPresentation("", False, False)
        self._error_return_screen = LOGIN_SCREEN
        self._editing_shared_table = False
        self._last_reference_size: QSize | None = None
        self.setObjectName("appRoot")
        self.setWindowTitle(self.settings.texts.application_name)
        self.setFont(self.style_manager.base_font())
        self.setStyleSheet(self.style_manager.stylesheet())
        self.setMinimumSize(720, 600)

        self.stack = QStackedWidget()
        self.setCentralWidget(self.stack)
        self.login_view = LoginView(
            self.settings,
            self.style_manager,
            self.controller.authenticate,
        )
        self.register_view = RegisterView(
            self.settings,
            self.style_manager,
            self.controller.register_user,
        )
        self.main_menu_view = MainMenuView(self.settings, self.style_manager)
        self.academics_list_view = AcademicsListView(
            self.settings,
            self.style_manager,
            initial_academics,
        )
        self.academic_form_view = AcademicFormView(
            self.settings,
            self.style_manager,
            self._submit_callback,
            update_callback=self.controller.update_academic,
        )
        self.approval_view = ApprovalView(
            self.settings,
            self.style_manager,
            self.controller.approve_user,
        )
        self.error_notification_view = ErrorNotificationView(
            self.settings,
            self.style_manager,
            self.controller.notify_error,
        )
        self.update_view = UpdateView(
            self.settings,
            self.style_manager,
            self.controller.run_update,
        )
        self.alerts_view = AlertsView(self.settings, self.style_manager)
        self._views = {
            LOGIN_SCREEN: self.login_view,
            REGISTER_SCREEN: self.register_view,
            MENU_SCREEN: self.main_menu_view,
            ACADEMIC_LIST_SCREEN: self.academics_list_view,
            ACADEMIC_FORM_SCREEN: self.academic_form_view,
            APPROVAL_SCREEN: self.approval_view,
            ERROR_NOTIFICATION_SCREEN: self.error_notification_view,
            UPDATE_SCREEN: self.update_view,
            ALERTS_SCREEN: self.alerts_view,
        }
        for view in self._views.values():
            self.stack.addWidget(view)

        self._connect_navigation()
        self.main_menu_view.set_session("", is_owner=False)
        self._show_screen(LOGIN_SCREEN, force_reference_size=True)

    @property
    def current_screen(self) -> str:
        current = self.stack.currentWidget()
        return next(name for name, view in self._views.items() if view is current)

    @property
    def authenticated_username(self) -> str:
        return self._session.username

    def _connect_navigation(self) -> None:
        self.login_view.authenticated.connect(self._handle_authenticated)
        self.login_view.registration_requested.connect(self.show_registration)
        self.register_view.back_requested.connect(self.show_login)
        self.register_view.registration_succeeded.connect(
            self._handle_registration_success
        )
        self.main_menu_view.academics_requested.connect(self.show_academics_list)
        self.main_menu_view.approvals_requested.connect(self.show_approvals)
        self.main_menu_view.update_requested.connect(self.show_update)
        self.main_menu_view.alerts_requested.connect(self.show_alerts)
        self.academics_list_view.menu_requested.connect(self.show_main_menu)
        self.academics_list_view.add_requested.connect(self.show_academic_form)
        self.academics_list_view.edit_requested.connect(self.show_academic_edit)
        self.academics_list_view.shared_edit_requested.connect(
            self.show_shared_academic_edit
        )
        self.academic_form_view.cancel_requested.connect(self.show_academics_list)
        self.academic_form_view.submission_succeeded.connect(
            self._handle_submission_success
        )
        self.approval_view.back_requested.connect(self.show_main_menu)
        self.update_view.back_requested.connect(self.show_main_menu)
        self.alerts_view.back_requested.connect(self.show_main_menu)
        self.error_notification_view.back_requested.connect(self._return_from_error)

        authenticated_views = (
            self.main_menu_view,
            self.academics_list_view,
            self.academic_form_view,
            self.approval_view,
            self.error_notification_view,
            self.update_view,
            self.alerts_view,
        )
        for view in authenticated_views:
            view.logout_requested.connect(self.logout)

        error_sources = (
            self.login_view,
            self.register_view,
            self.main_menu_view,
            self.academics_list_view,
            self.academic_form_view,
            self.approval_view,
            self.error_notification_view,
            self.update_view,
            self.alerts_view,
        )
        for view in error_sources:
            view.error_requested.connect(self.show_error_notification)

    def show_login(self) -> None:
        self._show_screen(LOGIN_SCREEN)

    def show_registration(self) -> None:
        self._show_screen(REGISTER_SCREEN)

    def show_main_menu(self) -> None:
        self._show_screen(MENU_SCREEN)

    def show_academics_list(self) -> None:
        self._reload_academics()
        self._reload_shared_tables()
        self._show_screen(ACADEMIC_LIST_SCREEN)

    def _reload_shared_tables(self) -> str | None:
        try:
            self.academics_list_view.set_shared_tables(
                self.controller.list_shared_tables()
            )
        except (RuntimeError, ValueError) as error:
            self.academics_list_view.set_shared_tables(())
            self.academics_list_view.show_result(str(error), success=False)
            return str(error)
        return None

    def show_academic_form(self) -> None:
        self._editing_shared_table = False
        self.academic_form_view.prepare_new()
        self._show_screen(ACADEMIC_FORM_SCREEN)

    def show_academic_edit(self, record: AcademicRecord) -> None:
        self._editing_shared_table = False
        self.academic_form_view.prepare_edit(record)
        self._show_screen(ACADEMIC_FORM_SCREEN)

    def show_shared_academic_edit(
        self,
        table_number: int,
        record: AcademicRecord,
    ) -> None:
        self._editing_shared_table = True

        def update_shared(
            academic_id: str,
            data: AcademicFormData,
        ) -> SubmissionResult:
            return self.controller.update_shared_academic(
                table_number,
                academic_id,
                data,
            )

        self.academic_form_view.prepare_edit(record, update_callback=update_shared)
        self._show_screen(ACADEMIC_FORM_SCREEN)

    def show_approvals(self) -> None:
        try:
            items = self.controller.list_approvals()
        except (RuntimeError, ValueError) as error:
            self.approval_view.set_items(())
            self.approval_view.show_result(str(error), success=False)
        else:
            self.approval_view.set_items(items)
        self._show_screen(APPROVAL_SCREEN)

    def show_update(self) -> None:
        self.update_view.set_context(
            self._session.username,
            self.controller.pending_update_summary(),
        )
        self._show_screen(UPDATE_SCREEN)

    def show_alerts(self) -> None:
        try:
            alerts = self.controller.list_owner_alerts()
        except (RuntimeError, ValueError) as error:
            self.alerts_view.set_alerts(())
            self.alerts_view.show_error(str(error))
        else:
            self.alerts_view.set_alerts(alerts)
        self._show_screen(ALERTS_SCREEN)

    def show_error_notification(self, error: str = "") -> None:
        origin = self.current_screen
        if origin != ERROR_NOTIFICATION_SCREEN:
            self._error_return_screen = origin
        self.error_notification_view.prepare(
            origin,
            self.settings.texts.screen_titles.get(origin, origin),
            error,
        )
        self._show_screen(ERROR_NOTIFICATION_SCREEN)

    def logout(self) -> None:
        self.controller.logout()
        self._session = SessionPresentation("", False, False)
        self.login_view.reset()
        self._show_screen(LOGIN_SCREEN, force_reference_size=True)

    def _handle_authenticated(
        self,
        username: str,
        is_owner: bool,
        is_approved: bool,
    ) -> None:
        self._session = SessionPresentation(username, is_owner, is_approved)
        self.main_menu_view.set_session(
            username,
            is_owner=is_owner,
            can_approve=is_approved,
        )
        self.academics_list_view.set_session(username)
        self.academics_list_view.set_shared_edit_permission(is_approved)
        self.academic_form_view.set_session(username)
        self.approval_view.set_session(username)
        self.alerts_view.set_session(username)
        self.show_main_menu()

    def _handle_registration_success(self, message: str) -> None:
        self.login_view.present_message(message, success=True)
        self.show_login()

    def _return_from_error(self) -> None:
        self._show_screen(self._error_return_screen)

    def _show_screen(
        self, screen_name: str, *, force_reference_size: bool = False
    ) -> None:
        dimensions = self.settings.visual.screens[screen_name]
        reference_size = QSize(dimensions.width, dimensions.height)
        follows_reference = (
            force_reference_size
            or self._last_reference_size is None
            or self.size() == self._last_reference_size
        )
        self.stack.setCurrentWidget(self._views[screen_name])
        if follows_reference:
            self.resize(reference_size)
        self._last_reference_size = reference_size

    def _reload_academics(self) -> str | None:
        self.academics_list_view.clear_result()
        try:
            academics = self._academics_provider()
        except AcademicListingError as error:
            message = str(error)
            self.academics_list_view.set_academics(())
            self.academics_list_view.show_result(message, success=False)
            return message
        self.academics_list_view.set_academics(academics)
        return None

    def _handle_submission_success(self, message: str) -> None:
        listing_error = (
            self._reload_shared_tables()
            if self._editing_shared_table
            else self._reload_academics()
        )
        if listing_error is None:
            self.academics_list_view.show_result(message, success=True)
        else:
            self.academics_list_view.show_result(
                f"{message} {listing_error}", success=False
            )
        self._show_screen(ACADEMIC_LIST_SCREEN)


def build_frontend_window(
    controller: FrontendController,
    settings: ApplicationSettings,
    submit_callback: SubmissionCallback | None = None,
    academics: Iterable[AcademicRecord] = (),
    academics_provider: AcademicsProvider | None = None,
) -> MainWindow:
    """Build, but do not show, the frontend using only injected contracts."""
    return MainWindow(
        controller=controller,
        settings=settings,
        submit_callback=submit_callback,
        academics=academics,
        academics_provider=academics_provider,
    )
