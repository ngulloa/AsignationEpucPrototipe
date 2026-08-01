"""Owner approval administration presentation."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from typing import Final

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from frontend.contracts import ApprovalItem, UiResult
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

ApprovalCallback = Callable[[str], UiResult]
ROUTE: Final = FrontendRoute.APPROVAL


class ApprovalView(QWidget):
    back_requested = Signal()
    logout_requested = Signal()
    error_requested = Signal(str)

    def __init__(
        self,
        settings: ApplicationSettings,
        style_manager: StyleManager,
        approve_user: ApprovalCallback,
        withdraw_approval: ApprovalCallback,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.settings = settings
        self._approve_user = approve_user
        self._withdraw_approval = withdraw_approval
        self.items: tuple[ApprovalItem, ...] = ()
        self._latest_error = "Error al administrar aprobaciones."
        self.setObjectName("approvalView")
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
            PageTitle(self.settings.texts.screen_titles["approval"], self.settings)
        )
        panel = Surface(style_manager)
        panel_layout = QVBoxLayout(panel)
        panel_layout.setContentsMargins(
            spacing["medium"], spacing["medium"], spacing["medium"], spacing["medium"]
        )
        panel_layout.setSpacing(spacing["medium"])
        helper = QLabel(
            "Seleccione una solicitud pendiente para habilitar su aprobación."
        )
        helper.setObjectName("helperText")
        panel_layout.addWidget(helper)
        self.table = QTableWidget()
        self.table.setColumnCount(4)
        self.table.setHorizontalHeaderLabels(
            ("#", "Nombre de usuario", "Fecha de solicitud", "Estado")
        )
        self.table.verticalHeader().hide()
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setWordWrap(False)
        approval_header = self.table.horizontalHeader()
        approval_header.setSectionResizeMode(0, approval_header.ResizeMode.Fixed)
        approval_header.setSectionResizeMode(1, approval_header.ResizeMode.Stretch)
        approval_header.setSectionResizeMode(2, approval_header.ResizeMode.Fixed)
        approval_header.setSectionResizeMode(3, approval_header.ResizeMode.Stretch)
        self.table.setColumnWidth(0, 56)
        self.table.setColumnWidth(2, 190)
        self.table.itemSelectionChanged.connect(self._refresh_state)
        panel_layout.addWidget(self.table, stretch=1)
        self.empty_label = QLabel(self.settings.texts.messages["no_approvals"])
        self.empty_label.setObjectName("emptyMessage")
        self.empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        panel_layout.addWidget(self.empty_label)
        self.result_label = ResultBanner()
        panel_layout.addWidget(self.result_label)
        buttons = QHBoxLayout()
        buttons.addStretch()
        self.withdraw_button = QPushButton("Retirar solicitud")
        self.withdraw_button.setObjectName("secondaryButton")
        self.withdraw_button.setMinimumSize(180, 48)
        self.withdraw_button.setEnabled(False)
        self.withdraw_button.clicked.connect(self.withdraw_selected)
        buttons.addWidget(self.withdraw_button)
        self.back_button = QPushButton(self.settings.texts.button_labels["back"])
        self.back_button.setObjectName("secondaryButton")
        self.back_button.setMinimumSize(180, 48)
        self.back_button.clicked.connect(self.back_requested)
        buttons.addWidget(self.back_button)
        self.approve_button = QPushButton(self.settings.texts.button_labels["approve"])
        self.approve_button.setObjectName("primaryButton")
        self.approve_button.setMinimumSize(180, 48)
        self.approve_button.setEnabled(False)
        self.approve_button.clicked.connect(self.approve_selected)
        buttons.addWidget(self.approve_button)
        panel_layout.addLayout(buttons)
        body.addWidget(panel, stretch=1)
        add_page_footer(
            body, self.settings, lambda: self.error_requested.emit(self._latest_error)
        )
        root.addLayout(body, stretch=1)

    def set_session(self, username: str) -> None:
        self.header.username_label.setText(username)
        self.header.username_label.setVisible(bool(username))

    def set_items(self, items: Iterable[ApprovalItem]) -> None:
        self.items = tuple(items)
        self.table.clearContents()
        self.table.setRowCount(len(self.items))
        for row, item in enumerate(self.items):
            values = (str(row + 1), item.username, item.requested_at, item.status)
            for column, value in enumerate(values):
                table_item = QTableWidgetItem(value)
                if column == 0:
                    table_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                self.table.setItem(row, column, table_item)
            self.table.setRowHeight(row, 48)
        self.empty_label.setVisible(not self.items)
        self.result_label.clear_result()
        self._refresh_state()

    def _refresh_state(self) -> None:
        row = self.table.currentRow()
        is_pending = (
            0 <= row < len(self.items)
            and self.items[row].status == "Pendiente"
            and self.items[row].can_approve
        )
        self.approve_button.setEnabled(is_pending)
        self.withdraw_button.setEnabled(
            0 <= row < len(self.items) and self.items[row].can_withdraw
        )

    def approve_selected(self) -> None:
        row = self.table.currentRow()
        if not 0 <= row < len(self.items):
            return
        result = self._approve_user(self.items[row].request_id)
        self.result_label.present(result.message, success=result.success)
        if result.success:
            self.table.item(row, 3).setText("Aprobado")
            self.approve_button.setEnabled(False)
        else:
            self._latest_error = result.message

    def withdraw_selected(self) -> None:
        row = self.table.currentRow()
        if not 0 <= row < len(self.items) or not self.items[row].can_withdraw:
            return
        confirmation = QMessageBox.question(
            self,
            "Retirar solicitud",
            "¿Confirma que desea retirar esta solicitud pendiente?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if confirmation != QMessageBox.StandardButton.Yes:
            return
        result = self._withdraw_approval(self.items[row].request_id)
        self.result_label.present(result.message, success=result.success)
        if result.success:
            remaining = list(self.items)
            del remaining[row]
            self.set_items(remaining)
            self.result_label.present(result.message, success=True)
        else:
            self._latest_error = result.message

    def show_result(self, message: str, *, success: bool) -> None:
        self.result_label.present(message, success=success)
        if not success:
            self._latest_error = message
