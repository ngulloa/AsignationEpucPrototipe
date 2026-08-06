"""Read-only presentation of consolidated assignments grouped by academic."""

from __future__ import annotations

from collections.abc import Iterable

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QFont, QResizeEvent
from PySide6.QtWidgets import (
    QAbstractItemView,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QScrollArea,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from backend.contracts import AcademicAssignmentsSummary, AssignmentSummary
from frontend.settings import ApplicationSettings
from frontend.style_manager import StyleManager
from frontend.widgets import AppHeader, PageTitle, ResultBanner, Surface


class AssignmentsListView(QWidget):
    """Render the consolidated assignment DTOs without deriving business data."""

    menu_requested = Signal()
    logout_requested = Signal()

    def __init__(
        self,
        settings: ApplicationSettings,
        style_manager: StyleManager,
        assignments: Iterable[AcademicAssignmentsSummary] = (),
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.settings = settings
        self._style_manager = style_manager
        self.assignments = tuple(assignments)
        self.warning_indicators: list[QLabel] = []
        self.setObjectName("assignmentsListView")
        self._build_ui()
        self.set_assignments(self.assignments)

    def _build_ui(self) -> None:
        visual = self.settings.visual
        texts = self.settings.texts
        spacing = visual.spacing

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        self.header = AppHeader(self.settings, username="", show_logout=True)
        self.header.logout_requested.connect(self.logout_requested)
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
        body.addWidget(PageTitle(texts.screen_titles["assignments"], self.settings))

        panel = Surface(self._style_manager)
        panel_layout = QVBoxLayout(panel)
        panel_layout.setContentsMargins(*(spacing["medium"],) * 4)
        panel_layout.setSpacing(spacing["medium"])

        toolbar = QHBoxLayout()
        toolbar.addStretch()
        self.back_button = QPushButton(texts.button_labels["back_to_menu"])
        self.back_button.setObjectName("secondaryButton")
        self.back_button.setMinimumSize(156, 40)
        self.back_button.clicked.connect(self.menu_requested)
        toolbar.addWidget(self.back_button)
        panel_layout.addLayout(toolbar)

        self.result_banner = ResultBanner()
        panel_layout.addWidget(self.result_banner)

        self.count_label = QLabel()
        self.count_label.setObjectName("recordCount")
        panel_layout.addWidget(self.count_label)

        self.table = QTableWidget()
        headers = texts.assignment_table_headers
        self.table.setColumnCount(len(headers))
        self.table.setHorizontalHeaderLabels(headers)
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self.table.setWordWrap(True)
        header = self.table.horizontalHeader()
        header.setFixedHeight(spacing["extra_large"])
        for column in range(len(headers)):
            header.setSectionResizeMode(column, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        panel_layout.addWidget(self.table, stretch=1)

        self.empty_label = QLabel(texts.messages["no_assignment_academics"])
        self.empty_label.setObjectName("emptyMessage")
        self.empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        panel_layout.addWidget(self.empty_label)
        body.addWidget(panel, stretch=1)

        self.body_scroll = QScrollArea()
        self.body_scroll.setObjectName("assignmentsBodyScroll")
        self.body_scroll.setWidgetResizable(True)
        self.body_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.body_scroll.setWidget(body_widget)
        root.addWidget(self.body_scroll, stretch=1)

    def set_session(self, username: str) -> None:
        self.header.username_label.setText(username)
        self.header.username_label.setVisible(bool(username))

    def resizeEvent(self, event: QResizeEvent) -> None:
        self.header.institution_label.setVisible(event.size().width() >= 940)
        super().resizeEvent(event)
        QTimer.singleShot(0, self._fit_row_heights)

    def set_assignments(
        self,
        assignments: Iterable[AcademicAssignmentsSummary],
    ) -> None:
        self.assignments = tuple(assignments)
        self.warning_indicators.clear()
        self.table.clearContents()
        self.table.setRowCount(len(self.assignments))
        for row, summary in enumerate(self.assignments):
            self._populate_row(row, summary)
        self._fit_row_heights()
        self.empty_label.setVisible(not self.assignments)
        self.count_label.setText(
            self.settings.texts.messages["assignment_academic_count_format"].format(
                count=len(self.assignments)
            )
        )

    def _fit_row_heights(self) -> None:
        self.table.resizeRowsToContents()
        minimum_row_height = self.settings.visual.spacing["extra_large"] * 2
        for row in range(self.table.rowCount()):
            self.table.setRowHeight(
                row,
                max(self.table.rowHeight(row), minimum_row_height),
            )

    def _populate_row(self, row: int, summary: AcademicAssignmentsSummary) -> None:
        values = (
            summary.name,
            summary.rut,
            self._assignments_text(summary.assignments),
            f"{summary.total_points:.2f}",
        )
        for column, value in enumerate(values):
            item = QTableWidgetItem(value)
            alignment = Qt.AlignmentFlag.AlignVCenter
            alignment |= (
                Qt.AlignmentFlag.AlignRight
                if column == 3
                else Qt.AlignmentFlag.AlignLeft
            )
            item.setTextAlignment(alignment)
            if column == 3:
                font = item.font()
                font.setWeight(QFont.Weight.Bold)
                item.setFont(font)
            self.table.setItem(row, column, item)
        self.table.setCellWidget(row, 4, self._warning_widget())

    def _assignments_text(self, assignments: tuple[AssignmentSummary, ...]) -> str:
        if not assignments:
            return self.settings.texts.messages["no_assignments"]
        return "\n".join(self._assignment_line(item) for item in assignments)

    @staticmethod
    def _assignment_line(assignment: AssignmentSummary) -> str:
        course = " ".join(
            value for value in (assignment.course_code, assignment.course_name) if value
        )
        parts = (
            course or assignment.type_name,
            assignment.period_label,
            assignment.classification_name,
            assignment.status_name,
            f"{assignment.displayed_points:.2f}",
        )
        return " · ".join(value for value in parts if value)

    def _warning_widget(self) -> QWidget:
        container = QWidget()
        layout = QHBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        indicator = QLabel("●")
        indicator.setObjectName("warningIndicator")
        indicator.setProperty("warningState", "inactive")
        tooltip = self.settings.texts.messages["warning_inactive_tooltip"]
        indicator.setToolTip(tooltip)
        indicator.setAccessibleName(
            self.settings.texts.messages["warning_inactive_accessible_name"]
        )
        indicator.setAccessibleDescription(tooltip)
        indicator.setAlignment(Qt.AlignmentFlag.AlignCenter)
        indicator.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.warning_indicators.append(indicator)
        layout.addStretch()
        layout.addWidget(indicator)
        layout.addStretch()
        return container

    def show_error(self, message: str) -> None:
        self.result_banner.present(message, success=False)

    def clear_error(self) -> None:
        self.result_banner.clear_result()
