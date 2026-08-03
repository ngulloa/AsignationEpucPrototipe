"""Centralized Qt styling built exclusively from validated visual settings."""

from __future__ import annotations

from PySide6.QtCore import QEvent, QObject, QPointF, Qt
from PySide6.QtGui import QColor, QFont, QFontDatabase
from PySide6.QtWidgets import (
    QAbstractButton,
    QApplication,
    QGraphicsDropShadowEffect,
    QWidget,
)

from frontend.settings import VisualSettings


class _ClickableCursorFilter(QObject):
    """Keep enabled abstract buttons discoverable without per-view setup."""

    _REFRESH_EVENTS = frozenset(
        {
            QEvent.Type.EnabledChange,
            QEvent.Type.ParentChange,
            QEvent.Type.Polish,
            QEvent.Type.Show,
        }
    )

    def __init__(self, root: QWidget) -> None:
        super().__init__(root)
        self._root = root

    @staticmethod
    def _refresh_button(button: QAbstractButton) -> None:
        cursor = (
            Qt.CursorShape.PointingHandCursor
            if button.isEnabled()
            else Qt.CursorShape.ArrowCursor
        )
        button.setCursor(cursor)

    def refresh_all(self) -> None:
        for button in self._root.findChildren(QAbstractButton):
            self._refresh_button(button)

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        if (
            isinstance(watched, QAbstractButton)
            and event.type() in self._REFRESH_EVENTS
            and self._root.isAncestorOf(watched)
        ):
            self._refresh_button(watched)
        return super().eventFilter(watched, event)


