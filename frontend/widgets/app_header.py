"""Institutional header shared by every frontend view."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QWidget

from frontend.settings import ApplicationSettings


class AppHeader(QWidget):
    """Render the Penpot header and optional presentation-only session actions."""

    logout_requested = Signal()

    def __init__(
        self,
        settings: ApplicationSettings,
        *,
        centered: bool = False,
        compact: bool = False,
        username: str = "",
        show_logout: bool = False,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("appHeader")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        spacing = settings.visual.spacing
        self.setFixedHeight(spacing["extra_large"])

        layout = QHBoxLayout(self)
        layout.setContentsMargins(
            settings.visual.margins["page"] + spacing["medium"],
            0,
            settings.visual.margins["page"] + spacing["medium"],
            0,
        )
        layout.setSpacing(spacing["medium"])

        self.institution_label = self._header_label(
            settings.texts.headers["institution"]
        )
        if centered:
            layout.addStretch()
            layout.addWidget(self.institution_label)
            layout.addStretch()
            return

        if compact:
            layout.addWidget(self.institution_label)
        else:
            application = self._header_label(settings.texts.headers["application"])
            layout.addWidget(application)
        layout.addStretch()

        self.username_label = self._header_label(username)
        self.username_label.setObjectName("headerUserLabel")
        self.username_label.setVisible(bool(username))
        layout.addWidget(self.username_label)

        if not compact:
            layout.addWidget(self.institution_label)
        self.logout_button = QPushButton(settings.texts.button_labels["logout"])
        self.logout_button.setObjectName("headerLink")
        self.logout_button.setVisible(show_logout)
        self.logout_button.clicked.connect(self.logout_requested)
        layout.addWidget(self.logout_button)

    @staticmethod
    def _header_label(text: str) -> QLabel:
        label = QLabel(text)
        label.setObjectName("headerLabel")
        label.setAlignment(Qt.AlignmentFlag.AlignVCenter)
        return label
