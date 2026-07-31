"""Application-update form that never executes commands itself."""

from __future__ import annotations

from collections.abc import Callable
from typing import Final

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QApplication,
    QFormLayout,
    QHBoxLayout,
    QLineEdit,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from frontend.contracts import UiResult, UpdateRequest
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

UpdateCallback = Callable[[UpdateRequest], UiResult]
ROUTE: Final = FrontendRoute.UPDATE


class UpdateView(QWidget):
    back_requested = Signal()
    logout_requested = Signal()
    error_requested = Signal(str)

    def __init__(
        self,
        settings: ApplicationSettings,
        style_manager: StyleManager,
        run_update: UpdateCallback,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.settings = settings
        self._run_update = run_update
        self._latest_error = settings.texts.messages["update_error"]
        self.setObjectName("updateView")
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
            PageTitle(self.settings.texts.screen_titles["update"], self.settings)
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
        self.username_input = QLineEdit()
        self.username_input.setObjectName("authenticatedUserInput")
        self.username_input.setReadOnly(True)
        self.username_input.setMinimumHeight(40)
        form.addRow(
            self.settings.texts.field_labels["authenticated_user"], self.username_input
        )
        self.update_name_input = QLineEdit()
        self.update_name_input.setPlaceholderText("Actualización local")
        self.update_name_input.setMinimumHeight(40)
        form.addRow(
            self.settings.texts.field_labels["update_name"], self.update_name_input
        )
        self.summary_text = QTextEdit()
        self.summary_text.setReadOnly(True)
        self.summary_text.setMinimumHeight(160)
        form.addRow(
            self.settings.texts.field_labels["pending_summary"], self.summary_text
        )
        panel_layout.addLayout(form)
        self.result_label = ResultBanner()
        self.result_label.setObjectName("updateResult")
        panel_layout.addWidget(self.result_label)
        buttons = QHBoxLayout()
        buttons.addStretch()
        self.back_button = QPushButton(self.settings.texts.button_labels["back"])
        self.back_button.setObjectName("secondaryButton")
        self.back_button.setMinimumSize(200, 56)
        self.back_button.clicked.connect(self.back_requested)
        buttons.addWidget(self.back_button)
        self.update_button = QPushButton(
            self.settings.texts.button_labels["run_update"]
        )
        self.update_button.setObjectName("primaryButton")
        self.update_button.setMinimumSize(200, 56)
        self.update_button.setEnabled(False)
        self.update_button.clicked.connect(self.submit)
        buttons.addWidget(self.update_button)
        panel_layout.addLayout(buttons)
        body.addWidget(panel, stretch=1)
        add_page_footer(
            body, self.settings, lambda: self.error_requested.emit(self._latest_error)
        )
        root.addLayout(body, stretch=1)
        self.update_name_input.textChanged.connect(self._refresh_state)

    def set_context(self, username: str, summary: str) -> None:
        self.header.username_label.setText(username)
        self.header.username_label.setVisible(bool(username))
        self.username_input.setText(username)
        self.summary_text.setPlainText(summary)
        self.result_label.clear_result()
        self._refresh_state()

    def _refresh_state(self) -> None:
        self.update_button.setEnabled(
            bool(self.username_input.text())
            and bool(self.update_name_input.text().strip())
        )

    def submit(self) -> None:
        if not self.update_button.isEnabled():
            return
        self._set_busy(True)
        QApplication.processEvents()
        try:
            result = self._run_update(
                UpdateRequest(self.username_input.text(), self.update_name_input.text())
            )
        finally:
            self._set_busy(False)
        self.result_label.present(result.message, success=result.success)
        if not result.success:
            self._latest_error = result.message

    def _set_busy(self, busy: bool) -> None:
        self.update_name_input.setEnabled(not busy)
        self.back_button.setEnabled(not busy)
        self.update_button.setText(
            "Actualizando…" if busy else self.settings.texts.button_labels["run_update"]
        )
        if busy:
            self.update_button.setEnabled(False)
        else:
            self._refresh_state()