class StyleManager:
    """Translate immutable visual settings into fonts, QSS and effects."""

    def __init__(self, visual: VisualSettings) -> None:
        self.visual = visual
        self.font_family = self._select_font_family()
        self.button_horizontal_padding = self.visual.spacing["medium"]
        self._clickable_cursor_filter: _ClickableCursorFilter | None = None

    def _select_font_family(self) -> str:
        available = set(QFontDatabase.families())
        candidates = (
            self.visual.typography.preferred_family,
            *self.visual.typography.fallback_families,
        )
        return next(
            (family for family in candidates if family in available),
            QFont().defaultFamily(),
        )

    def base_font(self) -> QFont:
        """Return the configured application font using the available fallback."""
        font = QFont(self.font_family)
        font.setPixelSize(self.visual.typography.sizes["body"])
        font.setWeight(QFont.Weight(self.visual.typography.weights["regular"]))
        return font

    def stylesheet(self) -> str:
        """Build the complete stylesheet without embedded color literals."""
        colors = self.visual.colors
        sizes = self.visual.typography.sizes
        weights = self.visual.typography.weights
        radii = self.visual.radii
        control_border = self.visual.borders["control"]
        focus_border = self.visual.borders["focus"]
        control_color = colors[control_border.color_token]
        focus_color = colors[focus_border.color_token]
        button_padding = self.button_horizontal_padding

        return f"""
            QWidget#appRoot {{
                background-color: {colors["neutral_white"]};
                color: {colors["neutral_black"]};
                font-family: "{self.font_family}";
                font-size: {sizes["body"]}px;
            }}
            QLabel {{
                background: transparent;
                color: {colors["neutral_black"]};
            }}
            #appHeader {{
                background-color: {colors["brand_blue"]};
            }}
            QLabel#headerLabel {{
                background: transparent;
                color: {colors["neutral_white"]};
                font-size: {sizes["body"]}px;
                font-weight: {weights["bold"]};
            }}
            QLabel#headerUserLabel {{
                background: transparent;
                color: {colors["neutral_white"]};
                font-size: {sizes["caption"]}px;
                font-weight: {weights["regular"]};
            }}
            QPushButton#headerLink {{
                background: transparent;
                color: {colors["neutral_white"]};
                font-size: {sizes["caption"]}px;
                text-decoration: underline;
            }}
            QLabel#screenTitle {{
                background: transparent;
                color: {colors["neutral_black"]};
                font-size: {sizes["title"]}px;
                font-weight: {weights["bold"]};
            }}
            QLabel#sectionTitle {{
                background: transparent;
                color: {colors["neutral_black"]};
                font-size: {sizes["subtitle"]}px;
                font-weight: {weights["bold"]};
            }}
            QLabel#fieldLabel {{
                background: transparent;
                color: {colors["brand_blue"]};
                font-size: {sizes["subtitle"]}px;
                font-weight: {weights["regular"]};
            }}
            QLabel#helperText {{
                background: transparent;
                color: {colors["neutral_gray_700"]};
                font-size: {sizes["caption"]}px;
            }}
            QLabel#recordCount, QLabel#contextLabel {{
                background: transparent;
                color: {colors["neutral_gray_700"]};
                font-size: {sizes["body"]}px;
            }}
            QFrame#accent {{
                background-color: {colors["brand_yellow"]};
                border: none;
            }}
            QFrame#surface {{
                background: qlineargradient(
                    x1: 0, y1: 0, x2: 1, y2: 1,
                    stop: 0 {colors["neutral_white"]},
                    stop: 1 {colors["neutral_gray_50"]}
                );
                border: {control_border.width}px solid {control_color};
                border-radius: {radii["small"]}px;
            }}
            QAbstractButton {{
                padding-left: {button_padding}px;
                padding-right: {button_padding}px;
            }}
            QPushButton {{
                border: none;
                border-radius: 0;
                font-size: {sizes["button"]}px;
                font-weight: {weights["regular"]};
                padding-top: 0;
                padding-bottom: 0;
            }}
            QPushButton#primaryButton {{
                background-color: {colors["brand_light_blue"]};
                color: {colors["neutral_white"]};
            }}
            QPushButton#primaryButton:hover {{
                background-color: {colors["brand_blue"]};
            }}
            QPushButton#primaryButton:disabled {{
                background-color: {colors["neutral_gray_300"]};
                color: {colors["neutral_gray_700"]};
            }}
            QPushButton#primaryButton:focus {{
                border: {focus_border.width}px solid {colors["brand_yellow"]};
            }}
            QPushButton#secondaryButton {{
                background-color: {colors["neutral_white"]};
                color: {colors["brand_light_blue"]};
                border: {control_border.width}px solid {colors["neutral_gray_200"]};
            }}
            QPushButton#secondaryButton:hover {{
                border: {focus_border.width}px solid {focus_color};
            }}
            QPushButton#secondaryButton:disabled {{
                background-color: {colors["neutral_gray_50"]};
                color: {colors["neutral_gray_500"]};
                border: {control_border.width}px solid {colors["neutral_gray_300"]};
            }}
            QPushButton#secondaryButton:focus {{
                border: {focus_border.width}px solid {focus_color};
            }}
            QPushButton#headerLink:focus, QPushButton#linkButton:focus {{
                border: {focus_border.width}px solid {colors["brand_yellow"]};
            }}
            QPushButton#linkButton {{
                background: transparent;
                color: {colors["brand_light_blue"]};
                font-size: {sizes["body"]}px;
                text-decoration: underline;
                padding-top: {self.visual.spacing["extra_small"]}px;
                padding-bottom: {self.visual.spacing["extra_small"]}px;
            }}
            QPushButton#toggleButton {{
                background-color: {colors["neutral_white"]};
                color: {colors["brand_light_blue"]};
                border: {control_border.width}px solid {colors["neutral_gray_300"]};
            }}
            QPushButton#toggleButton:checked {{
                background-color: {colors["brand_light_blue"]};
                color: {colors["neutral_white"]};
                border-color: {colors["brand_light_blue"]};
            }}
            QPushButton[sizeRole="large"] {{
                font-size: {sizes["subtitle"]}px;
            }}
            QLineEdit, QComboBox, QSpinBox, QTextEdit {{
                background-color: {colors["neutral_white"]};
                color: {colors["neutral_gray_700"]};
                border: {control_border.width}px solid {control_color};
                border-radius: 0;
                padding-left: {self.visual.spacing["medium"]}px;
                font-size: {sizes["body"]}px;
                selection-background-color: {colors["brand_light_blue"]};
            }}
            QTextEdit {{
                padding: {self.visual.spacing["small"]}px;
            }}
            QLineEdit:focus, QComboBox:focus, QSpinBox:focus, QTextEdit:focus {{
                border: {focus_border.width}px solid {focus_color};
            }}
            QLineEdit:disabled, QLineEdit:read-only, QTextEdit:read-only {{
                background-color: {colors["neutral_white"]};
                color: {colors["neutral_gray_500"]};
            }}
            QComboBox:disabled {{
                background-color: {colors["neutral_white"]};
                color: {colors["neutral_gray_500"]};
            }}
            QLineEdit[sizeRole="form"], QComboBox[sizeRole="form"],
            QSpinBox[sizeRole="form"] {{
                font-size: {sizes["subtitle"]}px;
            }}
            QComboBox::drop-down, QSpinBox::up-button, QSpinBox::down-button {{
                border: none;
                background-color: {colors["neutral_white"]};
            }}
            QComboBox QAbstractItemView {{
                background-color: {colors["neutral_white"]};
                color: {colors["neutral_gray_700"]};
                border: {control_border.width}px solid {control_color};
                outline: none;
                selection-background-color: {colors["brand_light_blue"]};
                selection-color: {colors["neutral_white"]};
            }}
            QComboBox QAbstractItemView::item:selected {{
                background-color: {colors["brand_light_blue"]};
                color: {colors["neutral_white"]};
            }}
            QTableWidget {{
                background-color: {colors["neutral_white"]};
                alternate-background-color: {colors["neutral_gray_50"]};
                border: {control_border.width}px solid {control_color};
                gridline-color: {colors["neutral_gray_300"]};
                color: {colors["neutral_black"]};
                font-size: {sizes["caption"]}px;
                outline: none;
            }}
            QTableWidget::item:selected {{
                background-color: {colors["neutral_gray_100"]};
                color: {colors["neutral_black"]};
            }}
            QHeaderView::section {{
                background-color: {colors["neutral_white"]};
                color: {colors["brand_blue"]};
                border: none;
                border-bottom: {control_border.width}px solid {control_color};
                padding-left: {self.visual.spacing["small"]}px;
                font-size: {sizes["body"]}px;
                font-weight: {weights["regular"]};
            }}
            QPushButton#tableEditAction {{
                background: transparent;
                color: {colors["brand_light_blue"]};
                font-size: {sizes["caption"]}px;
            }}
            QPushButton#tableDeleteAction {{
                background: transparent;
                color: {colors["semantic_error"]};
                font-size: {sizes["caption"]}px;
            }}
            QLabel#emptyMessage {{
                background: transparent;
                color: {colors["neutral_gray_700"]};
                font-size: {sizes["body"]}px;
            }}
            QLabel#errorLabel {{
                background: transparent;
                color: {colors["semantic_error"]};
                font-size: {sizes["caption"]}px;
            }}
            QLabel#successMessage {{
                background: transparent;
                color: {colors["semantic_success"]};
                font-size: {sizes["body"]}px;
                font-weight: {weights["medium"]};
            }}
            QLabel#failureMessage {{
                background: transparent;
                color: {colors["semantic_error"]};
                font-size: {sizes["body"]}px;
                font-weight: {weights["medium"]};
            }}
            QFrame#messagePanel {{
                background-color: {colors["neutral_gray_50"]};
                border-left: {self.visual.spacing["extra_small"]}px solid {colors["brand_yellow"]};
            }}
            QScrollArea {{
                background: transparent;
                border: none;
            }}
            QScrollArea > QWidget > QWidget {{
                background: transparent;
            }}
        """

    def apply_surface_shadow(self, widget: QWidget) -> None:
        """Apply the configured shadow to a raised surface."""
        settings = self.visual.shadows["surface"]
        color = QColor(settings.color)
        color.setAlphaF(settings.opacity)
        effect = QGraphicsDropShadowEffect(widget)
        effect.setBlurRadius(settings.blur)
        effect.setOffset(QPointF(settings.offset_x, settings.offset_y))
        effect.setColor(color)
        widget.setGraphicsEffect(effect)

    def apply_interaction_defaults(self, root: QWidget) -> None:
        """Apply centralized pointer feedback to all buttons."""
        application = QApplication.instance()
        if application is None:
            raise RuntimeError("Se requiere QApplication para configurar cursores.")
        cursor_filter = _ClickableCursorFilter(root)
        application.installEventFilter(cursor_filter)
        cursor_filter.refresh_all()
        self._clickable_cursor_filter = cursor_filter
