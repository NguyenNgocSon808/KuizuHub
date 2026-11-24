"""Server-backed Phase 2–3 desktop workspace.

This module deliberately does not import ``MockApiService``.  It layers the
remaining room, practice, result, history, leaderboard, and profile screens on
top of the same QThread-backed TCP service used by the Phase 1 surfaces.
"""

from __future__ import annotations

from datetime import datetime, timezone
from math import ceil
from time import monotonic
from typing import Any

from PySide6.QtCore import QPoint, Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QRadioButton,
    QScrollArea,
    QSizePolicy,
    QSpinBox,
    QStackedWidget,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ..config import APP_TITLE, WINDOW_MIN_HEIGHT, WINDOW_MIN_WIDTH
from ..services.tcp_api_service import PhaseOneApiService
from .phase1_main_window import LiveAuthPage, LiveDashboardPage, LiveUser, QuestionBankPage, _response_data
from .widgets import ChartCanvas, MetricCard, PrimaryButton, SecondaryButton, StatusBadge, UserAvatar, show_toast


def _wire_data(response: object) -> dict[str, Any]:
    return _response_data(response)


def _safe_int(value: object, default: int = 0) -> int:
    return value if isinstance(value, int) else default


def _safe_float(value: object, default: float = 0.0) -> float:
    return float(value) if isinstance(value, (int, float)) else default


def _format_duration(seconds: object) -> str:
    value = _safe_int(seconds)
    return f"{value // 60} phút {value % 60:02d}s"


