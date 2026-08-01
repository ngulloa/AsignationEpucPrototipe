"""User-registration presentation with no persistence or permission decisions."""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from frontend.contracts import RegistrationRequest, UiResult
from frontend.settings import ApplicationSettings
from frontend.style_manager import StyleManager
from frontend.widgets import (
    AppHeader,
    PageTitle,
    ResultBanner,
    Surface,
    add_page_footer,
)

RegistrationCallback = Callable[[RegistrationRequest], UiResult]


class RegisterView(QWidget):
    back_requested = Signal()
    registration_succeeded = Signal(str)
    error_requested = Signal(str)

    def __init__(
        self,
        settings: ApplicationSettings,
        style_manager: StyleManager,
        register_user: RegistrationCallback,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.settings = settings
        self._register_user = register_user
        self._latest_error = "Error de registro."
        self.field_error_labels: dict[str, QLabel] = {}
        self.setObjectName("registerView")
        self._build_ui(style_manager)

    def _build_ui(self, style_manager: StyleManager) -> None:
        visual = self.settings.visual
        texts = self.settings.texts
        spacing = visual.spacing
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        root.addWidget(AppHeader(self.settings, centered=True))

        body = QVBoxLayout()
        body.setContentsMargins(
            visual.margins["page"],
            spacing["large"],
            visual.margins["page"],
            visual.margins["section"],
        )
        body.setSpacing(spacing["medium"])
        body.addWidget(PageTitle(texts.screen_titles["register"], self.settings))

        panel = Surface(style_manager)
        panel.setMaximumWidth(
            visual.screens["register"].width - visual.margins["page"] * 2
        )
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
        form.setVerticalSpacing(spacing["small"])

        self.username_input = self._line_edit()
        form.addRow(texts.field_labels["username"], self.username_input)
        self.password_input = self._password_edit()
        form.addRow(
            texts.field_labels["password"], self._with_hint(self.password_input)
        )
        self.confirmation_input = self._password_edit()
        confirmation_box = QVBoxLayout()
        confirmation_box.setSpacing(spacing["extra_small"])
        confirmation_box.addWidget(self.confirmation_input)
        confirmation_error = QLabel()
        confirmation_error.setObjectName("errorLabel")
        confirmation_error.setWordWrap(True)
        confirmation_error.hide()
        confirmation_box.addWidget(confirmation_error)
        self.field_error_labels["password_confirmation"] = confirmation_error
        form.addRow(texts.field_labels["password_confirmation"], confirmation_box)
        panel_layout.addLayout(form)

        self.result_label = ResultBanner()
        panel_layout.addWidget(self.result_label)
        buttons = QHBoxLayout()
        buttons.setSpacing(spacing["medium"])
        self.back_button = QPushButton(texts.button_labels["back_to_login"])
        self.back_button.setObjectName("secondaryButton")
        self.back_button.setMinimumSize(200, 48)
        self.back_button.clicked.connect(self.back_requested)
        buttons.addWidget(self.back_button)
        self.register_button = QPushButton(texts.button_labels["register"])
        self.register_button.setObjectName("primaryButton")
        self.register_button.setMinimumSize(200, 48)
        self.register_button.setEnabled(False)
        self.register_button.clicked.connect(self.submit)
        buttons.addWidget(self.register_button)
        panel_layout.addLayout(buttons)

        body.addWidget(panel, stretch=1, alignment=Qt.AlignmentFlag.AlignHCenter)
        self.error_footer = add_page_footer(body, self.settings, self._request_error)
        self.error_footer.hide()
        root.addLayout(body, stretch=1)
        for control in (
            self.username_input,
            self.password_input,
            self.confirmation_input,
        ):
            control.textChanged.connect(self._refresh_submit_state)

    def _line_edit(self) -> QLineEdit:
        edit = QLineEdit()
        edit.setMinimumHeight(
            self.settings.visual.spacing["large"]
            + self.settings.visual.spacing["medium"]
        )
        return edit

    def _password_edit(self) -> QLineEdit:
        edit = self._line_edit()
        edit.setEchoMode(QLineEdit.EchoMode.Password)
        edit.setMaxLength(8)
        return edit

    def _with_hint(self, edit: QLineEdit) -> QVBoxLayout:
        layout = QVBoxLayout()
        layout.setSpacing(self.settings.visual.spacing["extra_small"])
        layout.addWidget(edit)
        hint = QLabel(self.settings.texts.messages["password_hint"])
        hint.setObjectName("helperText")
        layout.addWidget(hint)
        return layout

    def _refresh_submit_state(self) -> None:
        lengths_are_valid = all(
            4 <= len(control.text()) <= 8
            for control in (self.password_input, self.confirmation_input)
        )
        self.register_button.setEnabled(
            bool(self.username_input.text().strip()) and lengths_are_valid
        )

    def submit(self) -> None:
        if not self.register_button.isEnabled():
            return
        self._clear_errors()
        result = self._register_user(
            RegistrationRequest(
                self.username_input.text(),
                self.password_input.text(),
                self.confirmation_input.text(),
            )
        )
        self.result_label.present(result.message, success=result.success)
        for name, message in result.field_errors.items():
            if name in self.field_error_labels:
                self.field_error_labels[name].setText(message)
                self.field_error_labels[name].show()
        if result.success:
            self.registration_succeeded.emit(result.message)
        else:
            self._latest_error = result.message

    def _clear_errors(self) -> None:
        self.result_label.clear_result()
        for label in self.field_error_labels.values():
            label.clear()
            label.hide()

    def _request_error(self) -> None:
        self.error_requested.emit(self._latest_error)
