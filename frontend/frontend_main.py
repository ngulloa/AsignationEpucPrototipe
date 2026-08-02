"""Single-window PySide6 frontend composed from the product views."""

from __future__ import annotations

from collections.abc import Callable, Iterable, Sequence

from PySide6.QtCore import QSize, Slot
from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import QMainWindow, QStackedWidget, QWidget

from backend.contracts import (
    AcademicFormData,
    AcademicListingError,
    AcademicRecord,
    SubmissionResult,
)
from frontend.async_worker import AsyncOperation
from frontend.contracts import SessionPresentation, UiResult
from frontend.controller import FrontendController
from frontend.navigation import (
    ACADEMIC_FORM_SCREEN,
    ACADEMIC_LIST_SCREEN,
    LOGIN_SCREEN,
    MENU_SCREEN,
    REGISTER_SCREEN,
)
from frontend.settings import ApplicationSettings
from frontend.style_manager import StyleManager
from frontend.views import (
    AcademicFormView,
    AcademicsListView,
    LoginView,
    MainMenuView,
    RegisterView,
)

SubmissionCallback = Callable[[AcademicFormData], SubmissionResult]
AcademicsProvider = Callable[[], Sequence[AcademicRecord]]


class MainWindow(QMainWindow):
    """Coordinate one instance of every reachable route."""

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
        self.academic_catalogs = self.controller.academic_catalogs()
        self.settings = settings
        self.style_manager = StyleManager(self.settings.visual)
        self._session = SessionPresentation("")
        self._sync_operation = AsyncOperation(self)
        self._sync_operation.succeeded.connect(self._complete_sync)
        self._sync_operation.failed.connect(self._fail_sync)
        self._sync_operation.finished.connect(self._finish_sync)
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
            self.academic_catalogs,
            self._submit_callback,
            update_callback=self.controller.update_academic,
        )
        self._views = {
            LOGIN_SCREEN: self.login_view,
            REGISTER_SCREEN: self.register_view,
            MENU_SCREEN: self.main_menu_view,
            ACADEMIC_LIST_SCREEN: self.academics_list_view,
            ACADEMIC_FORM_SCREEN: self.academic_form_view,
        }
        for view in self._views.values():
            self.stack.addWidget(view)

        self.style_manager.apply_interaction_defaults(self)
        self._connect_navigation()
        self.main_menu_view.set_session("")
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
        self.main_menu_view.download_requested.connect(self.download_information)
        self.main_menu_view.upload_requested.connect(self.upload_information)
        self.academics_list_view.menu_requested.connect(self.show_main_menu)
        self.academics_list_view.add_requested.connect(self.show_academic_form)
        self.academics_list_view.edit_requested.connect(self.show_academic_edit)
        self.academics_list_view.delete_requested.connect(self._delete_academic)
        self.academic_form_view.cancel_requested.connect(self.show_academics_list)
        self.academic_form_view.submission_succeeded.connect(
            self._handle_submission_success
        )
        for view in (
            self.main_menu_view,
            self.academics_list_view,
            self.academic_form_view,
        ):
            view.logout_requested.connect(self.logout)

    def show_login(self) -> None:
        self._show_screen(LOGIN_SCREEN)

    def show_registration(self) -> None:
        self._show_screen(REGISTER_SCREEN)

    def show_main_menu(self) -> None:
        self._show_screen(MENU_SCREEN)

    def show_academics_list(self) -> None:
        self._reload_academics()
        self._show_screen(ACADEMIC_LIST_SCREEN)

    def show_academic_form(self) -> None:
        self.academic_form_view.prepare_new()
        self._show_screen(ACADEMIC_FORM_SCREEN)

    def show_academic_edit(self, record: AcademicRecord) -> None:
        self.academic_form_view.prepare_edit(record)
        self._show_screen(ACADEMIC_FORM_SCREEN)

    def download_information(self) -> None:
        self._start_sync("download", self.controller.download_information)

    def upload_information(self) -> None:
        self._start_sync("upload", self.controller.upload_information)

    def _start_sync(self, operation: str, callback: Callable[[], UiResult]) -> None:
        if self._sync_operation.active:
            return
        self.main_menu_view.set_sync_busy(True, operation)
        if not self._sync_operation.start(callback):
            self.main_menu_view.set_sync_busy(False)

    @Slot(object)
    def _complete_sync(self, result: object) -> None:
        if not isinstance(result, UiResult):
            self._fail_sync("La respuesta de sincronización es inválida.")
            return
        self.main_menu_view.show_sync_result(
            result.message,
            success=result.success,
        )

    @Slot(str)
    def _fail_sync(self, message: str) -> None:
        self.main_menu_view.show_sync_result(message, success=False)

    @Slot()
    def _finish_sync(self) -> None:
        self.main_menu_view.set_sync_busy(False)

    def logout(self) -> None:
        self.controller.logout()
        self._session = SessionPresentation("")
        self.login_view.reset()
        self.main_menu_view.set_session("")
        self.academics_list_view.set_session("")
        self.academic_form_view.set_session("")
        self._show_screen(LOGIN_SCREEN, force_reference_size=True)

    def _handle_authenticated(self, username: str) -> None:
        self._session = SessionPresentation(username)
        self.main_menu_view.set_session(username)
        self.academics_list_view.set_session(username)
        self.academic_form_view.set_session(username)
        self.show_main_menu()

    def _handle_registration_success(self, _message: str, username: str) -> None:
        self._handle_authenticated(username)

    def _show_screen(
        self,
        screen_name: str,
        *,
        force_reference_size: bool = False,
    ) -> None:
        self.academics_list_view.reset_delete_confirmation()
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
        listing_error = self._reload_academics()
        if listing_error is None:
            self.academics_list_view.show_result(message, success=True)
        else:
            self.academics_list_view.show_result(
                f"{message} {listing_error}",
                success=False,
            )
        self._show_screen(ACADEMIC_LIST_SCREEN)

    @Slot(str)
    def _delete_academic(self, academic_id: str) -> None:
        result = self.controller.delete_academic(academic_id)
        if not result.success:
            self.academics_list_view.reset_delete_confirmation()
            self.academics_list_view.show_result(result.message, success=False)
            return
        listing_error = self._reload_academics()
        if listing_error is None:
            self.academics_list_view.show_result(result.message, success=True)
        else:
            self.academics_list_view.show_result(
                f"{result.message} {listing_error}",
                success=False,
            )

    def closeEvent(self, event: QCloseEvent) -> None:
        if self._sync_operation.active:
            self.main_menu_view.show_sync_result(
                "Espere a que termine la sincronización antes de cerrar.",
                success=False,
            )
            event.ignore()
            return
        super().closeEvent(event)


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
