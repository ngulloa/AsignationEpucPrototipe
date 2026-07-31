"""Small reusable elements that preserve the Penpot page grammar."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from frontend.settings import ApplicationSettings
from frontend.style_manager import StyleManager


class PageTitle(QWidget):
    def __init__(
        self,
        text: str,
        settings: ApplicationSettings,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(settings.visual.spacing["medium"])
        self.label = QLabel(text.upper())
        self.label.setObjectName("sectionTitle")
        layout.addWidget(self.label)
        accent = QFrame()
        accent.setObjectName("accent")
        accent.setFixedSize(
            settings.visual.margins["page"] - settings.visual.spacing["small"],
            settings.visual.spacing["small"],
        )
        layout.addWidget(accent)
        layout.addStretch()


class Surface(QFrame):
    def __init__(
        self,
        style_manager: StyleManager,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("surface")
        style_manager.apply_surface_shadow(self)


class ResultBanner(QLabel):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWordWrap(True)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.hide()

    def present(self, message: str, *, success: bool) -> None:
        self.setText(message)
        self.setObjectName("successMessage" if success else "failureMessage")
        self.style().unpolish(self)
        self.style().polish(self)
        self.setVisible(bool(message))

    def clear_result(self) -> None:
        self.clear()
        self.hide()


class ErrorLinkFooter(QWidget):
    """Footer action present on every page, including the error form itself."""

    requested = Signal()

    def __init__(
        self,
        settings: ApplicationSettings,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addStretch()
        self.button = QPushButton(settings.texts.button_labels["notify_error"])
        self.button.setObjectName("linkButton")
        self.button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.button.clicked.connect(self.requested)
        layout.addWidget(self.button)


def add_page_footer(
    layout: QVBoxLayout,
    settings: ApplicationSettings,
    callback: object,
) -> ErrorLinkFooter:
    footer = ErrorLinkFooter(settings)
    footer.requested.connect(callback)  # type: ignore[arg-type]
    layout.addWidget(footer)
    return footer
