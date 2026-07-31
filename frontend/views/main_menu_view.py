"""Main menu view using the shared institutional visual system."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFrame,
    QGridLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from frontend.settings import ApplicationSettings
from frontend.style_manager import StyleManager
from frontend.widgets import AppHeader, Surface, add_page_footer


class MainMenuView(QWidget):
    academics_requested = Signal()
    approvals_requested = Signal()
    update_requested = Signal()
    alerts_requested = Signal()
    logout_requested = Signal()
    error_requested = Signal(str)

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
            username="usuario",
            show_logout=True,
        )
        self.header.logout_requested.connect(self.logout_requested)
        root.addWidget(self.header)

        body = QVBoxLayout()
        side_margin = visual.margins["section"] - spacing["extra_small"]
        body.setContentsMargins(
            side_margin,
            visual.margins["section"],
            side_margin,
            side_margin,
        )
        body.setSpacing(spacing["medium"])

        title = QLabel(texts.screen_titles["menu"].upper())
        title.setObjectName("screenTitle")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title.setWordWrap(True)
        title.setMinimumSize(520, 104)
        title.setMaximumWidth(620)
        body.addWidget(title, alignment=Qt.AlignmentFlag.AlignHCenter)

        accent = QFrame()
        accent.setObjectName("accent")
        accent.setFixedSize(
            visual.margins["page"] + visual.margins["section"],
            spacing["small"],
        )
        body.addWidget(accent, alignment=Qt.AlignmentFlag.AlignHCenter)

        panel = Surface(self._style_manager)
        panel_layout = QGridLayout(panel)
        panel_layout.setContentsMargins(
            visual.margins["page"],
            visual.margins["section"],
            visual.margins["page"],
            visual.margins["section"],
        )
        panel_layout.setHorizontalSpacing(spacing["large"])
        panel_layout.setVerticalSpacing(spacing["medium"])

        self.academics_button = self._menu_button(
            texts.button_labels["open_academics"], primary=True
        )
        self.update_button = self._menu_button(texts.button_labels["update"])
        self.approvals_button = self._menu_button(texts.button_labels["approvals"])
        self.alerts_button = self._menu_button(texts.button_labels["alerts"])
        self.assign_load_button = self._menu_button(
            texts.button_labels["assign_load"], enabled=False
        )
        self.assignments_button = self._menu_button(
            texts.button_labels["assignments"], enabled=False
        )
        self.courses_button = self._menu_button(
            texts.button_labels["courses"], enabled=False
        )

        unavailable = texts.out_of_scope_function_texts["menu_features"]
        for button in (
            self.assign_load_button,
            self.assignments_button,
            self.courses_button,
        ):
            button.setToolTip(unavailable)

        panel_layout.addWidget(self.academics_button, 0, 0)
        panel_layout.addWidget(self.update_button, 0, 1)
        panel_layout.addWidget(self.approvals_button, 1, 0)
        panel_layout.addWidget(self.alerts_button, 1, 1)
        panel_layout.addWidget(self.assign_load_button, 2, 0)
        panel_layout.addWidget(self.assignments_button, 2, 1)
        panel_layout.setRowStretch(3, 1)

        self.academics_button.clicked.connect(self.academics_requested)
        self.update_button.clicked.connect(self.update_requested)
        self.approvals_button.clicked.connect(self.approvals_requested)
        self.alerts_button.clicked.connect(self.alerts_requested)

        body.addWidget(panel, stretch=1)
        add_page_footer(
            body,
            self.settings,
            lambda: self.error_requested.emit("Error en el menú principal."),
        )
        root.addLayout(body, stretch=1)

    def set_session(
        self,
        username: str,
        *,
        is_owner: bool,
        can_approve: bool | None = None,
    ) -> None:
        self.header.username_label.setText(username)
        self.header.username_label.setVisible(bool(username))
        self.approvals_button.setVisible(
            is_owner if can_approve is None else can_approve
        )
        self.alerts_button.setVisible(is_owner)

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
        button.setMinimumSize(240, 64)
        button.setEnabled(enabled)
        return button