class CreateRoomDialog(QDialog):
    """Build a validated CREATE_ROOM payload without guessing question rules."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Tạo phòng thi")
        self.setMinimumWidth(620)
        self._rules: list[tuple[QFrame, QLineEdit, QComboBox, QSpinBox]] = []
        root = QVBoxLayout(self)
        form = QFormLayout()
        self.name = QLineEdit()
        self.name.setPlaceholderText("Ví dụ: Kiểm tra TCP")
        self.duration = QSpinBox()
        self.duration.setRange(60, 7200)
        self.duration.setValue(600)
        self.duration.setSuffix(" giây")
        form.addRow("Tên phòng", self.name)
        form.addRow("Thời lượng", self.duration)
        root.addLayout(form)
        header = QHBoxLayout()
        header.addWidget(QLabel("Quy tắc chọn câu hỏi"))
        header.addStretch()
        add_rule = SecondaryButton("+ Thêm rule")
        add_rule.clicked.connect(self._add_rule)
        header.addWidget(add_rule)
        root.addLayout(header)
        self.rules_layout = QVBoxLayout()
        root.addLayout(self.rules_layout)
        self.notice = QLabel()
        self.notice.setObjectName("subtle")
        self.notice.setWordWrap(True)
        root.addWidget(self.notice)
        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self._accept_if_valid)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)
        self._add_rule()

    def _add_rule(self) -> None:
        frame = QFrame()
        frame.setObjectName("sectionCard")
        row = QHBoxLayout(frame)
        row.setContentsMargins(10, 8, 10, 8)
        topic = QLineEdit("TCP Socket")
        topic.setPlaceholderText("Chủ đề")
        difficulty = QComboBox()
        difficulty.addItem("Dễ", "easy")
        difficulty.addItem("Trung bình", "medium")
        difficulty.addItem("Khó", "hard")
        quantity = QSpinBox()
        quantity.setRange(1, 50)
        quantity.setValue(3)
        remove = SecondaryButton("Bỏ")
        remove.clicked.connect(lambda: self._remove_rule(frame))
        row.addWidget(topic, 3)
        row.addWidget(difficulty, 2)
        row.addWidget(quantity)
        row.addWidget(remove)
        self.rules_layout.addWidget(frame)
        self._rules.append((frame, topic, difficulty, quantity))

    def _remove_rule(self, frame: QFrame) -> None:
        if len(self._rules) <= 1:
            self.notice.setText("Phòng cần ít nhất một rule.")
            return
        self._rules = [rule for rule in self._rules if rule[0] is not frame]
        self.rules_layout.removeWidget(frame)
        frame.deleteLater()

    def payload(self) -> dict[str, Any]:
        rules: list[dict[str, Any]] = []
        seen: set[tuple[str, str]] = set()
        for _frame, topic, difficulty, quantity in self._rules:
            topic_value = topic.text().strip()
            difficulty_value = str(difficulty.currentData())
            key = (topic_value, difficulty_value)
            if not topic_value:
                raise ValueError("Mỗi rule phải có chủ đề.")
            if key in seen:
                raise ValueError("Không được lặp cùng chủ đề và độ khó.")
            seen.add(key)
            rules.append({
                "topic": topic_value,
                "difficulty": difficulty_value,
                "quantity": quantity.value(),
            })
        name = self.name.text().strip()
        if not name:
            raise ValueError("Tên phòng là bắt buộc.")
        return {"name": name, "duration_seconds": self.duration.value(), "rules": rules}

    def _accept_if_valid(self) -> None:
        try:
            self.payload()
        except ValueError as error:
            self.notice.setText(str(error))
            return
        self.accept()


class LiveRoomsPage(QWidget):
    exam_requested = Signal(int)
    results_requested = Signal(int)
    leaderboard_requested = Signal(int)
    lobby_requested = Signal(int)

    def __init__(self, service: PhaseOneApiService, user: LiveUser) -> None:
        super().__init__()
        self.service = service
        self.user = user
        self.rooms: list[dict[str, Any]] = []
        self._pending: dict[str, str] = {}
        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)
        header = QHBoxLayout()
        copy = QVBoxLayout()
        title = QLabel("Phòng thi")
        title.setObjectName("pageTitle")
        copy.addWidget(title)
        detail = QLabel("Danh sách phòng và mọi thao tác đều đi qua TCP server.")
        detail.setObjectName("subtle")
        copy.addWidget(detail)
        header.addLayout(copy, 1)
        refresh = SecondaryButton("Làm mới")
        refresh.clicked.connect(self.refresh)
        header.addWidget(refresh)
        if user.role in {"HOST", "ADMIN"}:
            create = PrimaryButton("+ Tạo phòng")
            create.clicked.connect(self._create_room)
            header.addWidget(create)
        root.addLayout(header)
        self.notice = QLabel("Đang tải phòng…")
        self.notice.setObjectName("subtle")
        root.addWidget(self.notice)
        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels(
            ["Tên phòng", "Chủ phòng", "Trạng thái", "Thí sinh", "Thời lượng", "Thao tác"]
        )
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.verticalHeader().setVisible(False)
        self.table.verticalHeader().setDefaultSectionSize(46)
        self.table.verticalHeader().setMinimumSectionSize(46)
        # One action column uses the remaining horizontal space. Its child layout
        # keeps every button at its own text-driven size.
        self.table.horizontalHeader().setStretchLastSection(True)
        root.addWidget(self.table, 1)
        self.service.request_succeeded.connect(self._on_success)
        self.service.request_failed.connect(self._on_failure)

    def refresh(self) -> None:
        request_id = self.service.list_rooms()
        self._pending[request_id] = "list"
        self.notice.setText("Đang tải phòng…")

    def _create_room(self) -> None:
        dialog = CreateRoomDialog(self)
        if dialog.exec() != QDialog.Accepted:
            return
        payload = dialog.payload()
        request_id = self.service.create_room(
            str(payload["name"]), _safe_int(payload["duration_seconds"]), list(payload["rules"])
        )
        self._pending[request_id] = "create"
        self.notice.setText("Đang tạo phòng…")

    def _join(self, room_id: int) -> None:
        request_id = self.service.join_room(room_id)
        self._pending[request_id] = "join"
        self.notice.setText("Đang tham gia phòng…")

    def _start(self, room_id: int) -> None:
        if QMessageBox.question(
            self, "Bắt đầu phòng", "Bắt đầu sẽ chốt đề và không cho thí sinh mới tham gia.",
            QMessageBox.Yes | QMessageBox.No,
        ) != QMessageBox.Yes:
            return
        request_id = self.service.start_room(room_id)
        self._pending[request_id] = "start"
        self.notice.setText("Đang chốt đề và bắt đầu phòng…")

    def _end(self, room_id: int) -> None:
        if QMessageBox.question(
            self, "Kết thúc phòng", "Kết thúc ngay và chấm các đáp án đã lưu của mọi thí sinh?",
            QMessageBox.Yes | QMessageBox.No,
        ) == QMessageBox.Yes:
            self._pending[self.service.end_room(room_id)] = "end"
            self.notice.setText("Đang kết thúc phòng…")

    def _render(self) -> None:
        self.table.setRowCount(len(self.rooms))
        status_column_width = 0
        action_column_width = 0
        for row, room in enumerate(self.rooms):
            room_id = _safe_int(room.get("id"))
            status = str(room.get("status", "WAITING"))
            values = [
                str(room.get("name", "")),
                str(room.get("owner_name", "")),
                "",
                str(room.get("participant_count", 0)),
                _format_duration(room.get("duration_seconds")),
            ]
            for column, value in enumerate(values):
                if column == 2:
                    badge = StatusBadge(status)
                    badge.setSizePolicy(QSizePolicy.Minimum, QSizePolicy.Fixed)
                    badge.setMinimumWidth(badge.sizeHint().width())
                    status_column_width = max(status_column_width, badge.sizeHint().width() + 16)
                    self.table.setCellWidget(row, column, badge)
                else:
                    self.table.setItem(row, column, QTableWidgetItem(value))
            action_cell = QWidget()
            action_layout = QHBoxLayout(action_cell)
            action_layout.setContentsMargins(8, 2, 8, 2)
            action_layout.setSpacing(8)
            if status == "WAITING":
                if _safe_int(room.get("owner_id")) == self.user.id:
                    button = PrimaryButton("Bắt đầu")
                    button.clicked.connect(lambda _checked=False, rid=room_id: self._start(rid))
                else:
                    button = PrimaryButton("Tham gia")
                    button.clicked.connect(lambda _checked=False, rid=room_id: self._join(rid))
                action_layout.addWidget(button)
                lobby = SecondaryButton("Sảnh chờ")
                lobby.clicked.connect(lambda _checked=False, rid=room_id: self.lobby_requested.emit(rid))
                action_layout.addWidget(lobby)
            elif status == "RUNNING":
                if _safe_int(room.get("owner_id")) == self.user.id:
                    button = SecondaryButton("Kết thúc phòng")
                    button.clicked.connect(lambda _checked=False, rid=room_id: self._end(rid))
                else:
                    button = PrimaryButton("Vào thi")
                    button.clicked.connect(lambda _checked=False, rid=room_id: self.exam_requested.emit(rid))
                action_layout.addWidget(button)
            elif status == "ENDED":
                button = SecondaryButton("Kết quả")
                button.clicked.connect(lambda _checked=False, rid=room_id: self.results_requested.emit(rid))
                action_layout.addWidget(button)
                leaderboard = SecondaryButton("BXH")
                leaderboard.clicked.connect(lambda _checked=False, rid=room_id: self.leaderboard_requested.emit(rid))
                action_layout.addWidget(leaderboard)
            action_layout.addStretch()
            action_layout.activate()
            action_cell.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
            action_column_width = max(action_column_width, action_cell.sizeHint().width() + 16)
            self.table.setCellWidget(row, 5, action_cell)
            # Button cells have a larger minimum height than plain table text.
            # Set it explicitly so Qt does not clip their labels or the status badge.
            self.table.setRowHeight(row, 46)
        self.table.resizeColumnsToContents()
        self.table.setColumnWidth(0, max(260, self.table.columnWidth(0)))
        self.table.setColumnWidth(2, max(112, status_column_width))
        self.table.setColumnWidth(5, max(188, action_column_width))

    def _on_success(self, request_id: str, response: object) -> None:
        action = self._pending.pop(request_id, None)
        if action is None:
            return
        try:
            data = _wire_data(response)
            if action == "list":
                raw_rooms = data.get("rooms")
                if not isinstance(raw_rooms, list) or not all(isinstance(room, dict) for room in raw_rooms):
                    raise ValueError("Server trả về dữ liệu phòng không hợp lệ.")
                self.rooms = raw_rooms
                self.notice.setText(f"Có {len(self.rooms)} phòng.")
                self._render()
                return
        except ValueError as error:
            self.notice.setText(str(error))
            return
        messages = {
            "create": "Đã tạo phòng.", "join": "Đã tham gia phòng.",
            "start": "Phòng đã bắt đầu.", "end": "Phòng đã kết thúc và các bài đã được chấm.",
        }
        message = messages.get(action, "Đã hoàn tất.")
        self.notice.setText(message)
        show_toast(self, message)
        self.refresh()

    def _on_failure(self, request_id: str, message: str) -> None:
        if self._pending.pop(request_id, None) is not None:
            self.notice.setText(f"Không thể hoàn tất: {message}")
            QMessageBox.warning(self, "Yêu cầu thất bại", message)


class LivePracticePage(QWidget):
    exam_ready = Signal(object)

    def __init__(self, service: PhaseOneApiService) -> None:
        super().__init__()
        self.service = service
        self._pending: set[str] = set()
        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)
        title = QLabel("Luyện tập")
        title.setObjectName("pageTitle")
        root.addWidget(title)
        detail = QLabel("Server chọn và chấm đề; client không nhận đáp án đúng khi đang làm bài.")
        detail.setObjectName("subtle")
        detail.setWordWrap(True)
        root.addWidget(detail)
        form_card = QFrame()
        form_card.setObjectName("sectionCard")
        form = QFormLayout(form_card)
        self.topic = QLineEdit("TCP Socket")
        self.difficulty = QComboBox()
        self.difficulty.addItem("Dễ", "easy")
        self.difficulty.addItem("Trung bình", "medium")
        self.difficulty.addItem("Khó", "hard")
        self.count = QSpinBox()
        self.count.setRange(1, 20)
        self.count.setValue(3)
        self.duration = QSpinBox()
        self.duration.setRange(60, 7200)
        self.duration.setValue(600)
        self.duration.setSuffix(" giây")
        form.addRow("Chủ đề", self.topic)
        form.addRow("Độ khó", self.difficulty)
        form.addRow("Số câu", self.count)
        form.addRow("Thời lượng", self.duration)
        root.addWidget(form_card)
        self.notice = QLabel()
        self.notice.setObjectName("subtle")
        root.addWidget(self.notice)
        start = PrimaryButton("Bắt đầu luyện tập")
        start.clicked.connect(self._start)
        root.addWidget(start, alignment=Qt.AlignLeft)
        root.addStretch()
        self.service.request_succeeded.connect(self._on_success)
        self.service.request_failed.connect(self._on_failure)

    def _start(self) -> None:
        topic = self.topic.text().strip()
        if not topic:
            self.notice.setText("Chủ đề là bắt buộc.")
            return
        request_id = self.service.start_practice(
            topic, str(self.difficulty.currentData()), self.count.value(), self.duration.value()
        )
        self._pending.add(request_id)
        self.notice.setText("Server đang tạo snapshot đề luyện tập…")

    def _on_success(self, request_id: str, response: object) -> None:
        if request_id not in self._pending:
            return
        self._pending.remove(request_id)
        try:
            self.exam_ready.emit(_wire_data(response))
        except ValueError as error:
            self.notice.setText(str(error))

    def _on_failure(self, request_id: str, message: str) -> None:
        if request_id in self._pending:
            self._pending.remove(request_id)
            self.notice.setText(f"Không thể bắt đầu: {message}")


class _ExamOption(QRadioButton):
    def __init__(self, text: str) -> None:
        super().__init__()
        self.setObjectName("answerOption")
        self.setAccessibleName(text)
        label = QLabel(text)
        label.setTextFormat(Qt.PlainText)
        label.setWordWrap(True)
        label.setAttribute(Qt.WA_TransparentForMouseEvents)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(45, 13, 13, 13)
        layout.addWidget(label)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)

    def hitButton(self, position: QPoint) -> bool:
        return self.rect().contains(position)


class LiveExamPage(QWidget):
    submitted = Signal(object, bool, int)
    back_requested = Signal()

    def __init__(self, service: PhaseOneApiService) -> None:
        super().__init__()
        self.service = service
        self.mode = "room"
        self.room_id = 0
        self.attempt_id = 0
        self.questions: list[dict[str, Any]] = []
        self.answers: dict[int, int] = {}
        self.saved_answers: dict[int, int] = {}
        self.current_index = 0
        self._pending_saves: dict[str, tuple[int, int]] = {}
        self._submit_request: str | None = None
        self._deadline: float | None = None
        self._expired = False
        self._finished = False
        self._answer_group = QButtonGroup(self)
        self.timer = QTimer(self)
        self.timer.timeout.connect(self._tick)
        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)
        header = QHBoxLayout()
        self.title = QLabel("Làm bài")
        self.title.setObjectName("pageTitle")
        header.addWidget(self.title, 1)
        self.countdown = QLabel()
        self.countdown.setObjectName("sectionTitle")
        header.addWidget(self.countdown)
        root.addLayout(header)
        self.notice = QLabel()
        self.notice.setObjectName("subtle")
        self.notice.setWordWrap(True)
        root.addWidget(self.notice)
        body = QHBoxLayout()
        self.navigator = QComboBox()
        self.navigator.setMinimumWidth(120)
        self.navigator.currentIndexChanged.connect(self._select_question)
        body.addWidget(self.navigator, 1)
        content = QFrame()
        content.setObjectName("sectionCard")
        self.content_layout = QVBoxLayout(content)
        self.question_label = QLabel()
        self.question_label.setTextFormat(Qt.PlainText)
        self.question_label.setWordWrap(True)
        self.question_label.setObjectName("sectionTitle")
        self.content_layout.addWidget(self.question_label)
        self.options_layout = QVBoxLayout()
        self.content_layout.addLayout(self.options_layout)
        self.content_layout.addStretch()
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(content)
        body.addWidget(scroll, 5)
        root.addLayout(body, 1)
        footer = QHBoxLayout()
        self.back_button = SecondaryButton("← Danh sách phòng")
        self.back_button.clicked.connect(self.back_requested)
        footer.addWidget(self.back_button)
        footer.addStretch()
        self.retry_button = SecondaryButton("Lưu lại đáp án")
        self.retry_button.clicked.connect(self._retry_answer)
        self.retry_button.hide()
        footer.addWidget(self.retry_button)
        self.submit_button = PrimaryButton("Nộp bài")
        self.submit_button.clicked.connect(self._submit)
        footer.addWidget(self.submit_button)
        root.addLayout(footer)
        self.service.request_succeeded.connect(self._on_success)
        self.service.request_failed.connect(self._on_failure)

    def load_exam(self, data: dict[str, Any], *, practice: bool) -> None:
        raw_questions = data.get("questions")
        if not isinstance(raw_questions, list) or not raw_questions or not all(isinstance(question, dict) for question in raw_questions):
            raise ValueError("Server trả về đề thi không hợp lệ.")
        self.mode = "practice" if practice else "room"
        self.room_id = _safe_int(data.get("room_id"))
        self.attempt_id = _safe_int(data.get("attempt_id"))
        self.questions = raw_questions
        self.answers = {}
        self._pending_saves.clear()
        self._submit_request = None
        self._expired = False
        self._finished = False
        self._deadline = None
        remaining = data.get("remaining_seconds")
        if isinstance(remaining, int):
            self._deadline = monotonic() + max(0, remaining)
        elif isinstance(data.get("ended_at"), str):
            try:
                deadline = datetime.strptime(data["ended_at"], "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
                self._deadline = monotonic() + (deadline - datetime.now(timezone.utc)).total_seconds()
            except ValueError:
                pass
        selected_key = "selected_option_position" if practice else "selected_option_id"
        for question in self.questions:
            question_id = _safe_int(question.get("id"))
            selected = question.get(selected_key)
            if question_id > 0 and isinstance(selected, int):
                self.answers[question_id] = selected
        self.saved_answers = self.answers.copy()
        self.title.setText("Luyện tập" if practice else "Làm bài thi phòng")
        self.back_button.setText("← Luyện tập" if practice else "← Danh sách phòng")
        self.navigator.blockSignals(True)
        self.navigator.clear()
        for index, question in enumerate(self.questions, start=1):
            marker = " ✓" if _safe_int(question.get("id")) in self.answers else ""
            self.navigator.addItem(f"Câu {index}{marker}", index - 1)
        self.navigator.setCurrentIndex(0)
        self.navigator.blockSignals(False)
        self.current_index = 0
        self.submit_button.setText("Nộp bài")
        self._render_question()
        self._update_controls()
        self.notice.setText("Chọn đáp án để tự động lưu trên server.")
        self.timer.start(1000)
        self._tick()

    def _select_question(self, index: int) -> None:
        if 0 <= index < len(self.questions):
            self.current_index = index
            self._render_question()
            self._update_controls()

    def _render_question(self) -> None:
        if not self.questions:
            self.question_label.setText("Chưa có đề thi.")
            return
        question = self.questions[self.current_index]
        question_id = _safe_int(question.get("id"))
        position = _safe_int(question.get("position"), self.current_index + 1)
        self.question_label.setText(f"Câu {position}. {question.get('content', '')}")
        while self.options_layout.count():
            item = self.options_layout.takeAt(0)
            if item.widget() is not None:
                item.widget().hide()
                item.widget().deleteLater()
        for button in self._answer_group.buttons():
            self._answer_group.removeButton(button)
        raw_options = question.get("options")
        if not isinstance(raw_options, list):
            self.notice.setText("Dữ liệu đáp án không hợp lệ.")
            return
        for raw_option in raw_options:
            if not isinstance(raw_option, dict):
                continue
            value = _safe_int(raw_option.get("position") if self.mode == "practice" else raw_option.get("id"))
            if value <= 0:
                continue
            label = str(raw_option.get("label", ""))
            content = str(raw_option.get("content", ""))
            button = _ExamOption(f"{label}. {content}")
            self._answer_group.addButton(button, value)
            if self.answers.get(question_id) == value:
                button.setChecked(True)
            button.toggled.connect(
                lambda checked, chosen=value, qid=question_id: self._answer_selected(qid, chosen, checked)
            )
            self.options_layout.addWidget(button)
        self.options_layout.addStretch()

    def _answer_selected(self, question_id: int, value: int, checked: bool) -> None:
        if not checked or question_id <= 0 or self._expired or self._finished or self._submit_request:
            return
        self.answers[question_id] = value
        self._save_answer(question_id, value)

    def _save_answer(self, question_id: int, value: int) -> None:
        if self.mode == "practice":
            request_id = self.service.save_practice_answer(self.attempt_id, question_id, value)
        else:
            request_id = self.service.save_answer(self.room_id, question_id, value)
        self._pending_saves[request_id] = (question_id, value)
        self._update_answer_marker(question_id)
        self._update_controls()
        self.notice.setText("?ang l?u ??p ?n?")

    def _update_answer_marker(self, question_id: int) -> None:
        pending = any(qid == question_id for qid, _ in self._pending_saves.values())
        if pending:
            marker = " ?"
        elif question_id not in self.answers:
            marker = ""
        elif self.saved_answers.get(question_id) == self.answers[question_id]:
            marker = " ?"
        else:
            marker = " !"
        for index, question in enumerate(self.questions):
            if question.get("id") == question_id:
                self.navigator.setItemText(index, f"C?u {index + 1}{marker}")
                break

    def _update_controls(self) -> None:
        available = bool(self.questions) and self._submit_request is None and not self._finished
        for button in self._answer_group.buttons():
            button.setEnabled(available and not self._expired)
        self.submit_button.setEnabled(available and not self._pending_saves)
        self.retry_button.setVisible(
            available and not self._expired and not self._pending_saves
            and self._current_unsaved_answer() is not None
        )

    def _current_unsaved_answer(self) -> tuple[int, int] | None:
        if self.questions:
            question_id = _safe_int(self.questions[self.current_index].get("id"))
            value = self.answers.get(question_id)
            if value is not None and self.saved_answers.get(question_id) != value:
                return question_id, value
        return None

    def _retry_answer(self) -> None:
        selected = self._current_unsaved_answer()
        if selected is not None:
            self._save_answer(*selected)

    def _submit(self) -> None:
        if not self.submit_button.isEnabled():
            return
        if self._expired:
            self._send_submission()
            return
        unanswered = len(self.questions) - len(self.answers)
        unsaved = sum(self.saved_answers.get(qid) != value for qid, value in self.answers.items())
        message = f"B?n c?n {unanswered} c?u ch?a ch?n."
        if unsaved:
            message += f" C? {unsaved} l?a ch?n ch?a ???c x?c nh?n l?u. Server s? ch?m theo ??p ?n ?? l?u."
        if QMessageBox.question(
            self, "X?c nh?n n?p b?i", f"{message} N?p b?i ngay?",
            QMessageBox.Yes | QMessageBox.No,
        ) == QMessageBox.Yes and not self._expired and self.submit_button.isEnabled():
            self._send_submission()

    def _send_submission(self) -> None:
        if self._submit_request is not None or self._finished or self._pending_saves:
            return
        if self.mode == "practice":
            self._submit_request = self.service.submit_practice(self.attempt_id)
        else:
            self._submit_request = self.service.submit_exam(self.room_id)
        self._update_controls()
        self.notice.setText("?? h?t gi?. ?ang l?y k?t qu??" if self._expired else "Server ?ang ch?m b?i?")

    def _tick(self) -> None:
        if self._deadline is None:
            self.countdown.clear()
            return
        remaining = max(0, ceil(self._deadline - monotonic()))
        self.countdown.setText(f"C?n {remaining // 60:02d}:{remaining % 60:02d}")
        if remaining == 0:
            self._expired = True
            self.timer.stop()
            self.submit_button.setText("L?y k?t qu?")
            self._update_controls()
            if self._pending_saves:
                self.notice.setText("?? h?t gi?. ?ang ch? ph?n h?i l?u ??p ?n?")
            else:
                self._send_submission()

    def _on_success(self, request_id: str, response: object) -> None:
        if request_id not in self._pending_saves and request_id != self._submit_request:
            return
        try:
            data = _wire_data(response)
            if request_id in self._pending_saves and data.get("saved") is not True:
                raise ValueError("Server ch?a x?c nh?n l?u ??p ?n.")
        except ValueError as error:
            self._on_failure(request_id, str(error))
            return
        if request_id in self._pending_saves:
            question_id, value = self._pending_saves.pop(request_id)
            self.saved_answers[question_id] = value
            self._update_answer_marker(question_id)
            self._update_controls()
            if self._expired:
                self._send_submission()
            elif self._pending_saves:
                self.notice.setText("?ang l?u ??p ?n?")
            elif any(self.saved_answers.get(qid) != answer for qid, answer in self.answers.items()):
                self.notice.setText("M?t s? ??p ?n ch?a ???c x?c nh?n l?u. Ch?n c?u ??nh d?u ! ?? l?u l?i.")
            else:
                self.notice.setText("?? l?u ??p ?n tr?n server.")
            return
        self._submit_request = None
        self._finished = True
        self.timer.stop()
        self._update_controls()
        self.notice.setText("?? n?p b?i.")
        self.submitted.emit(data, self.mode == "practice", self.room_id)

    def _on_failure(self, request_id: str, message: str) -> None:
        pending = self._pending_saves.pop(request_id, None)
        if pending is not None:
            self._update_answer_marker(pending[0])
            self._update_controls()
            self.notice.setText(f"Kh?ng th? l?u ??p ?n: {message}")
            if self._expired:
                self._send_submission()
        elif request_id == self._submit_request:
            self._submit_request = None
            self._update_controls()
            self.notice.setText(f"Kh?ng th? l?y k?t qu?: {message}" if self._expired else f"Kh?ng th? n?p b?i: {message}")

    def stop(self) -> None:
        self.timer.stop()
        self._pending_saves.clear()
        self._submit_request = None
        self._finished = True
        self._update_controls()


class LiveLobbyDialog(QDialog):
    """Refreshable waiting-room view for an owner or an already joined user."""

    def __init__(self, service: PhaseOneApiService, data: dict[str, Any], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.service = service
        self.room_id = _safe_int((data.get("room") or {}).get("id") if isinstance(data.get("room"), dict) else 0)
        self._pending: set[str] = set()
        self.setWindowTitle("Sảnh chờ")
        self.setMinimumSize(520, 360)
        root = QVBoxLayout(self)
        self.title = QLabel()
        self.title.setObjectName("pageTitle")
        root.addWidget(self.title)
        self.detail = QLabel()
        self.detail.setObjectName("subtle")
        root.addWidget(self.detail)
        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(["ID", "Người tham gia", "Trạng thái"])
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setStretchLastSection(True)
        root.addWidget(self.table, 1)
        buttons = QDialogButtonBox(QDialogButtonBox.Close)
        refresh = buttons.addButton("Làm mới", QDialogButtonBox.ActionRole)
        refresh.clicked.connect(self.refresh)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)
        self.service.request_succeeded.connect(self._on_success)
        self.service.request_failed.connect(self._on_failure)
        self.load_data(data)

    def load_data(self, data: dict[str, Any]) -> None:
        room = data.get("room") if isinstance(data.get("room"), dict) else {}
        self.room_id = _safe_int(room.get("id"), self.room_id)
        self.title.setText(f"Sảnh chờ · {room.get('name', '')}")
        self.detail.setText(
            f"Trạng thái: {room.get('status', '')} · "
            f"Thời lượng: {_format_duration(room.get('duration_seconds'))}. "
            "Danh sách này được tải từ server."
        )
        raw_participants = data.get("participants")
        participants = raw_participants if isinstance(raw_participants, list) else []
        self.table.setRowCount(len(participants))
        for row, participant in enumerate(participants):
            if not isinstance(participant, dict):
                continue
            values = [
                str(participant.get("user_id", "")),
                str(participant.get("display_name", "")),
                str(participant.get("state", "")),
            ]
            for column, value in enumerate(values):
                self.table.setItem(row, column, QTableWidgetItem(value))
        self.table.resizeColumnsToContents()

    def refresh(self) -> None:
        if self.room_id <= 0:
            return
        request_id = self.service.get_room_lobby(self.room_id)
        self._pending.add(request_id)
        self.detail.setText("Đang tải lại danh sách người tham gia…")

    def _on_success(self, request_id: str, response: object) -> None:
        if request_id not in self._pending:
            return
        self._pending.remove(request_id)
        try:
            self.load_data(_wire_data(response))
        except ValueError as error:
            self.detail.setText(str(error))

    def _on_failure(self, request_id: str, message: str) -> None:
        if request_id in self._pending:
            self._pending.remove(request_id)
            self.detail.setText(f"Không thể tải sảnh chờ: {message}")


class LiveResultPage(QWidget):
    rooms_requested = Signal()

    def __init__(self) -> None:
        super().__init__()
        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)
        self.title = QLabel("Kết quả")
        self.title.setObjectName("pageTitle")
        root.addWidget(self.title)
        self.summary = QLabel("Chưa có kết quả để hiển thị.")
        self.summary.setObjectName("subtle")
        self.summary.setWordWrap(True)
        root.addWidget(self.summary)
        self.results = QTableWidget(0, 7)
        self.results.setHorizontalHeaderLabels(["Hạng", "Người dùng", "Trạng thái", "Đúng", "Tổng", "Điểm", "Nộp lúc"])
        self.results.setEditTriggers(QTableWidget.NoEditTriggers)
        self.results.verticalHeader().setVisible(False)
        self.results.horizontalHeader().setStretchLastSection(True)
        root.addWidget(self.results, 1)
        self.review = QTableWidget(0, 5)
        self.review.setHorizontalHeaderLabels(["Câu", "Nội dung", "Bạn chọn", "Đáp án", "Kết quả"])
        self.review.setEditTriggers(QTableWidget.NoEditTriggers)
        self.review.verticalHeader().setVisible(False)
        self.review.horizontalHeader().setStretchLastSection(True)
        root.addWidget(self.review, 1)
        footer = QHBoxLayout()
        rooms = SecondaryButton("← Phòng thi")
        rooms.clicked.connect(self.rooms_requested)
        footer.addWidget(rooms)
        footer.addStretch()
        root.addLayout(footer)

    def show_submission(self, data: dict[str, Any], *, practice: bool) -> None:
        self.title.setText("Kết quả luyện tập" if practice else "Đã nộp bài thi")
        self.summary.setText(
            f"Điểm: {_safe_float(data.get('score')):.2f}/10 · "
            f"Đúng {_safe_int(data.get('correct_count'))}/{_safe_int(data.get('total'))} · "
            f"Trạng thái {data.get('state', '')}."
        )
        self.results.setRowCount(0)
        self.review.setRowCount(0)

    def show_room_results(self, data: dict[str, Any]) -> None:
        room = data.get("room") if isinstance(data.get("room"), dict) else {}
        self.title.setText(f"Kết quả · {room.get('name', '')}")
        scope = str(data.get("scope", "participant"))
        self.summary.setText(
            "Chủ phòng xem toàn bộ kết quả." if scope == "owner" else "Chỉ hiển thị kết quả của bạn sau khi phòng kết thúc."
        )
        raw_results = data.get("results")
        results = raw_results if isinstance(raw_results, list) else []
        self.results.setRowCount(len(results))
        for row, value in enumerate(results):
            if not isinstance(value, dict):
                continue
            cells = [
                str(row + 1), str(value.get("username", "")), str(value.get("state", "")),
                str(value.get("correct_count", "")), str(value.get("total", "")),
                f"{_safe_float(value.get('score')):.2f}", str(value.get("submitted_at") or "—"),
            ]
            for column, text in enumerate(cells):
                self.results.setItem(row, column, QTableWidgetItem(text))
        raw_review = data.get("review")
        review = raw_review if isinstance(raw_review, list) else []
        self.review.setRowCount(len(review))
        for row, value in enumerate(review):
            if not isinstance(value, dict):
                continue
            options = value.get("options") if isinstance(value.get("options"), list) else []
            option_labels = { _safe_int(option.get("id")): str(option.get("label", ""))
                              for option in options if isinstance(option, dict) }
            selected = option_labels.get(_safe_int(value.get("selected_option_id")), "Chưa chọn")
            correct = option_labels.get(_safe_int(value.get("correct_option_id")), "")
            cells = [
                str(value.get("position", "")), str(value.get("content", "")), selected, correct,
                "Đúng" if value.get("is_correct") else "Sai/chưa làm",
            ]
            for column, text in enumerate(cells):
                self.review.setItem(row, column, QTableWidgetItem(text))
        self.results.resizeColumnsToContents()
        self.review.resizeColumnsToContents()
        if data.get("results_truncated") or data.get("review_truncated"):
            self.summary.setText(self.summary.text() + " Dữ liệu dài đã được phân trang/rút gọn để bảo vệ giới hạn giao thức.")

    def show_leaderboard(self, data: dict[str, Any]) -> None:
        self.title.setText(f"Bảng xếp hạng · {data.get('room_name', '')}")
        self.summary.setText("Bảng xếp hạng chỉ công bố sau khi phòng đã kết thúc.")
        raw_entries = data.get("entries")
        entries = raw_entries if isinstance(raw_entries, list) else []
        self.results.setRowCount(len(entries))
        for row, value in enumerate(entries):
            if not isinstance(value, dict):
                continue
            cells = [
                str(value.get("rank", row + 1)), str(value.get("username", "")), str(value.get("state", "")),
                str(value.get("correct_count", "")), str(value.get("total", "")),
                f"{_safe_float(value.get('score')):.2f}", str(value.get("submitted_at") or "—"),
            ]
            for column, text in enumerate(cells):
                self.results.setItem(row, column, QTableWidgetItem(text))
        self.review.setRowCount(0)
        self.results.resizeColumnsToContents()


class LiveHistoryPage(QWidget):
    def __init__(self, service: PhaseOneApiService) -> None:
        super().__init__()
        self.service = service
        self._pending: dict[str, str] = {}
        self._history: list[dict[str, Any]] = []
        self._stats: dict[str, Any] = {}
        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)
        header = QHBoxLayout()
        title = QLabel("Lịch sử và thống kê")
        title.setObjectName("pageTitle")
        header.addWidget(title, 1)
        refresh = SecondaryButton("Làm mới")
        refresh.clicked.connect(self.refresh)
        header.addWidget(refresh)
        root.addLayout(header)
        metrics = QHBoxLayout()
        self.metric_attempts = MetricCard("Bài đã hoàn thành", "0")
        self.metric_average = MetricCard("Điểm trung bình", "0.00/10")
        self.metric_accuracy = MetricCard("Tỷ lệ đúng", "0%")
        self.metric_streak = MetricCard("Chuỗi học", "0 ngày")
        for metric in (self.metric_attempts, self.metric_average, self.metric_accuracy, self.metric_streak):
            metrics.addWidget(metric)
        root.addLayout(metrics)
        charts = QHBoxLayout()
        self.score_chart = ChartCanvas(4.3, 2.4)
        self.topic_chart = ChartCanvas(4.3, 2.4)
        charts.addWidget(self.score_chart, 1)
        charts.addWidget(self.topic_chart, 1)
        root.addLayout(charts)
        self.notice = QLabel()
        self.notice.setObjectName("subtle")
        root.addWidget(self.notice)
        self.table = QTableWidget(0, 7)
        self.table.setHorizontalHeaderLabels(["Loại", "Tên", "Chủ đề", "Độ khó", "Đúng/Tổng", "Điểm", "Hoàn thành"])
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setStretchLastSection(True)
        root.addWidget(self.table, 1)
        self.service.request_succeeded.connect(self._on_success)
        self.service.request_failed.connect(self._on_failure)

    def refresh(self) -> None:
        self._pending[self.service.get_my_stats()] = "stats"
        self._pending[self.service.get_my_history(limit=50)] = "history"
        self.notice.setText("Đang tải lịch sử và thống kê…")

    def _render(self) -> None:
        self.metric_attempts.set_value(str(_safe_int(self._stats.get("attempts"))))
        self.metric_average.set_value(f"{_safe_float(self._stats.get('average_score')):.2f}/10")
        self.metric_accuracy.set_value(f"{_safe_float(self._stats.get('accuracy_percent')):.1f}%")
        self.metric_streak.set_value(f"{_safe_int(self._stats.get('streak_days'))} ngày")
        self.table.setRowCount(len(self._history))
        for row, attempt in enumerate(self._history):
            cells = [
                str(attempt.get("kind", "")), str(attempt.get("title", "")), str(attempt.get("topic", "")),
                str(attempt.get("difficulty", "")),
                f"{_safe_int(attempt.get('correct_count'))}/{_safe_int(attempt.get('total'))}",
                f"{_safe_float(attempt.get('score')):.2f}", str(attempt.get("completed_at", "")),
            ]
            for column, text in enumerate(cells):
                self.table.setItem(row, column, QTableWidgetItem(text))
        self.table.resizeColumnsToContents()
        score_axis = self.score_chart.axes()
        ordered = list(reversed(self._history))
        scores = [_safe_float(attempt.get("score")) for attempt in ordered]
        score_axis.plot(range(1, len(scores) + 1), scores, marker="o", color="#2563EB")
        score_axis.set_ylim(0, 10.5)
        score_axis.set_title("Điểm theo thời gian")
        score_axis.set_xlabel("Bài làm")
        score_axis.set_ylabel("Điểm / 10")
        self.score_chart.draw_idle()
        topic_axis = self.topic_chart.axes()
        raw_buckets = self._stats.get("by_topic")
        buckets = raw_buckets if isinstance(raw_buckets, list) else []
        grouped: dict[str, list[float]] = {}
        for bucket in buckets:
            if not isinstance(bucket, dict):
                continue
            topic = str(bucket.get("topic", "Khác"))
            grouped.setdefault(topic, []).append(_safe_float(bucket.get("accuracy_percent")))
        labels = list(grouped) or ["Chưa có dữ liệu"]
        values = [sum(grouped[label]) / len(grouped[label]) for label in grouped] or [0.0]
        topic_axis.bar(labels, values, color="#16A34A")
        topic_axis.set_ylim(0, 100)
        topic_axis.set_title("Tỷ lệ đúng theo chủ đề")
        topic_axis.set_ylabel("% đúng")
        topic_axis.tick_params(axis="x", rotation=20)
        self.topic_chart.draw_idle()

    def _on_success(self, request_id: str, response: object) -> None:
        action = self._pending.pop(request_id, None)
        if action is None:
            return
        try:
            data = _wire_data(response)
            if action == "stats":
                self._stats = data
            else:
                raw_history = data.get("attempts")
                if not isinstance(raw_history, list) or not all(isinstance(item, dict) for item in raw_history):
                    raise ValueError("Server trả về lịch sử không hợp lệ.")
                self._history = raw_history
            self._render()
            if not self._pending:
                self.notice.setText(f"Đã tải {len(self._history)} bài làm.")
        except ValueError as error:
            self.notice.setText(str(error))

    def _on_failure(self, request_id: str, message: str) -> None:
        if self._pending.pop(request_id, None) is not None:
            self.notice.setText(f"Không thể tải dữ liệu: {message}")


class LiveProfilePage(QWidget):
    profile_updated = Signal(object)

    def __init__(self, service: PhaseOneApiService, user: LiveUser) -> None:
        super().__init__()
        self.service = service
        self.user = user
        self._pending: dict[str, str] = {}
        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)
        title = QLabel("Hồ sơ")
        title.setObjectName("pageTitle")
        root.addWidget(title)
        card = QFrame()
        card.setObjectName("sectionCard")
        form = QFormLayout(card)
        self.username = QLabel(user.username)
        self.role = QLabel(user.role)
        self.display_name = QLineEdit(user.username)
        self.current_password = QLineEdit()
        self.current_password.setEchoMode(QLineEdit.Password)
        self.current_password.setPlaceholderText("Chỉ cần khi đổi mật khẩu")
        self.new_password = QLineEdit()
        self.new_password.setEchoMode(QLineEdit.Password)
        self.new_password.setPlaceholderText("Ít nhất 8 ký tự")
        form.addRow("Username", self.username)
        form.addRow("Vai trò", self.role)
        form.addRow("Tên hiển thị", self.display_name)
        form.addRow("Mật khẩu hiện tại", self.current_password)
        form.addRow("Mật khẩu mới", self.new_password)
        root.addWidget(card)
        self.notice = QLabel()
        self.notice.setObjectName("subtle")
        root.addWidget(self.notice)
        actions = QHBoxLayout()
        refresh = SecondaryButton("Tải lại")
        refresh.clicked.connect(self.refresh)
        save = PrimaryButton("Lưu thay đổi")
        save.clicked.connect(self._save)
        actions.addWidget(refresh)
        actions.addWidget(save)
        actions.addStretch()
        root.addLayout(actions)
        root.addStretch()
        self.service.request_succeeded.connect(self._on_success)
        self.service.request_failed.connect(self._on_failure)

    def refresh(self) -> None:
        self._pending[self.service.get_my_profile()] = "profile"
        self.notice.setText("Đang tải hồ sơ…")

    def _save(self) -> None:
        display_name = self.display_name.text().strip()
        current_password = self.current_password.text()
        new_password = self.new_password.text()
        if not display_name:
            self.notice.setText("Tên hiển thị không được để trống.")
            return
        if bool(current_password) != bool(new_password):
            self.notice.setText("Nhập cả mật khẩu hiện tại và mật khẩu mới để đổi mật khẩu.")
            return
        request_id = self.service.update_my_profile(
            display_name=display_name,
            current_password=current_password or None,
            new_password=new_password or None,
        )
        self._pending[request_id] = "update"
        self.notice.setText("Đang lưu hồ sơ…")

    def _on_success(self, request_id: str, response: object) -> None:
        action = self._pending.pop(request_id, None)
        if action is None:
            return
        try:
            data = _wire_data(response)
            raw_user = data.get("user")
            if not isinstance(raw_user, dict):
                raise ValueError("Server trả về hồ sơ không hợp lệ.")
            display_name = raw_user.get("display_name")
            if isinstance(display_name, str):
                self.display_name.setText(display_name)
            if action == "update":
                self.current_password.clear()
                self.new_password.clear()
                show_toast(self, "Đã cập nhật hồ sơ.")
                self.profile_updated.emit(raw_user)
            self.notice.setText("Hồ sơ đã được đồng bộ với server.")
        except ValueError as error:
            self.notice.setText(str(error))

    def _on_failure(self, request_id: str, message: str) -> None:
        if self._pending.pop(request_id, None) is not None:
            self.notice.setText(f"Không thể cập nhật hồ sơ: {message}")


class LiveMainWindow(QMainWindow):
    """One actual TCP workspace for all completed project phases."""

    def __init__(self, service: PhaseOneApiService) -> None:
        super().__init__()
        self.service = service
        self.user: LiveUser | None = None
        self._main_pending: dict[str, str] = {}
        self.setWindowTitle(APP_TITLE)
        self.setMinimumSize(WINDOW_MIN_WIDTH, WINDOW_MIN_HEIGHT)
        self.resize(1240, 820)
        self.root = QStackedWidget()
        self.root.setObjectName("root")
        self.setCentralWidget(self.root)
        self.auth = LiveAuthPage(service)
        self.auth.authenticated.connect(self._on_authenticated)
        self.root.addWidget(self.auth)
        self.service.request_succeeded.connect(self._on_main_success)
        self.service.request_failed.connect(self._on_main_failure)

    def _on_authenticated(self, user: LiveUser) -> None:
        self.user = user
        if self.root.count() > 1:
            old = self.root.widget(1)
            self.root.removeWidget(old)
            old.deleteLater()
        workspace = QWidget()
        workspace.setObjectName("workspace")
        layout = QHBoxLayout(workspace)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self._sidebar(user))
        main = QWidget()
        main_layout = QVBoxLayout(main)
        main_layout.setContentsMargins(24, 20, 24, 20)
        main_layout.setSpacing(14)
        main_layout.addWidget(self._topbar(user))
        self.pages = QStackedWidget()
        self.dashboard = LiveDashboardPage(self.service, user)
        self.dashboard.open_questions.connect(lambda: self.show_page("questions"))
        self.dashboard.logged_out.connect(self._on_logged_out)
        self.rooms = LiveRoomsPage(self.service, user)
        self.practice = LivePracticePage(self.service)
        self.exam = LiveExamPage(self.service)
        self.result = LiveResultPage()
        self.history = LiveHistoryPage(self.service)
        self.profile = LiveProfilePage(self.service, user)
        self.page_map: dict[str, QWidget] = {
            "dashboard": self.dashboard,
            "rooms": self.rooms,
            "practice": self.practice,
            "exam": self.exam,
            "result": self.result,
            "history": self.history,
            "profile": self.profile,
        }
        self.question_bank: QuestionBankPage | None = None
        if user.role == "ADMIN":
            self.question_bank = QuestionBankPage(self.service)
            self.page_map["questions"] = self.question_bank
        for page in self.page_map.values():
            self.pages.addWidget(page)
        main_layout.addWidget(self.pages, 1)
        layout.addWidget(main, 1)
        self.root.addWidget(workspace)
        self.root.setCurrentWidget(workspace)
        self.rooms.exam_requested.connect(self._request_exam)
        self.rooms.results_requested.connect(self._request_results)
        self.rooms.leaderboard_requested.connect(self._request_leaderboard)
        self.rooms.lobby_requested.connect(self._request_lobby)
        self.practice.exam_ready.connect(self._open_practice_exam)
        self.exam.submitted.connect(self._show_submission)
        self.exam.back_requested.connect(
            lambda: self.show_page("practice" if self.exam.mode == "practice" else "rooms")
        )
        self.result.rooms_requested.connect(lambda: self.show_page("rooms"))
        self.profile.profile_updated.connect(self._on_profile_updated)
        self.show_page("dashboard")

    def _sidebar(self, user: LiveUser) -> QFrame:
        sidebar = QFrame()
        sidebar.setObjectName("sidebar")
        sidebar.setFixedWidth(235)
        layout = QVBoxLayout(sidebar)
        layout.setContentsMargins(16, 20, 16, 16)
        brand = QLabel("◈  KuizuHub")
        brand.setObjectName("brand")
        layout.addWidget(brand)
        layout.addSpacing(24)
        self.identity = QLabel(f"@{user.username}\n{user.role}")
        self.identity.setObjectName("sideUser")
        layout.addWidget(self.identity)
        layout.addSpacing(16)
        self.nav_buttons: dict[str, QPushButton] = {}
        nav_items = [
            ("dashboard", "⌂  Tổng quan"),
            ("rooms", "▣  Phòng thi"),
            ("practice", "✦  Luyện tập"),
            ("history", "◔  Lịch sử & thống kê"),
        ]
        if user.role == "ADMIN":
            nav_items.append(("questions", "☷  Ngân hàng câu hỏi"))
        nav_items.append(("profile", "⚙  Hồ sơ"))
        for key, text in nav_items:
            button = QPushButton(text)
            button.setObjectName("nav")
            button.setCheckable(True)
            button.clicked.connect(lambda _checked=False, target=key: self.show_page(target))
            layout.addWidget(button)
            self.nav_buttons[key] = button
        layout.addStretch()
        note = QLabel("Phase 2–3\nTCP thật · không mock")
        note.setObjectName("caption")
        note.setWordWrap(True)
        layout.addWidget(note)
        return sidebar

    def _topbar(self, user: LiveUser) -> QFrame:
        topbar = QFrame()
        topbar.setObjectName("topbar")
        layout = QHBoxLayout(topbar)
        layout.setContentsMargins(14, 8, 14, 8)
        self.page_title = QLabel("Tổng quan")
        self.page_title.setObjectName("sectionTitle")
        layout.addWidget(self.page_title)
        layout.addStretch()
        layout.addWidget(UserAvatar(user.username, 34))
        identity = QLabel(f"@{user.username}\n{user.role}")
        identity.setObjectName("caption")
        layout.addWidget(identity)
        return topbar

    def show_page(self, key: str) -> None:
        page = self.page_map.get(key)
        if page is None:
            return
        self.pages.setCurrentWidget(page)
        titles = {
            "dashboard": "Tổng quan", "rooms": "Phòng thi", "practice": "Luyện tập",
            "exam": "Làm bài", "result": "Kết quả", "history": "Lịch sử & thống kê",
            "questions": "Ngân hàng câu hỏi", "profile": "Hồ sơ",
        }
        self.page_title.setText(titles.get(key, "KuizuHub"))
        for nav_key, button in self.nav_buttons.items():
            button.setChecked(nav_key == key)
        if key == "rooms":
            self.rooms.refresh()
        elif key == "history":
            self.history.refresh()
        elif key == "profile":
            self.profile.refresh()
        elif key == "questions" and self.question_bank is not None:
            self.question_bank.refresh()

    def _request_exam(self, room_id: int) -> None:
        self._main_pending[self.service.get_exam(room_id)] = "exam"

    def _request_results(self, room_id: int) -> None:
        self._main_pending[self.service.get_room_results(room_id)] = "results"

    def _request_leaderboard(self, room_id: int) -> None:
        self._main_pending[self.service.get_leaderboard(room_id)] = "leaderboard"

    def _request_lobby(self, room_id: int) -> None:
        self._main_pending[self.service.get_room_lobby(room_id)] = "lobby"

    def _open_practice_exam(self, data: object) -> None:
        if not isinstance(data, dict):
            return
        try:
            self.exam.load_exam(data, practice=True)
        except ValueError as error:
            QMessageBox.warning(self, "Không thể mở đề", str(error))
            return
        self.show_page("exam")

    def _show_submission(self, data: object, practice: bool, _room_id: int) -> None:
        if isinstance(data, dict) and self.pages.currentWidget() is self.exam:
            self.result.show_submission(data, practice=practice)
            self.show_page("result")

    def _on_main_success(self, request_id: str, response: object) -> None:
        action = self._main_pending.pop(request_id, None)
        if action is None:
            return
        try:
            data = _wire_data(response)
            if action == "exam":
                self.exam.load_exam(data, practice=False)
                self.show_page("exam")
            elif action == "results":
                self.result.show_room_results(data)
                self.show_page("result")
            elif action == "leaderboard":
                self.result.show_leaderboard(data)
                self.show_page("result")
            elif action == "lobby":
                LiveLobbyDialog(self.service, data, self).exec()
        except ValueError as error:
            QMessageBox.warning(self, "Dữ liệu không hợp lệ", str(error))

    def _on_main_failure(self, request_id: str, message: str) -> None:
        action = self._main_pending.pop(request_id, None)
        if action is not None:
            QMessageBox.warning(self, "Yêu cầu thất bại", message)

    def _on_profile_updated(self, raw_user: object) -> None:
        if not isinstance(raw_user, dict) or self.user is None:
            return
        display_name = raw_user.get("display_name")
        if isinstance(display_name, str) and display_name:
            self.identity.setText(f"@{display_name}\n{self.user.role}")

    def _on_logged_out(self) -> None:
        self.exam.stop()
        self._main_pending.clear()
        self.user = None
        self.root.setCurrentWidget(self.auth)
        self.auth.login_password.clear()

    def closeEvent(self, event: object) -> None:  # type: ignore[override]
        self.service.close()
        super().closeEvent(event)  # type: ignore[arg-type]
