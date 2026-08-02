"""Inicio view with exactly five vertically ordered actions."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QFrame, QLabel, QPushButton, QVBoxLayout, QWidget

from frontend.settings import ApplicationSettings
from frontend.style_manager import StyleManager
from frontend.widgets import AppHeader, ResultBanner, Surface


class MainMenuView(QWidget):
    academics_requested = Signal()
    download_requested = Signal()
    upload_requested = Signal()
    logout_requested = Signal()

    def __init__(
        self,
        settings: ApplicationSettings,
        style_manager: StyleManager,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.settings = settings
        self._style_manager = style_manager
        self.setObjectName("mainMenuView")
        self._build_ui()

    def _build_ui(self) -> None:
        visual = self.settings.visual
        texts = self.settings.texts
        spacing = visual.spacing

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        self.header = AppHeader(
            self.settings,
            compact=True,
            show_logout=True,
        )
        self.header.logout_requested.connect(self.logout_requested)
        root.addWidget(self.header)

        body = QVBoxLayout()
        body.setContentsMargins(
            visual.margins["section"],
            spacing["large"],
            visual.margins["section"],
            spacing["large"],
        )
        body.setSpacing(spacing["medium"])

        title = QLabel(texts.screen_titles["menu"].upper())
        title.setObjectName("screenTitle")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title.setWordWrap(True)
        title.setFixedHeight(128)
        title.setMaximumWidth(620)
        body.addWidget(title, alignment=Qt.AlignmentFlag.AlignHCenter)

        accent = QFrame()
        accent.setObjectName("accent")
        accent.setFixedSize(
            visual.margins["page"] + visual.margins["section"],
            spacing["extra_small"],
        )
        body.addWidget(accent, alignment=Qt.AlignmentFlag.AlignHCenter)

        panel = Surface(self._style_manager)
        panel.setMaximumWidth(560)
        panel_layout = QVBoxLayout(panel)
        panel_layout.setContentsMargins(
            visual.margins["section"],
            spacing["medium"],
            visual.margins["section"],
            spacing["medium"],
        )
        panel_layout.setSpacing(spacing["small"])

        self.assign_load_button = self._menu_button(
            texts.button_labels["assign_load"],
            enabled=False,
        )
        self.academics_button = self._menu_button(
            texts.button_labels["open_academics"],
            primary=True,
        )
        self.assignments_button = self._menu_button(
            texts.button_labels["assignments"],
            enabled=False,
        )
        self.download_button = self._menu_button(
            texts.button_labels["download_information"]
        )
        self.upload_button = self._menu_button(
            texts.button_labels["upload_information"]
        )
        self.action_buttons = (
            self.assign_load_button,
            self.academics_button,
            self.assignments_button,
            self.download_button,
            self.upload_button,
        )
        unavailable = texts.out_of_scope_function_texts["menu_features"]
        self.assign_load_button.setToolTip(unavailable)
        self.assignments_button.setToolTip(unavailable)
        for button in self.action_buttons:
            panel_layout.addWidget(button)

        self.sync_message = ResultBanner()
        self.sync_message.setMinimumHeight(48)
        self.sync_message.show()
        panel_layout.addWidget(self.sync_message)

        self.academics_button.clicked.connect(self.academics_requested)
        self.download_button.clicked.connect(self._request_download)
        self.upload_button.clicked.connect(self._request_upload)

        body.addWidget(panel, alignment=Qt.AlignmentFlag.AlignHCenter)
        body.addStretch(1)
        root.addLayout(body, stretch=1)

    def set_session(self, username: str) -> None:
        self.header.username_label.setText(username)
        self.header.username_label.setVisible(bool(username))
        self.sync_message.clear_result()
        self.sync_message.show()

    def _request_download(self) -> None:
        self.download_requested.emit()

    def _request_upload(self) -> None:
        self.upload_requested.emit()

    def set_sync_busy(self, busy: bool, operation: str = "") -> None:
        """Keep geometry stable while preventing overlapping actions."""
        for button in self.action_buttons:
            button.setEnabled(
                not busy
                and button not in (self.assign_load_button, self.assignments_button)
            )
        self.header.logout_button.setEnabled(not busy)
        self.download_button.setText(
            "Bajando información…"
            if busy and operation == "download"
            else self.settings.texts.button_labels["download_information"]
        )
        self.upload_button.setText(
            "Subiendo información…"
            if busy and operation == "upload"
            else self.settings.texts.button_labels["upload_information"]
        )
        if busy:
            self.sync_message.present(
                self.settings.texts.messages["sync_in_progress"],
                success=True,
            )

    def show_sync_result(self, message: str, *, success: bool) -> None:
        self.sync_message.present(message, success=success)

    @staticmethod
    def _menu_button(
        label: str,
        *,
        primary: bool = False,
        enabled: bool = True,
    ) -> QPushButton:
        button = QPushButton(label)
        button.setObjectName("primaryButton" if primary else "secondaryButton")
        button.setProperty("sizeRole", "large")
        button.setMinimumSize(320, 52)
        button.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        button.setEnabled(enabled)
        return button
