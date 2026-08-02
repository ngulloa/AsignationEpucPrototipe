"""Login presentation driven only by an injected authentication callback."""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from frontend.contracts import AuthenticationResult, LoginRequest
from frontend.settings import ApplicationSettings
from frontend.style_manager import StyleManager
from frontend.widgets import (
    AppHeader,
    PageTitle,
    ResultBanner,
    Surface,
)

AuthenticationCallback = Callable[[LoginRequest], AuthenticationResult]


class LoginView(QWidget):
    authenticated = Signal(str)
    registration_requested = Signal()

    def __init__(
        self,
        settings: ApplicationSettings,
        style_manager: StyleManager,
        authenticate: AuthenticationCallback,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.settings = settings
        self._authenticate = authenticate
        self.setObjectName("loginView")
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
            visual.margins["page"],
            visual.margins["page"],
            visual.margins["section"],
        )
        body.setSpacing(spacing["large"])
        body.addWidget(
            PageTitle(texts.screen_titles["login"], self.settings),
            alignment=self._center(),
        )

        panel = Surface(style_manager)
        panel.setMaximumWidth(
            visual.screens["login"].width - visual.margins["page"] * 2
        )
        panel_layout = QVBoxLayout(panel)
        panel_layout.setContentsMargins(
            visual.margins["page"],
            visual.margins["page"],
            visual.margins["page"],
            visual.margins["page"],
        )
        panel_layout.setSpacing(spacing["large"])

        form = QFormLayout()
        form.setHorizontalSpacing(spacing["large"])
        form.setVerticalSpacing(spacing["medium"])
        self.username_input = QLineEdit()
        self.username_input.setObjectName("usernameInput")
        self.username_input.setMinimumHeight(spacing["large"] + spacing["medium"])
        form.addRow(texts.field_labels["username"], self.username_input)

        password_box = QVBoxLayout()
        password_box.setSpacing(spacing["extra_small"])
        self.password_input = QLineEdit()
        self.password_input.setObjectName("passwordInput")
        self.password_input.setEchoMode(QLineEdit.EchoMode.Password)
        self.password_input.setMaxLength(8)
        self.password_input.setMinimumHeight(spacing["large"] + spacing["medium"])
        password_box.addWidget(self.password_input)
        hint = QLabel(texts.messages["password_hint"])
        hint.setObjectName("helperText")
        password_box.addWidget(hint)
        form.addRow(texts.field_labels["password"], password_box)
        panel_layout.addLayout(form)

        self.result_label = ResultBanner()
        panel_layout.addWidget(self.result_label)

        buttons = QHBoxLayout()
        buttons.setSpacing(spacing["medium"])
        self.register_button = QPushButton(texts.button_labels["create_account"])
        self.register_button.setObjectName("secondaryButton")
        self.register_button.setMinimumSize(200, 48)
        self.register_button.clicked.connect(self.registration_requested)
        buttons.addWidget(self.register_button)
        self.login_button = QPushButton(texts.button_labels["login"])
        self.login_button.setObjectName("primaryButton")
        self.login_button.setMinimumSize(200, 48)
        self.login_button.setEnabled(False)
        self.login_button.clicked.connect(self.submit)
        buttons.addWidget(self.login_button)
        panel_layout.addLayout(buttons)

        body.addWidget(panel, stretch=1, alignment=self._center())
        root.addLayout(body, stretch=1)

        self.username_input.textChanged.connect(self._refresh_submit_state)
        self.password_input.textChanged.connect(self._refresh_submit_state)
        self.password_input.returnPressed.connect(self.submit)

    @staticmethod
    def _center():
        from PySide6.QtCore import Qt

        return Qt.AlignmentFlag.AlignHCenter

    def _refresh_submit_state(self) -> None:
        password_length = len(self.password_input.text())
        self.login_button.setEnabled(
            bool(self.username_input.text().strip()) and 4 <= password_length <= 8
        )

    def submit(self) -> None:
        if not self.login_button.isEnabled():
            return
        result = self._authenticate(
            LoginRequest(self.username_input.text(), self.password_input.text())
        )
        self.result_label.present(result.message, success=result.success)
        if result.success:
            self.password_input.clear()
            self.authenticated.emit(result.username)

    def present_message(self, message: str, *, success: bool) -> None:
        self.result_label.present(message, success=success)

    def reset(self) -> None:
        self.username_input.clear()
        self.password_input.clear()
        self.result_label.clear_result()
