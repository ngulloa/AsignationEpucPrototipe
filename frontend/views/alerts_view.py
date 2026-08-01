"""Owner-only presentation of safe structured notification details."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import replace

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from frontend.contracts import OwnerAlert, UiResult
from frontend.settings import ApplicationSettings
from frontend.style_manager import StyleManager
from frontend.widgets import AppHeader, PageTitle, Surface, add_page_footer


class AlertsView(QWidget):
    back_requested = Signal()
    logout_requested = Signal()
    error_requested = Signal(str)

    def __init__(
        self,
        settings: ApplicationSettings,
        style_manager: StyleManager,
        mark_seen: Callable[[str], UiResult],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.settings = settings
        self._mark_seen = mark_seen
        self.alerts: tuple[OwnerAlert, ...] = ()
        self.setObjectName("alertsView")
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
            PageTitle(self.settings.texts.screen_titles["alerts"], self.settings)
        )
        panel = Surface(style_manager)
        panel_layout = QVBoxLayout(panel)
        panel_layout.setContentsMargins(
            spacing["medium"], spacing["medium"], spacing["medium"], spacing["medium"]
        )
        panel_layout.setSpacing(spacing["medium"])
        hint = QLabel("Seleccione una alerta para revisar su detalle estructurado.")
        hint.setObjectName("helperText")
        panel_layout.addWidget(hint)
        self.table = QTableWidget()
        self.table.setColumnCount(5)
        self.table.setHorizontalHeaderLabels(
            ("#", "Origen", "Fecha", "Categoría", "Estado")
        )
        self.table.verticalHeader().hide()
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setWordWrap(False)
        header = self.table.horizontalHeader()
        for column in range(5):
            header.setSectionResizeMode(
                column,
                header.ResizeMode.Stretch if column == 3 else header.ResizeMode.Fixed,
            )
        self.table.setColumnWidth(0, 56)
        self.table.setColumnWidth(1, 180)
        self.table.setColumnWidth(2, 180)
        self.table.setColumnWidth(4, 120)
        self.table.itemSelectionChanged.connect(self._show_detail)
        panel_layout.addWidget(self.table, stretch=2)
        self.empty_label = QLabel(self.settings.texts.messages["no_alerts"])
        self.empty_label.setObjectName("emptyMessage")
        self.empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        panel_layout.addWidget(self.empty_label)
        self.detail_text = QTextEdit()
        self.detail_text.setReadOnly(True)
        self.detail_text.setPlaceholderText("Detalle estructurado de la alerta")
        self.detail_text.setMaximumHeight(120)
        panel_layout.addWidget(self.detail_text)
        buttons = QHBoxLayout()
        buttons.addStretch()
        self.mark_seen_button = QPushButton("Marcar como vista")
        self.mark_seen_button.setObjectName("primaryButton")
        self.mark_seen_button.setMinimumSize(200, 48)
        self.mark_seen_button.setEnabled(False)
        self.mark_seen_button.clicked.connect(self.mark_selected_seen)
        buttons.addWidget(self.mark_seen_button)
        self.back_button = QPushButton(self.settings.texts.button_labels["back"])
        self.back_button.setObjectName("secondaryButton")
        self.back_button.setMinimumSize(200, 48)
        self.back_button.clicked.connect(self.back_requested)
        buttons.addWidget(self.back_button)
        panel_layout.addLayout(buttons)
        body.addWidget(panel, stretch=1)
        add_page_footer(
            body,
            self.settings,
            lambda: self.error_requested.emit("Error al visualizar alertas."),
        )
        root.addLayout(body, stretch=1)

    def set_session(self, username: str) -> None:
        self.header.username_label.setText(username)
        self.header.username_label.setVisible(bool(username))

    def set_alerts(self, alerts: Iterable[OwnerAlert]) -> None:
        self.alerts = tuple(alerts)
        self.table.clearContents()
        self.table.setRowCount(len(self.alerts))
        for row, alert in enumerate(self.alerts):
            values = (
                str(row + 1),
                alert.source_screen,
                alert.created_at,
                alert.category,
                "Nueva" if alert.status == "new" else "Vista",
            )
            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                if column == 0:
                    item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                self.table.setItem(row, column, item)
            self.table.setRowHeight(row, 48)
        self.empty_label.setVisible(not self.alerts)
        self.detail_text.clear()
        self.mark_seen_button.setEnabled(False)

    def show_error(self, message: str) -> None:
        self.detail_text.setPlainText(message)

    def _show_detail(self) -> None:
        row = self.table.currentRow()
        if 0 <= row < len(self.alerts):
            alert = self.alerts[row]
            self.detail_text.setPlainText(
                f"Identificador: {alert.alert_id}\n"
                f"Origen: {alert.source_screen}\n"
                f"Categoría: {alert.category}\n"
                f"Código: {alert.error_code}\n"
                f"Estado: {'Nueva' if alert.status == 'new' else 'Vista'}\n\n"
                f"Descripción:\n{alert.description}"
            )
            self.mark_seen_button.setEnabled(alert.status == "new")

    def mark_selected_seen(self) -> None:
        row = self.table.currentRow()
        if not 0 <= row < len(self.alerts):
            return
        alert = self.alerts[row]
        result = self._mark_seen(alert.alert_id)
        if not result.success:
            self.show_error(result.message)
            return
        updated = list(self.alerts)
        updated[row] = replace(alert, status="seen")
        self.set_alerts(updated)
        self.table.selectRow(row)
