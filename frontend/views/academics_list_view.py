"""Single local academic workspace backed exclusively by injected records."""

from __future__ import annotations

from collections.abc import Iterable

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QResizeEvent
from PySide6.QtWidgets import (
    QAbstractItemView,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from backend.contracts import AcademicRecord
from frontend.settings import ApplicationSettings
from frontend.style_manager import StyleManager
from frontend.widgets import AppHeader, PageTitle, Surface

_RECORD_FIELDS = ("name", "rut", "plant", "profile", "weekly_hours", "status")


class AcademicsListView(QWidget):
    add_requested = Signal()
    edit_requested = Signal(object)
    delete_requested = Signal(str)
    menu_requested = Signal()
    logout_requested = Signal()

    def __init__(
        self,
        settings: ApplicationSettings,
        style_manager: StyleManager,
        academics: Iterable[AcademicRecord] = (),
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.settings = settings
        self._style_manager = style_manager
        self.academics = tuple(academics)
        self.action_buttons: list[QPushButton] = []
        self._delete_buttons: dict[str, QPushButton] = {}
        self._pending_delete_id: str | None = None
        self._compact_toolbar = False
        self.setObjectName("academicsListView")
        self._build_ui()
        self.set_academics(self.academics)

    def _build_ui(self) -> None:
        visual = self.settings.visual
        texts = self.settings.texts
        spacing = visual.spacing
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        self.header = AppHeader(self.settings, username="", show_logout=True)
        self.header.logout_requested.connect(self._request_logout)
        root.addWidget(self.header)

        body_widget = QWidget()
        body = QVBoxLayout(body_widget)
        horizontal_margin = visual.margins["page"] + spacing["medium"]
        body.setContentsMargins(
            horizontal_margin,
            spacing["large"],
            horizontal_margin,
            spacing["medium"],
        )
        body.setSpacing(spacing["medium"])
        body.addWidget(PageTitle(texts.screen_titles["academic_list"], self.settings))

        panel = Surface(self._style_manager)
        panel_layout = QVBoxLayout(panel)
        panel_layout.setContentsMargins(
            spacing["medium"],
            spacing["medium"],
            spacing["medium"],
            spacing["medium"],
        )
        panel_layout.setSpacing(spacing["medium"])

        self.toolbar = QGridLayout()
        self.toolbar.setHorizontalSpacing(spacing["medium"])
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText(texts.messages["search_placeholder"])
        self.search_input.setMinimumSize(260, 40)
        self.search_input.setMaximumWidth(360)
        self.search_input.setEnabled(False)
        self.search_input.setToolTip(texts.out_of_scope_function_texts["search"])
        self.edit_selected_button = self._action_button(
            texts.button_labels["edit_selected"],
            primary=False,
        )
        self.edit_selected_button.setEnabled(False)
        self.edit_selected_button.clicked.connect(self._edit_selected)
        self.add_button = self._action_button(
            texts.button_labels["add_academic"],
            primary=True,
        )
        self.add_button.clicked.connect(self._request_add)
        self.back_button = self._action_button(
            texts.button_labels["back_to_menu"],
            primary=False,
        )
        self.back_button.clicked.connect(self._request_menu)
        self._arrange_toolbar(compact=False)
        panel_layout.addLayout(self.toolbar)

        self.feedback_label = QLabel()
        self.feedback_label.setWordWrap(True)
        self.feedback_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.feedback_label.hide()
        panel_layout.addWidget(self.feedback_label)

        status_row = QHBoxLayout()
        self.count_label = QLabel()
        self.count_label.setObjectName("recordCount")
        status_row.addWidget(self.count_label)
        status_row.addStretch()
        panel_layout.addLayout(status_row)

        self.table = QTableWidget()
        self.table.setColumnCount(len(texts.table_headers))
        self.table.setHorizontalHeaderLabels(texts.table_headers)
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setWordWrap(False)
        header = self.table.horizontalHeader()
        header.setFixedHeight(spacing["extra_large"])
        for column in range(len(texts.table_headers)):
            header.setSectionResizeMode(
                column,
                QHeaderView.ResizeMode.Stretch
                if column == 0
                else QHeaderView.ResizeMode.ResizeToContents,
            )
        self.table.itemSelectionChanged.connect(self._refresh_edit_state)
        panel_layout.addWidget(self.table, stretch=1)

        self.empty_label = QLabel(texts.messages["no_academics"])
        self.empty_label.setObjectName("emptyMessage")
        self.empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        panel_layout.addWidget(self.empty_label)
        body.addWidget(panel, stretch=1)

        self.body_scroll = QScrollArea()
        self.body_scroll.setObjectName("academicsBodyScroll")
        self.body_scroll.setWidgetResizable(True)
        self.body_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.body_scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        self.body_scroll.setWidget(body_widget)
        root.addWidget(self.body_scroll, stretch=1)

    @staticmethod
    def _action_button(text: str, *, primary: bool) -> QPushButton:
        button = QPushButton(text)
        button.setObjectName("primaryButton" if primary else "secondaryButton")
        button.setMinimumSize(156, 40)
        return button

    def _arrange_toolbar(self, *, compact: bool) -> None:
        while self.toolbar.count():
            self.toolbar.takeAt(0)
        if compact:
            self.toolbar.addWidget(self.search_input, 0, 0, 1, 3)
            self.toolbar.addWidget(self.edit_selected_button, 1, 0)
            self.toolbar.addWidget(self.add_button, 1, 1)
            self.toolbar.addWidget(self.back_button, 1, 2)
        else:
            self.toolbar.addWidget(self.search_input, 0, 0)
            self.toolbar.setColumnStretch(1, 1)
            self.toolbar.addWidget(self.edit_selected_button, 0, 2)
            self.toolbar.addWidget(self.add_button, 0, 3)
            self.toolbar.addWidget(self.back_button, 0, 4)
        self._compact_toolbar = compact

    def resizeEvent(self, event: QResizeEvent) -> None:
        compact = event.size().width() < 940
        body = self.body_scroll.widget()
        if body is not None:
            body.setMaximumWidth(event.size().width())
        if compact != self._compact_toolbar:
            self._arrange_toolbar(compact=compact)
            self.header.institution_label.setVisible(not compact)
        super().resizeEvent(event)

    def set_session(self, username: str) -> None:
        self.header.username_label.setText(username)
        self.header.username_label.setVisible(bool(username))

    def set_academics(self, academics: Iterable[AcademicRecord]) -> None:
        self.reset_delete_confirmation()
        self.academics = tuple(academics)
        self.action_buttons.clear()
        self._delete_buttons.clear()
        self.table.clearContents()
        self.table.setRowCount(len(self.academics))
        row_height = (
            self.settings.visual.margins["page"]
            + self.settings.visual.spacing["medium"]
        )
        for row, academic in enumerate(self.academics):
            for column, field_name in enumerate(_RECORD_FIELDS):
                item = QTableWidgetItem(str(getattr(academic, field_name)))
                item.setTextAlignment(
                    Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
                )
                self.table.setItem(row, column, item)
            self.table.setCellWidget(
                row,
                len(_RECORD_FIELDS),
                self._actions_widget(academic),
            )
            self.table.setRowHeight(row, row_height)
        self._fit_delete_action_widths()
        self.empty_label.setVisible(not self.academics)
        self.count_label.setText(f"Registros: {len(self.academics)}")
        self._refresh_edit_state()

    def _actions_widget(self, academic: AcademicRecord) -> QWidget:
        container = QWidget()
        layout = QHBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(self.settings.visual.spacing["small"])
        edit_button = QPushButton(self.settings.texts.button_labels["edit"])
        edit_button.setObjectName("tableEditAction")
        edit_button.clicked.connect(
            lambda _checked=False, record=academic: self._request_edit(record)
        )
        delete_button = QPushButton(self.settings.texts.button_labels["delete"])
        delete_button.setObjectName("tableDeleteAction")
        delete_button.clicked.connect(
            lambda _checked=False, academic_id=academic.academic_id: (
                self._request_delete(academic_id)
            )
        )
        self._delete_buttons[academic.academic_id] = delete_button
        self.action_buttons.extend((edit_button, delete_button))
        layout.addWidget(edit_button)
        layout.addWidget(delete_button)
        return container

    def _fit_delete_action_widths(self) -> None:
        delete_text = self.settings.texts.button_labels["delete"]
        confirm_text = self.settings.texts.button_labels["confirm_delete"]
        for delete_button in self._delete_buttons.values():
            delete_button.setText(confirm_text)
            delete_button.ensurePolished()
            delete_button.setMinimumWidth(delete_button.sizeHint().width())
            delete_button.setText(delete_text)
            container = delete_button.parentWidget()
            if container is not None and container.layout() is not None:
                container.layout().invalidate()
                container.layout().activate()
        self.table.resizeColumnToContents(len(_RECORD_FIELDS))

    def _refresh_edit_state(self) -> None:
        row = self.table.currentRow()
        self.edit_selected_button.setEnabled(row >= 0)
        if self._pending_delete_id is not None:
            selected_id = (
                self.academics[row].academic_id
                if 0 <= row < len(self.academics)
                else None
            )
            if selected_id != self._pending_delete_id:
                self.reset_delete_confirmation()

    def _edit_selected(self) -> None:
        row = self.table.currentRow()
        if 0 <= row < len(self.academics):
            self._request_edit(self.academics[row])

    def _request_delete(self, academic_id: str) -> None:
        if self._pending_delete_id == academic_id:
            self.reset_delete_confirmation()
            self.delete_requested.emit(academic_id)
            return
        self.reset_delete_confirmation()
        delete_button = self._delete_buttons.get(academic_id)
        if delete_button is None:
            return
        self._pending_delete_id = academic_id
        delete_button.setText(self.settings.texts.button_labels["confirm_delete"])

    def reset_delete_confirmation(self) -> None:
        if self._pending_delete_id is None:
            return
        delete_button = self._delete_buttons.get(self._pending_delete_id)
        if delete_button is not None:
            delete_button.setText(self.settings.texts.button_labels["delete"])
        self._pending_delete_id = None

    def _request_add(self, _checked: bool = False) -> None:
        self.reset_delete_confirmation()
        self.add_requested.emit()

    def _request_menu(self, _checked: bool = False) -> None:
        self.reset_delete_confirmation()
        self.menu_requested.emit()

    def _request_edit(self, record: AcademicRecord) -> None:
        self.reset_delete_confirmation()
        self.edit_requested.emit(record)

    def _request_logout(self) -> None:
        self.reset_delete_confirmation()
        self.logout_requested.emit()

    def show_result(self, message: str, *, success: bool) -> None:
        self.feedback_label.setText(message)
        self.feedback_label.setObjectName(
            "successMessage" if success else "failureMessage"
        )
        self.feedback_label.style().unpolish(self.feedback_label)
        self.feedback_label.style().polish(self.feedback_label)
        self.feedback_label.show()

    def clear_result(self) -> None:
        self.feedback_label.clear()
        self.feedback_label.hide()
