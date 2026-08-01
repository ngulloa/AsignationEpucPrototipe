"""Personal and shared academic tables backed exclusively by injected records."""

from __future__ import annotations

from collections.abc import Iterable

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QResizeEvent
from PySide6.QtWidgets import (
    QAbstractItemView,
    QButtonGroup,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QStackedWidget,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from backend.contracts import AcademicRecord
from frontend.contracts import SharedAcademicTable
from frontend.settings import ApplicationSettings
from frontend.style_manager import StyleManager
from frontend.widgets import AppHeader, PageTitle, Surface, add_page_footer

_RECORD_FIELDS = ("name", "rut", "plant", "profile", "weekly_hours", "status")


class AcademicsListView(QWidget):
    add_requested = Signal()
    edit_requested = Signal(object)
    shared_edit_requested = Signal(int, object)
    share_requested = Signal(str)
    public_rename_requested = Signal(int, str)
    public_publish_requested = Signal(int)
    public_draft_cancel_requested = Signal(int)
    menu_requested = Signal()
    logout_requested = Signal()
    error_requested = Signal(str)

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
        self.shared_tables: tuple[SharedAcademicTable, ...] = ()
        self.action_buttons: list[QPushButton] = []
        self._can_edit_shared = False
        self._session_username = ""
        self._compact_toolbar = False
        self._latest_error = settings.texts.messages["save_error"]
        self.setObjectName("academicsListView")
        self._build_ui()
        self.set_academics(self.academics)
        self.set_shared_tables(())

    def _build_ui(self) -> None:
        visual = self.settings.visual
        texts = self.settings.texts
        spacing = visual.spacing
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        self.header = AppHeader(self.settings, username="usuario", show_logout=True)
        self.header.logout_requested.connect(self.logout_requested)
        root.addWidget(self.header)

        body_widget = QWidget()
        body = QVBoxLayout(body_widget)
        horizontal_margin = visual.margins["page"] + spacing["medium"]
        body.setContentsMargins(
            horizontal_margin, spacing["large"], horizontal_margin, spacing["medium"]
        )
        body.setSpacing(spacing["medium"])
        body.addWidget(PageTitle(texts.screen_titles["academic_list"], self.settings))

        panel = Surface(self._style_manager)
        panel_layout = QVBoxLayout(panel)
        panel_layout.setContentsMargins(
            spacing["medium"], spacing["medium"], spacing["medium"], spacing["medium"]
        )
        panel_layout.setSpacing(spacing["medium"])

        mode_row = QHBoxLayout()
        mode_row.setSpacing(0)
        self.personal_table_button = self._toggle_button(
            texts.messages["personal_table"]
        )
        self.shared_tables_button = self._toggle_button(texts.messages["shared_tables"])
        mode_group = QButtonGroup(self)
        mode_group.setExclusive(True)
        mode_group.addButton(self.personal_table_button)
        mode_group.addButton(self.shared_tables_button)
        self.personal_table_button.setChecked(True)
        mode_row.addWidget(self.personal_table_button)
        mode_row.addWidget(self.shared_tables_button)
        mode_row.addStretch()
        panel_layout.addLayout(mode_row)

        self.toolbar = QGridLayout()
        self.toolbar.setHorizontalSpacing(spacing["medium"])
        self.toolbar.setVerticalSpacing(spacing["small"])
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText(texts.messages["search_placeholder"])
        self.search_input.setMinimumSize(260, 40)
        self.search_input.setMaximumWidth(360)
        self.search_input.setEnabled(False)
        self.search_input.setToolTip(texts.out_of_scope_function_texts["search"])
        self.edit_selected_button = self._action_button(
            texts.button_labels["edit_selected"], False
        )
        self.edit_selected_button.setEnabled(False)
        self.edit_selected_button.clicked.connect(self._edit_selected)
        self.add_button = self._action_button(texts.button_labels["add_academic"], True)
        self.add_button.clicked.connect(self.add_requested)
        self.table_name_input = QLineEdit()
        self.table_name_input.setPlaceholderText("Nombre de la tabla")
        self.table_name_input.setMaxLength(80)
        self.table_name_input.setMinimumSize(220, 40)
        self.share_button = self._action_button("Compartir tabla", False)
        self.share_button.setEnabled(False)
        self.share_button.clicked.connect(
            lambda: self.share_requested.emit(self.table_name_input.text())
        )
        self.table_name_input.textChanged.connect(
            lambda value: self.share_button.setEnabled(bool(value.strip()))
        )
        self.back_button = self._action_button(
            texts.button_labels["back_to_menu"], False
        )
        self.back_button.clicked.connect(self.menu_requested)
        self._arrange_toolbar(compact=False)
        panel_layout.addLayout(self.toolbar)

        self.feedback_label = QLabel()
        self.feedback_label.setWordWrap(True)
        self.feedback_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.feedback_label.hide()
        panel_layout.addWidget(self.feedback_label)

        self.mode_stack = QStackedWidget()
        personal_page = QWidget()
        personal_layout = QVBoxLayout(personal_page)
        personal_layout.setContentsMargins(0, 0, 0, 0)
        personal_layout.setSpacing(spacing["small"])
        status_row = QHBoxLayout()
        self.count_label = QLabel()
        self.count_label.setObjectName("recordCount")
        status_row.addWidget(self.count_label)
        status_row.addStretch()
        personal_layout.addLayout(status_row)
        self.table = self._academic_table()
        self.table.itemSelectionChanged.connect(self._refresh_edit_state)
        personal_layout.addWidget(self.table, stretch=1)
        self.empty_label = QLabel(texts.messages["no_academics"])
        self.empty_label.setObjectName("emptyMessage")
        self.empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        personal_layout.addWidget(self.empty_label)
        self.mode_stack.addWidget(personal_page)

        shared_page = QWidget()
        shared_layout = QVBoxLayout(shared_page)
        shared_layout.setContentsMargins(0, 0, 0, 0)
        shared_layout.setSpacing(spacing["small"])
        shared_hint = QLabel(texts.messages["select_shared_table"])
        shared_hint.setObjectName("helperText")
        shared_layout.addWidget(shared_hint)
        rename_row = QHBoxLayout()
        self.public_name_input = QLineEdit()
        self.public_name_input.setPlaceholderText("Nuevo nombre de la tabla")
        self.public_name_input.setMaxLength(80)
        self.public_name_input.setEnabled(False)
        self.public_name_input.textChanged.connect(self._refresh_public_rename_state)
        rename_row.addWidget(self.public_name_input, stretch=1)
        self.rename_public_button = self._action_button("Renombrar tabla", False)
        self.rename_public_button.setEnabled(False)
        self.rename_public_button.clicked.connect(self._rename_selected_public_table)
        rename_row.addWidget(self.rename_public_button)
        shared_layout.addLayout(rename_row)
        publication_row = QHBoxLayout()
        self.shared_edit_notice = QLabel(
            "Contenido compartido: los cambios se mantienen en un borrador privado."
        )
        self.shared_edit_notice.setObjectName("helperText")
        publication_row.addWidget(self.shared_edit_notice, stretch=1)
        self.cancel_public_draft_button = self._action_button("Cancelar cambios", False)
        self.cancel_public_draft_button.setMinimumWidth(0)
        self.cancel_public_draft_button.setEnabled(False)
        self.cancel_public_draft_button.clicked.connect(
            self._cancel_selected_public_draft
        )
        publication_row.addWidget(self.cancel_public_draft_button)
        self.publish_public_button = self._action_button("Publicar", True)
        self.publish_public_button.setMinimumWidth(0)
        self.publish_public_button.setEnabled(False)
        self.publish_public_button.clicked.connect(self._publish_selected_public_table)
        publication_row.addWidget(self.publish_public_button)
        shared_layout.addLayout(publication_row)
        self.shared_tables_table = QTableWidget()
        self.shared_tables_table.setObjectName("sharedTablesTable")
        self.shared_tables_table.setColumnCount(3)
        self.shared_tables_table.setHorizontalHeaderLabels(
            ("#", "Nombre de tabla", "Titular")
        )
        self._configure_table_selection(self.shared_tables_table)
        self.shared_tables_table.setMaximumHeight(180)
        self.shared_tables_table.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.ResizeMode.ResizeToContents
        )
        self.shared_tables_table.horizontalHeader().setSectionResizeMode(
            1, QHeaderView.ResizeMode.Stretch
        )
        self.shared_tables_table.horizontalHeader().setSectionResizeMode(
            2, QHeaderView.ResizeMode.Stretch
        )
        self.shared_tables_table.itemSelectionChanged.connect(
            self._show_selected_shared_table
        )
        shared_layout.addWidget(self.shared_tables_table)
        self.shared_context_label = QLabel(texts.messages["select_shared_table"])
        self.shared_context_label.setObjectName("contextLabel")
        shared_layout.addWidget(self.shared_context_label)
        self.shared_records_table = self._academic_table(include_actions=False)
        self.shared_records_table.itemSelectionChanged.connect(self._refresh_edit_state)
        shared_layout.addWidget(self.shared_records_table, stretch=1)
        self.shared_empty_label = QLabel(texts.messages["no_shared_tables"])
        self.shared_empty_label.setObjectName("emptyMessage")
        self.shared_empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        shared_layout.addWidget(self.shared_empty_label)
        self.mode_stack.addWidget(shared_page)
        panel_layout.addWidget(self.mode_stack, stretch=1)

        self.personal_table_button.clicked.connect(lambda: self._set_mode(0))
        self.shared_tables_button.clicked.connect(lambda: self._set_mode(1))
        body.addWidget(panel, stretch=1)
        add_page_footer(
            body, self.settings, lambda: self.error_requested.emit(self._latest_error)
        )
        self.body_scroll = QScrollArea()
        self.body_scroll.setObjectName("academicsBodyScroll")
        self.body_scroll.setWidgetResizable(True)
        self.body_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.body_scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        self.body_scroll.setWidget(body_widget)
        root.addWidget(self.body_scroll, stretch=1)

    def _arrange_toolbar(self, *, compact: bool) -> None:
        while self.toolbar.count():
            self.toolbar.takeAt(0)
        if compact:
            self.toolbar.setColumnStretch(1, 0)
            self.toolbar.addWidget(self.search_input, 0, 0, 1, 3)
            self.toolbar.addWidget(self.table_name_input, 1, 0, 1, 2)
            self.toolbar.addWidget(self.share_button, 1, 2)
            self.toolbar.addWidget(self.edit_selected_button, 2, 0)
            self.toolbar.addWidget(self.add_button, 2, 1)
            self.toolbar.addWidget(self.back_button, 2, 2)
        else:
            self.toolbar.addWidget(self.search_input, 0, 0)
            self.toolbar.setColumnStretch(1, 1)
            self.toolbar.addWidget(self.table_name_input, 0, 2)
            self.toolbar.addWidget(self.share_button, 0, 3)
            self.toolbar.addWidget(self.edit_selected_button, 0, 4)
            self.toolbar.addWidget(self.add_button, 0, 5)
            self.toolbar.addWidget(self.back_button, 0, 6)
        self._compact_toolbar = compact

    def resizeEvent(self, event: QResizeEvent) -> None:
        compact = event.size().width() < 940
        self.body_scroll.widget().setMaximumWidth(event.size().width())
        if compact != self._compact_toolbar:
            self._arrange_toolbar(compact=compact)
            self.header.institution_label.setVisible(not compact)
        self.shared_edit_notice.setVisible(not compact)
        super().resizeEvent(event)

    def _academic_table(self, *, include_actions: bool = True) -> QTableWidget:
        headers = (
            self.settings.texts.table_headers
            if include_actions
            else self.settings.texts.table_headers[:-1]
        )
        table = QTableWidget()
        table.setColumnCount(len(headers))
        table.setHorizontalHeaderLabels(headers)
        self._configure_table_selection(table)
        table.setWordWrap(False)
        header = table.horizontalHeader()
        header.setFixedHeight(self.settings.visual.spacing["extra_large"])
        for column in range(len(headers)):
            mode = (
                QHeaderView.ResizeMode.Stretch
                if column == 0
                else QHeaderView.ResizeMode.ResizeToContents
            )
            header.setSectionResizeMode(column, mode)
        return table

    @staticmethod
    def _configure_table_selection(table: QTableWidget) -> None:
        table.verticalHeader().setVisible(False)
        table.setAlternatingRowColors(False)
        table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)

    @staticmethod
    def _toggle_button(text: str) -> QPushButton:
        button = QPushButton(text)
        button.setObjectName("toggleButton")
        button.setCheckable(True)
        button.setMinimumSize(176, 40)
        return button

    @staticmethod
    def _action_button(text: str, primary: bool) -> QPushButton:
        button = QPushButton(text)
        button.setObjectName("primaryButton" if primary else "secondaryButton")
        button.setMinimumSize(156, 40)
        return button

    def set_session(self, username: str) -> None:
        self._session_username = username
        self.header.username_label.setText(username)
        self.header.username_label.setVisible(bool(username))
        self._refresh_public_rename_state()

    def set_shared_edit_permission(self, allowed: bool) -> None:
        self._can_edit_shared = allowed
        self._refresh_edit_state()

    def set_academics(self, academics: Iterable[AcademicRecord]) -> None:
        self.academics = tuple(academics)
        self.action_buttons.clear()
        self._populate_academic_table(self.table, self.academics, include_actions=True)
        self.empty_label.setVisible(not self.academics)
        self.count_label.setText(f"Registros: {len(self.academics)}")
        self._refresh_edit_state()

    def set_shared_tables(self, shared_tables: Iterable[SharedAcademicTable]) -> None:
        self.shared_tables = tuple(
            sorted(shared_tables, key=lambda table: table.name.casefold())
        )
        self.shared_tables_table.clearContents()
        self.shared_tables_table.setRowCount(len(self.shared_tables))
        for row, shared_table in enumerate(self.shared_tables):
            number = QTableWidgetItem(str(shared_table.table_number or row + 1))
            number.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.shared_tables_table.setItem(row, 0, number)
            self.shared_tables_table.setItem(
                row, 1, QTableWidgetItem(shared_table.name)
            )
            self.shared_tables_table.setItem(
                row, 2, QTableWidgetItem(shared_table.username)
            )
            self.shared_tables_table.setRowHeight(row, 40)
        self.shared_records_table.setRowCount(0)
        self.shared_records_table.clearSelection()
        self.public_name_input.clear()
        self.shared_empty_label.setVisible(not self.shared_tables)
        self.shared_context_label.setText(
            self.settings.texts.messages["select_shared_table"]
        )
        self._refresh_edit_state()
        self._refresh_public_rename_state()
        self._refresh_publication_state()

    def _populate_academic_table(
        self,
        table: QTableWidget,
        academics: tuple[AcademicRecord, ...],
        *,
        include_actions: bool,
    ) -> None:
        table.clearContents()
        table.setRowCount(len(academics))
        row_height = (
            self.settings.visual.margins["page"]
            + self.settings.visual.spacing["medium"]
        )
        for row, academic in enumerate(academics):
            for column, field_name in enumerate(_RECORD_FIELDS):
                item = QTableWidgetItem(str(getattr(academic, field_name)))
                item.setTextAlignment(
                    Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
                )
                table.setItem(row, column, item)
            if include_actions:
                table.setCellWidget(
                    row, len(_RECORD_FIELDS), self._actions_widget(academic)
                )
            table.setRowHeight(row, row_height)

    def _actions_widget(self, academic: AcademicRecord) -> QWidget:
        container = QWidget()
        layout = QHBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(self.settings.visual.spacing["small"])
        edit_button = QPushButton(self.settings.texts.button_labels["edit"])
        edit_button.setObjectName("tableEditAction")
        edit_button.clicked.connect(
            lambda _checked=False, record=academic: self.edit_requested.emit(record)
        )
        delete_button = QPushButton(self.settings.texts.button_labels["delete"])
        delete_button.setObjectName("tableDeleteAction")
        delete_button.setEnabled(False)
        delete_button.setToolTip(
            self.settings.texts.out_of_scope_function_texts["record_actions"]
        )
        self.action_buttons.extend((edit_button, delete_button))
        layout.addWidget(edit_button)
        layout.addWidget(delete_button)
        return container

    def _set_mode(self, index: int) -> None:
        self.mode_stack.setCurrentIndex(index)
        is_personal = index == 0
        self.add_button.setVisible(is_personal)
        self.search_input.setVisible(is_personal)
        self.table_name_input.setVisible(is_personal)
        self.share_button.setVisible(is_personal)
        self._refresh_edit_state()

    def set_private_table_name(self, name: str) -> None:
        self.table_name_input.setText(name)

    def _refresh_edit_state(self) -> None:
        if self.mode_stack.currentIndex() == 0:
            enabled = self.table.currentRow() >= 0
        else:
            enabled = (
                self._can_edit_shared
                and self.shared_tables_table.currentRow() >= 0
                and self.shared_records_table.currentRow() >= 0
            )
        self.edit_selected_button.setEnabled(enabled)
        if self.mode_stack.currentIndex() == 1 and not self._can_edit_shared:
            self.edit_selected_button.setToolTip(
                "Acceso denegado: se requiere una cuenta aprobada."
            )
        else:
            self.edit_selected_button.setToolTip("")

    def _edit_selected(self) -> None:
        if self.mode_stack.currentIndex() == 0:
            row = self.table.currentRow()
            if 0 <= row < len(self.academics):
                self.edit_requested.emit(self.academics[row])
            return
        table_row = self.shared_tables_table.currentRow()
        record_row = self.shared_records_table.currentRow()
        if not (
            self._can_edit_shared
            and 0 <= table_row < len(self.shared_tables)
            and 0 <= record_row < len(self.shared_tables[table_row].academics)
        ):
            self.show_result("Acceso denegado para editar esta tabla.", success=False)
            return
        table = self.shared_tables[table_row]
        if table.table_number is None:
            self.show_result(
                "La tabla compartida no tiene identificador.", success=False
            )
            return
        self.shared_edit_requested.emit(
            table.table_number,
            table.academics[record_row],
        )

    def _show_selected_shared_table(self) -> None:
        row = self.shared_tables_table.currentRow()
        if not 0 <= row < len(self.shared_tables):
            return
        shared_table = self.shared_tables[row]
        self.public_name_input.setText(shared_table.name)
        self.shared_context_label.setText(
            f"Tabla pública: {shared_table.name} · Titular: {shared_table.username} · "
            f"Registros: {len(shared_table.academics)} · Está editando contenido "
            "compartido"
        )
        self._populate_academic_table(
            self.shared_records_table, shared_table.academics, include_actions=False
        )
        self.shared_records_table.clearSelection()
        self._refresh_edit_state()
        self._refresh_public_rename_state()
        self._refresh_publication_state()

    def _refresh_public_rename_state(self) -> None:
        row = self.shared_tables_table.currentRow()
        owns_selected = (
            0 <= row < len(self.shared_tables)
            and self.shared_tables[row].username == self._session_username
            and self.shared_tables[row].table_number is not None
        )
        self.public_name_input.setEnabled(owns_selected)
        self.rename_public_button.setEnabled(
            owns_selected and bool(self.public_name_input.text().strip())
        )

    def _rename_selected_public_table(self) -> None:
        row = self.shared_tables_table.currentRow()
        if not 0 <= row < len(self.shared_tables):
            return
        table = self.shared_tables[row]
        if table.username != self._session_username or table.table_number is None:
            self.show_result(
                "Solo el titular puede renombrar esta tabla.",
                success=False,
            )
            return
        self.public_rename_requested.emit(
            table.table_number,
            self.public_name_input.text(),
        )

    def _refresh_publication_state(self) -> None:
        row = self.shared_tables_table.currentRow()
        operation = (
            self.shared_tables[row] if 0 <= row < len(self.shared_tables) else None
        )
        has_draft = operation is not None and operation.publication_state is not None
        allowed = self._can_edit_shared and has_draft
        self.publish_public_button.setEnabled(allowed)
        self.cancel_public_draft_button.setEnabled(
            allowed
            and operation.publication_state not in {"committed_local", "retry_pending"}
        )
        if has_draft:
            self.shared_edit_notice.setText(
                f"Borrador privado · estado: {operation.publication_state}"
            )
        else:
            self.shared_edit_notice.setText(
                "Contenido compartido: los cambios se mantienen en un borrador privado."
            )

    def _publish_selected_public_table(self) -> None:
        row = self.shared_tables_table.currentRow()
        if not 0 <= row < len(self.shared_tables):
            return
        table = self.shared_tables[row]
        if table.table_number is not None and table.publication_state is not None:
            self.public_publish_requested.emit(table.table_number)

    def _cancel_selected_public_draft(self) -> None:
        row = self.shared_tables_table.currentRow()
        if not 0 <= row < len(self.shared_tables):
            return
        table = self.shared_tables[row]
        if table.table_number is not None and table.publication_state is not None:
            self.public_draft_cancel_requested.emit(table.table_number)

    def set_publication_busy(self, busy: bool) -> None:
        self.publish_public_button.setText("Publicando…" if busy else "Publicar")
        self.shared_tables_table.setEnabled(not busy)
        self.shared_records_table.setEnabled(not busy)
        self.header.logout_button.setEnabled(not busy)
        self.back_button.setEnabled(not busy)
        self.personal_table_button.setEnabled(not busy)
        self.shared_tables_button.setEnabled(not busy)
        self.add_button.setEnabled(not busy)
        self.share_button.setEnabled(
            False if busy else bool(self.table_name_input.text().strip())
        )
        self.table_name_input.setEnabled(not busy)
        self.rename_public_button.setEnabled(False if busy else True)
        self.cancel_public_draft_button.setEnabled(False if busy else True)
        self.edit_selected_button.setEnabled(
            False if busy else self.edit_selected_button.isEnabled()
        )
        if not busy:
            self._refresh_edit_state()
            self._refresh_publication_state()

    def show_result(self, message: str, *, success: bool) -> None:
        self.feedback_label.setText(message)
        self.feedback_label.setObjectName(
            "successMessage" if success else "failureMessage"
        )
        self.feedback_label.style().unpolish(self.feedback_label)
        self.feedback_label.style().polish(self.feedback_label)
        self.feedback_label.show()
        if not success:
            self._latest_error = message

    def clear_result(self) -> None:
        self.feedback_label.clear()
        self.feedback_label.hide()
