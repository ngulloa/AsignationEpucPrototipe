"""Structured error notification form with only predefined safe options."""

from __future__ import annotations

from collections.abc import Callable
from typing import Final

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QComboBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from backend.academic_service import DUPLICATE_RUT_MESSAGE
from backend.system_contracts import DESCRIPTION_PRIVACY_WARNING
from frontend.contracts import ErrorNotificationRequest, UiResult
from frontend.navigation import FrontendRoute
from frontend.settings import ApplicationSettings
from frontend.style_manager import StyleManager
from frontend.widgets import (
    AppHeader,
    PageTitle,
    ResultBanner,
    Surface,
    add_page_footer,
)

NotificationCallback = Callable[[ErrorNotificationRequest], UiResult]
ROUTE: Final = FrontendRoute.ERROR_NOTIFICATION
ERROR_OPTIONS: Final = (
    ("Error al guardar.", "persistence", "SAVE_ERROR"),
    (DUPLICATE_RUT_MESSAGE, "validation", "DUPLICATE_RUT"),
    ("Rut inválido.", "validation", "INVALID_RUT"),
    ("Error de autenticación.", "authentication", "AUTH_ERROR"),
    ("Error de actualización.", "synchronization", "UPDATE_ERROR"),
    ("Acceso denegado.", "authorization", "ACCESS_DENIED"),
    ("Otro error", "unexpected", "OTHER_ERROR"),
)


class ErrorNotificationView(QWidget):
    back_requested = Signal()
    logout_requested = Signal()
    error_requested = Signal(str)

    def __init__(
        self,
        settings: ApplicationSettings,
        style_manager: StyleManager,
        notify_error: NotificationCallback,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.settings = settings
        self._notify_error = notify_error
        self._source_screen = FrontendRoute.ERROR_NOTIFICATION.value
        self._latest_error = "Error al preparar la notificación."
        self.setObjectName("errorNotificationView")
        self._build_ui(style_manager)

    def _build_ui(self, style_manager: StyleManager) -> None:
        visual = self.settings.visual
        spacing = visual.spacing
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        self.header = AppHeader(self.settings, username="usuario", show_logout=True)
        self.header.logout_requested.connect(self.logout_requested)
        root.addWidget(self.header)
        body = QVBoxLayout()
        body.setContentsMargins(
            visual.margins["page"] + spacing["medium"],
            spacing["large"],
            visual.margins["page"] + spacing["medium"],
            spacing["medium"],
        )
        body.setSpacing(spacing["medium"])
        body.addWidget(
            PageTitle(
                self.settings.texts.screen_titles["error_notification"], self.settings
            )
        )
        panel = Surface(style_manager)
        panel_layout = QVBoxLayout(panel)
        panel_layout.setContentsMargins(
            visual.margins["page"],
            spacing["large"],
            visual.margins["page"],
            spacing["large"],
        )
        panel_layout.setSpacing(spacing["medium"])
        form = QFormLayout()
        form.setHorizontalSpacing(spacing["large"])
        form.setVerticalSpacing(spacing["medium"])
        self.source_input = QLineEdit()
        self.source_input.setReadOnly(True)
        self.error_type_combo = QComboBox()
        for label, category, code in ERROR_OPTIONS:
            self.error_type_combo.addItem(label, (category, code))
        for control in (self.source_input, self.error_type_combo):
            control.setMinimumHeight(40)
        form.addRow(self.settings.texts.field_labels["error_source"], self.source_input)
        form.addRow(
            self.settings.texts.field_labels["error_type"], self.error_type_combo
        )
        description_box = QVBoxLayout()
        description_box.setSpacing(spacing["extra_small"])
        self.description_input = QTextEdit()
        self.description_input.setMaximumHeight(150)
        self.description_input.setPlaceholderText(
            "Describa qué ocurrió y qué esperaba que sucediera."
        )
        description_box.addWidget(self.description_input)
        self.description_warning = QLabel(DESCRIPTION_PRIVACY_WARNING)
        self.description_warning.setObjectName("helperText")
        self.description_warning.setWordWrap(True)
        description_box.addWidget(self.description_warning)
        form.addRow("Descripción", description_box)
        panel_layout.addLayout(form)
        panel_layout.addStretch()
        self.result_label = ResultBanner()
        panel_layout.addWidget(self.result_label)
        buttons = QHBoxLayout()
        buttons.addStretch()
        self.back_button = QPushButton(self.settings.texts.button_labels["back"])
        self.back_button.setObjectName("secondaryButton")
        self.back_button.setMinimumSize(200, 56)
        self.back_button.clicked.connect(self.back_requested)
        buttons.addWidget(self.back_button)
        self.send_button = QPushButton(self.settings.texts.button_labels["send"])
        self.send_button.setObjectName("primaryButton")
        self.send_button.setMinimumSize(220, 56)
        self.send_button.clicked.connect(self.submit)
        buttons.addWidget(self.send_button)
        panel_layout.addLayout(buttons)
        body.addWidget(panel, stretch=1)
        add_page_footer(
            body, self.settings, lambda: self.error_requested.emit(self._latest_error)
        )
        root.addLayout(body, stretch=1)

    def prepare(self, source_screen: str, source_title: str, error: str = "") -> None:
        self._source_screen = source_screen
        self.source_input.setText(source_title)
        normalized = error.strip()
        labels = [option[0] for option in ERROR_OPTIONS]
        self.error_type_combo.setCurrentIndex(
            labels.index(normalized) if normalized in labels else len(labels) - 1
        )
        self.result_label.clear_result()
        self.description_input.clear()
        if normalized:
            self._latest_error = normalized

    def submit(self) -> None:
        category, code = self.error_type_combo.currentData()
        result = self._notify_error(
            ErrorNotificationRequest(
                source_screen=self._source_screen,
                category=str(category),
                error_code=str(code),
                description=self.description_input.toPlainText(),
            )
        )
        self.result_label.present(result.message, success=result.success)
        if not result.success:
            self._latest_error = result.message
