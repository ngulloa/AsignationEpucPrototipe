"""Three-step course assignment flow backed exclusively by application services."""

from __future__ import annotations

from decimal import Decimal, InvalidOperation

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QResizeEvent
from PySide6.QtWidgets import (
    QComboBox,
    QDoubleSpinBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from backend.contracts import CourseAssignmentDraft
from frontend.settings import ApplicationSettings
from frontend.style_manager import StyleManager
from frontend.widgets import AppHeader, PageTitle, ResultBanner, Surface


class AssignmentFlowView(QWidget):
    cancel_requested = Signal()
    saved = Signal(str)
    logout_requested = Signal()

    def __init__(
        self,
        settings: ApplicationSettings,
        style: StyleManager,
        controller,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.settings = settings
        self.controller = controller
        self.selected_academic_id = ""
        self._academics = []
        self._courses = []
        self._page_layouts: list[QVBoxLayout] = []
        self.setObjectName("assignmentFlowView")
        self._build_ui(style)

    @property
    def current_step(self) -> int:
        return self.pages.currentIndex() + 1

    def _build_ui(self, style: StyleManager) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        self.header = AppHeader(self.settings, show_logout=True)
        self.header.logout_requested.connect(self.logout_requested)
        root.addWidget(self.header)
        self.pages = QStackedWidget()
        root.addWidget(self.pages, 1)
        self._build_academic_page(style)
        self._build_type_page(style)
        self._build_course_page(style)

    def _page(self, title: str, style: StyleManager) -> QVBoxLayout:
        visual = self.settings.visual
        spacing = visual.spacing
        page = QWidget()
        outer = QVBoxLayout(page)
        horizontal_margin = visual.margins["page"] + spacing["medium"]
        outer.setContentsMargins(
            horizontal_margin,
            spacing["large"],
            horizontal_margin,
            spacing["medium"],
        )
        outer.setSpacing(spacing["medium"])
        self._page_layouts.append(outer)
        outer.addWidget(PageTitle(title, self.settings))

        panel = Surface(style)
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(
            spacing["medium"],
            spacing["medium"],
            spacing["medium"],
            spacing["medium"],
        )
        layout.setSpacing(spacing["small"])
        outer.addWidget(panel, stretch=1)
        self.pages.addWidget(page)
        return layout

    def _build_academic_page(self, style: StyleManager) -> None:
        texts = self.settings.texts
        spacing = self.settings.visual.spacing
        layout = self._page(texts.screen_titles["assignment_step_1"], style)

        self.academic_search = QLineEdit()
        self.academic_search.setProperty("sizeRole", "form")
        self.academic_search.setPlaceholderText(
            texts.messages["assignment_academic_search_placeholder"]
        )
        self.academic_search.setMinimumHeight(spacing["large"] + spacing["medium"])
        layout.addWidget(self.academic_search)

        self.academic_status = QLabel(
            texts.messages["assignment_academic_selection_instruction"]
        )
        self.academic_status.setObjectName("contextLabel")
        self.academic_status.setWordWrap(True)
        layout.addWidget(self.academic_status)

        self.academic_list = QListWidget()
        self.academic_list.setObjectName("assignmentAcademicList")
        self.academic_list.setAlternatingRowColors(True)
        self.academic_list.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        self.academic_list.setTextElideMode(Qt.TextElideMode.ElideRight)
        self.academic_list.setUniformItemSizes(True)
        layout.addWidget(self.academic_list, stretch=1)

        self.academic_empty_label = QLabel(texts.messages["no_active_academics"])
        self.academic_empty_label.setObjectName("emptyMessage")
        self.academic_empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.academic_empty_label.setWordWrap(True)
        self.academic_empty_label.hide()
        layout.addWidget(self.academic_empty_label)

        self.academic_cancel_button = self._button(
            texts.button_labels["cancel"], primary=False
        )
        self.academic_next = self._button(texts.button_labels["next"], primary=True)
        self.academic_next.setEnabled(False)
        buttons = QHBoxLayout()
        buttons.setSpacing(spacing["medium"])
        buttons.addWidget(self.academic_cancel_button)
        buttons.addStretch()
        buttons.addWidget(self.academic_next)
        self._add_footer(layout, buttons)

        self.academic_search.textChanged.connect(self._filter_academics)
        self.academic_list.currentRowChanged.connect(self._academic_selection_changed)
        self.academic_next.clicked.connect(self._select_academic)
        self.academic_cancel_button.clicked.connect(self.cancel_requested)

    def _build_type_page(self, style: StyleManager) -> None:
        texts = self.settings.texts
        spacing = self.settings.visual.spacing
        layout = self._page(texts.screen_titles["assignment_step_2"], style)

        self.activity_context = QLabel()
        self.activity_context.setObjectName("contextLabel")
        self.activity_context.setWordWrap(True)
        layout.addWidget(self.activity_context)

        activity_container = QWidget()
        activity_container.setMaximumWidth(
            self.settings.visual.screens["assignment_flow"].width
            - self.settings.visual.margins["page"] * 4
        )
        activity_layout = QVBoxLayout(activity_container)
        activity_layout.setContentsMargins(0, spacing["small"], 0, spacing["small"])
        activity_layout.setSpacing(spacing["small"])

        self.course_type_button = self._button(
            texts.button_labels["activity_course"], primary=True
        )
        self.course_type_button.setProperty("sizeRole", "large")
        activity_layout.addWidget(self.course_type_button)
        self.pending_type_buttons = []
        for key in (
            "activity_practice",
            "activity_directed_study",
            "activity_thesis",
            "activity_committee",
            "activity_management",
        ):
            label = texts.messages["assignment_coming_soon_format"].format(
                activity=texts.button_labels[key]
            )
            button = self._button(label, primary=False)
            button.setObjectName("futureActivityButton")
            button.setProperty("sizeRole", "large")
            button.setEnabled(False)
            activity_layout.addWidget(button)
            self.pending_type_buttons.append(button)
        layout.addWidget(
            activity_container,
            stretch=1,
            alignment=Qt.AlignmentFlag.AlignHCenter,
        )

        self.type_back_button = self._button(texts.button_labels["back"], primary=False)
        self.type_cancel_button = self._button(
            texts.button_labels["cancel"], primary=False
        )
        controls = QHBoxLayout()
        controls.setSpacing(spacing["medium"])
        controls.addWidget(self.type_back_button)
        controls.addWidget(self.type_cancel_button)
        controls.addStretch()
        self._add_footer(layout, controls)

        self.type_back_button.clicked.connect(lambda: self.pages.setCurrentIndex(0))
        self.type_cancel_button.clicked.connect(self.cancel_requested)
        self.course_type_button.clicked.connect(self._open_course_step)

    def _build_course_page(self, style: StyleManager) -> None:
        texts = self.settings.texts
        spacing = self.settings.visual.spacing
        layout = self._page(texts.screen_titles["assignment_step_3"], style)

        self.course_context = QLabel()
        self.course_context.setObjectName("contextLabel")
        self.course_context.setWordWrap(True)
        layout.addWidget(self.course_context)

        form = QGridLayout()
        form.setHorizontalSpacing(spacing["small"])
        form.setVerticalSpacing(spacing["small"])
        control_height = spacing["large"] + spacing["medium"]
        self.period_combo = self._form_combo(control_height)
        self.course_combo = self._form_combo(control_height)
        self.offering_combo = self._form_combo(control_height)
        self.section_input = self._form_line_edit(control_height)
        self.section_input.setPlaceholderText(
            texts.messages["assignment_section_placeholder"]
        )
        self.nrc_input = self._form_line_edit(control_height)
        self.nrc_input.setPlaceholderText(texts.messages["assignment_optional"])
        self.participation_input = QDoubleSpinBox()
        self.participation_input.setProperty("sizeRole", "form")
        self.participation_input.setMinimumHeight(control_height)
        self.participation_input.setRange(0.01, 100)
        self.participation_input.setValue(100)
        self.participation_input.setSuffix(
            texts.messages["assignment_percentage_suffix"]
        )
        self.classification_combo = self._form_combo(control_height)
        for code in ("DOM", "AAC", "AAA"):
            self.classification_combo.addItem(
                texts.messages[f"assignment_classification_{code.lower()}"], code
            )
        self.demand_combo = self._form_combo(control_height)
        self._populate_demand_combo()

        self._add_form_field(form, "academic_period", self.period_combo, 0, 0)
        self._add_form_field(form, "participation", self.participation_input, 0, 2)
        self._add_form_field(form, "course", self.course_combo, 1, 0, control_span=3)
        self._add_form_field(
            form, "offering_section", self.offering_combo, 2, 0, control_span=3
        )
        self._add_form_field(form, "new_section", self.section_input, 3, 0)
        self._add_form_field(form, "nrc", self.nrc_input, 3, 2)
        self._add_form_field(form, "classification", self.classification_combo, 4, 0)
        self._add_form_field(form, "aaa_demand", self.demand_combo, 4, 2)
        form.setColumnStretch(1, 3)
        form.setColumnStretch(3, 2)
        layout.addLayout(form)
        layout.addStretch()

        self.policy_notice = QLabel(texts.messages["assignment_policy_notice"])
        self.policy_notice.setObjectName("policyNotice")
        self.policy_notice.setWordWrap(True)
        layout.addWidget(self.policy_notice)

        self.result = ResultBanner()
        self.result.setMinimumHeight(spacing["large"])
        layout.addWidget(self.result)

        self.course_back_button = self._button(
            texts.button_labels["back"], primary=False
        )
        self.course_cancel_button = self._button(
            texts.button_labels["cancel"], primary=False
        )
        self.calculate_button = self._button(
            texts.button_labels["calculate"], primary=False
        )
        self.save_button = self._button(
            texts.button_labels["save_assignment"], primary=True
        )
        self.calculate_button.setEnabled(False)
        self.save_button.setEnabled(False)
        self.course_actions = QHBoxLayout()
        self.course_actions.setSpacing(spacing["medium"])
        for button in (
            self.course_back_button,
            self.course_cancel_button,
            self.calculate_button,
            self.save_button,
        ):
            self.course_actions.addWidget(button)
        self._add_footer(layout, self.course_actions)

        self.course_back_button.clicked.connect(lambda: self.pages.setCurrentIndex(1))
        self.course_cancel_button.clicked.connect(self.cancel_requested)
        self.calculate_button.clicked.connect(self._calculate)
        self.save_button.clicked.connect(self._save)
        self.period_combo.currentIndexChanged.connect(self._reload_offerings)
        self.course_combo.currentIndexChanged.connect(self._reload_offerings)
        self.offering_combo.currentIndexChanged.connect(self._invalidate_calculation)
        self.section_input.textChanged.connect(self._invalidate_calculation)
        self.nrc_input.textChanged.connect(self._invalidate_calculation)
        self.participation_input.valueChanged.connect(self._invalidate_calculation)
        self.classification_combo.currentIndexChanged.connect(
            self._classification_changed
        )
        self.demand_combo.currentIndexChanged.connect(self._invalidate_calculation)
        self._classification_changed()

    def _add_form_field(
        self,
        layout: QGridLayout,
        label_key: str,
        control: QWidget,
        row: int,
        column: int,
        *,
        control_span: int = 1,
    ) -> None:
        label = QLabel(self.settings.texts.field_labels[label_key])
        label.setObjectName("fieldLabel")
        layout.addWidget(label, row, column)
        layout.addWidget(control, row, column + 1, 1, control_span)

    def _form_combo(self, height: int) -> QComboBox:
        combo = QComboBox()
        combo.setProperty("sizeRole", "form")
        combo.setMinimumHeight(height)
        return combo

    def _form_line_edit(self, height: int) -> QLineEdit:
        edit = QLineEdit()
        edit.setProperty("sizeRole", "form")
        edit.setMinimumHeight(height)
        return edit

    def _button(self, text: str, *, primary: bool) -> QPushButton:
        button = QPushButton(text)
        button.setObjectName("primaryButton" if primary else "secondaryButton")
        button.setMinimumHeight(
            self.settings.visual.spacing["large"]
            + self.settings.visual.spacing["medium"]
        )
        return button

    def _add_footer(self, layout: QVBoxLayout, controls) -> None:
        separator = QFrame()
        separator.setObjectName("footerDivider")
        separator.setFrameShape(QFrame.Shape.HLine)
        layout.addWidget(separator)
        layout.addLayout(controls)

    def resizeEvent(self, event: QResizeEvent) -> None:
        visual = self.settings.visual
        compact_threshold = (
            visual.screens["assignment_flow"].width - visual.margins["page"] * 3
        )
        compact = event.size().width() < compact_threshold
        self.header.institution_label.setVisible(not compact)
        horizontal_margin = (
            visual.margins["page"]
            if compact
            else visual.margins["page"] + visual.spacing["medium"]
        )
        for layout in self._page_layouts:
            layout.setContentsMargins(
                horizontal_margin,
                visual.spacing["large"],
                horizontal_margin,
                visual.spacing["medium"],
            )
        compact_right_width = visual.margins["page"] * 2 + visual.spacing["medium"]
        maximum_width = compact_right_width if compact else 16777215
        for control in (
            self.participation_input,
            self.nrc_input,
            self.demand_combo,
        ):
            control.setMaximumWidth(maximum_width)
        super().resizeEvent(event)

    def prepare(self) -> None:
        self.pages.setCurrentIndex(0)
        self.selected_academic_id = ""
        self.academic_search.clear()
        self.result.clear_result()
        self.save_button.setEnabled(False)
        try:
            self._academics = list(self.controller.list_active_academics())
        except AttributeError, RuntimeError:
            self._academics = []
        self._filter_academics()
        self.academic_list.setCurrentRow(-1)
        self.academic_next.setEnabled(False)

    def set_session(self, username: str) -> None:
        self.header.username_label.setText(username)
        self.header.username_label.setVisible(bool(username))

    def _filter_academics(self) -> None:
        query = self.academic_search.text().strip().casefold()
        self.academic_list.clear()
        for record in self._academics:
            if (
                query
                and query not in record.name.casefold()
                and query not in record.rut.casefold()
            ):
                continue
            self.academic_list.addItem(
                self.settings.texts.messages["assignment_academic_item_format"].format(
                    name=record.name,
                    rut=record.rut,
                )
            )
            item = self.academic_list.item(self.academic_list.count() - 1)
            item.setData(Qt.ItemDataRole.UserRole, record.academic_id)
            item.setToolTip(item.text())
        has_results = self.academic_list.count() > 0
        self.academic_list.setVisible(has_results)
        self.academic_empty_label.setVisible(not has_results)
        self._academic_selection_changed(-1)

    def _academic_selection_changed(self, row: int) -> None:
        selected = row >= 0
        self.academic_next.setEnabled(selected)
        if selected:
            item = self.academic_list.item(row)
            self.academic_status.setText(
                self.settings.texts.messages[
                    "assignment_academic_selected_format"
                ].format(academic=item.text())
            )
        elif self.academic_list.count():
            self.academic_status.setText(
                self.settings.texts.messages[
                    "assignment_academic_selection_instruction"
                ]
            )
        else:
            self.academic_status.setText(
                self.settings.texts.messages["assignment_no_academic_matches"]
            )

    def _select_academic(self) -> None:
        item = self.academic_list.currentItem()
        if item is not None:
            self.selected_academic_id = item.data(Qt.ItemDataRole.UserRole)
            selected_text = item.text()
            context = self.settings.texts.messages[
                "assignment_academic_context_format"
            ].format(academic=selected_text)
            self.activity_context.setText(context)
            self.course_context.setText(context)
            self.pages.setCurrentIndex(1)

    def _open_course_step(self) -> None:
        try:
            periods = list(self.controller.list_periods())
            self._courses = list(self.controller.list_courses())
        except (AttributeError, RuntimeError) as error:
            self.result.present(str(error), success=False)
            return
        self.result.clear_result()
        self.save_button.setEnabled(False)

        self.period_combo.blockSignals(True)
        self.period_combo.clear()
        if periods:
            for period in periods:
                self.period_combo.addItem(
                    self.settings.texts.messages["assignment_period_format"].format(
                        year=period.year, term=period.term_code
                    ),
                    period.period_id,
                )
        else:
            self.period_combo.addItem(
                self.settings.texts.messages["assignment_no_period_option"], ""
            )
        self.period_combo.setEnabled(bool(periods))
        self.period_combo.blockSignals(False)

        self.course_combo.blockSignals(True)
        self.course_combo.clear()
        if self._courses:
            for course in self._courses:
                self.course_combo.addItem(
                    self.settings.texts.messages["assignment_course_format"].format(
                        code=course.course_code, name=course.name
                    ),
                    course.course_id,
                )
        else:
            self.course_combo.addItem(
                self.settings.texts.messages["assignment_no_course_option"], ""
            )
        self.course_combo.setEnabled(bool(self._courses))
        self.course_combo.blockSignals(False)

        form_data_available = bool(periods and self._courses)
        for control in (
            self.offering_combo,
            self.section_input,
            self.nrc_input,
            self.participation_input,
            self.classification_combo,
        ):
            control.setEnabled(form_data_available)
        self.pages.setCurrentIndex(2)
        self._reload_offerings()
        self._classification_changed()
        if not periods and not self._courses:
            self.result.present(
                self.settings.texts.messages["assignment_empty_periods_and_courses"],
                success=False,
            )
        elif not periods:
            self.result.present(
                self.settings.texts.messages["assignment_empty_periods"],
                success=False,
            )
        elif not self._courses:
            self.result.present(
                self.settings.texts.messages["assignment_empty_courses"],
                success=False,
            )

    def _reload_offerings(self, *_args) -> None:
        self._invalidate_calculation()
        self.offering_combo.blockSignals(True)
        self.offering_combo.clear()
        period_id = self.period_combo.currentData()
        course_id = self.course_combo.currentData()
        if not period_id or not course_id:
            self.offering_combo.addItem(
                self.settings.texts.messages["assignment_no_offering_option"], ""
            )
            self.offering_combo.blockSignals(False)
            self._update_course_actions()
            return
        self.offering_combo.addItem(
            self.settings.texts.messages["assignment_create_offering"], ""
        )
        try:
            for offering in self.controller.list_offerings(period_id, course_id):
                label = self.settings.texts.messages[
                    "assignment_offering_format"
                ].format(section=offering.section_code)
                if offering.nrc:
                    label += self.settings.texts.messages[
                        "assignment_offering_nrc_suffix"
                    ].format(nrc=offering.nrc)
                self.offering_combo.addItem(label, offering.offering_id)
        except (AttributeError, RuntimeError) as error:
            self.result.present(str(error), success=False)
        finally:
            self.offering_combo.blockSignals(False)
        self._update_course_actions()

    def _populate_demand_combo(self) -> None:
        messages = self.settings.texts.messages
        self.demand_combo.clear()
        self.demand_combo.addItem(messages["assignment_demand_not_applicable"], "")
        for code in ("A", "B", "C", "D"):
            self.demand_combo.addItem(
                messages[f"assignment_demand_{code.lower()}"], code
            )

    def _classification_changed(self, *_args) -> None:
        self._invalidate_calculation()
        aaa = self.classification_combo.currentData() == "AAA"
        self.demand_combo.setEnabled(aaa and self._course_inputs_ready())
        if not aaa:
            self.demand_combo.setCurrentIndex(0)

    def _invalidate_calculation(self, *_args) -> None:
        self.save_button.setEnabled(False)
        if self.result.isVisible():
            self.result.clear_result()

    def _draft(self) -> CourseAssignmentDraft:
        try:
            participation = Decimal(str(self.participation_input.value()))
        except InvalidOperation as error:
            raise ValueError(
                self.settings.texts.messages["assignment_invalid_participation"]
            ) from error
        return CourseAssignmentDraft(
            self.selected_academic_id,
            self.period_combo.currentData() or "",
            self.course_combo.currentData() or "",
            self.classification_combo.currentData(),
            participation,
            self.offering_combo.currentData() or None,
            self.section_input.text(),
            self.nrc_input.text(),
            None,
            self.demand_combo.currentData() or None,
        )

    def _calculate(self) -> None:
        if not self._course_inputs_ready():
            self.result.present(
                self.settings.texts.messages["assignment_select_before_calculate"],
                success=False,
            )
            self.save_button.setEnabled(False)
            return
        try:
            preview = self.controller.calculate_course_assignment(self._draft())
        except (RuntimeError, ValueError) as error:
            self.result.present(str(error), success=False)
            self.save_button.setEnabled(False)
            return
        self.result.present(
            self.settings.texts.messages["assignment_calculation_result"].format(
                points=preview.calculated_points,
                policy=preview.policy_status,
            ),
            success=True,
        )
        self.save_button.setEnabled(self._course_inputs_ready())

    def _save(self) -> None:
        try:
            result = self.controller.create_course_assignment(self._draft())
        except (RuntimeError, ValueError) as error:
            self.result.present(str(error), success=False)
            return
        message = self.settings.texts.messages["assignment_saved_result"].format(
            points=result.calculated_points
        )
        self.result.present(message, success=True)
        self.save_button.setEnabled(False)
        self.saved.emit(message)

    def _course_inputs_ready(self) -> bool:
        return bool(self.period_combo.currentData() and self.course_combo.currentData())

    def _update_course_actions(self) -> None:
        ready = self._course_inputs_ready()
        self.calculate_button.setEnabled(ready)
        if not ready:
            self.save_button.setEnabled(False)
