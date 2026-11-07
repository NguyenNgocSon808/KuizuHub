from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (QComboBox, QDialog, QFormLayout, QFrame, QHBoxLayout, QLabel,
                               QLineEdit, QMessageBox, QPushButton, QScrollArea, QSpinBox,
                               QTableWidget, QTableWidgetItem, QTextEdit, QVBoxLayout, QWidget)

from ...config import DIFFICULTIES, TOPICS
from ...models import Question, Room, User
from ...services import MockApiService, ServiceError
from ..widgets import PageHeader, StatusBadge


def _show_error(parent: QWidget, error: Exception) -> None:
    QMessageBox.warning(parent, "Không thể thực hiện", str(error))


class RoomsPage(QWidget):
    open_waiting = Signal(int)
    open_exam = Signal(int)

    def __init__(self, service: MockApiService, user: User) -> None:
        super().__init__()
        self.service, self.user = service, user
        root = QVBoxLayout(self); root.setContentsMargins(6, 6, 6, 6)
        root.addWidget(PageHeader("Phòng thi", "Tìm phòng phù hợp và tham gia ngay khi phòng đang chờ."))
        filters = QHBoxLayout()
        self.search = QLineEdit(); self.search.setPlaceholderText("Tìm theo tên phòng hoặc chủ đề…"); self.search.textChanged.connect(self.refresh)
        self.status = QComboBox(); self.status.addItems(["Tất cả", "Chờ", "Đang diễn ra", "Đã kết thúc"]); self.status.currentTextChanged.connect(self.refresh)
        filters.addWidget(self.search, 4); filters.addWidget(self.status, 1)
        root.addLayout(filters)
        self.scroll = QScrollArea(); self.scroll.setWidgetResizable(True); self.scroll.setFrameShape(QFrame.NoFrame)
        self.content = QWidget(); self.cards = QVBoxLayout(self.content); self.cards.setSpacing(12); self.cards.addStretch()
        self.scroll.setWidget(self.content); root.addWidget(self.scroll)
        self.refresh()

    def refresh(self) -> None:
        while self.cards.count() > 1:
            item = self.cards.takeAt(0)
            if item.widget(): item.widget().deleteLater()
        for room in self.service.get_rooms(self.search.text(), self.status.currentText()):
            self.cards.insertWidget(self.cards.count() - 1, self._room_card(room))

    def _room_card(self, room: Room) -> QFrame:
        frame = QFrame(); frame.setObjectName("roomCard")
        layout = QVBoxLayout(frame); layout.setContentsMargins(16, 14, 16, 14)
        top = QHBoxLayout(); heading = QLabel(room.name); heading.setStyleSheet("font-size:17px;font-weight:700;color:#102a43;")
        top.addWidget(heading); top.addStretch(); top.addWidget(StatusBadge(room.status)); layout.addLayout(top)
        description = QLabel(room.description or "Chưa có mô tả."); description.setObjectName("subtle"); description.setWordWrap(True); layout.addWidget(description)
        meta = QLabel(f"Chủ phòng: {room.owner_name}    •    {room.topic}    •    {room.difficulty}    •    {room.question_count} câu / {room.duration_minutes} phút    •    {len(room.participant_ids)}/{room.max_participants} thí sinh")
        meta.setStyleSheet("color:#475467;"); meta.setWordWrap(True); layout.addWidget(meta)
        actions = QHBoxLayout(); actions.addStretch()
        if self.user.role == "HOST":
            button = QPushButton("Quản lý phòng")
            button.setObjectName("secondary"); button.clicked.connect(lambda: self.open_waiting.emit(room.id)); actions.addWidget(button)
        elif room.status == "WAITING":
            button = QPushButton("Vào phòng" if self.user.id in room.participant_ids else "Tham gia")
            button.clicked.connect(lambda: self._join(room)); actions.addWidget(button)
        elif room.status == "RUNNING":
            if self.user.id in room.participant_ids:
                button = QPushButton("Tiếp tục làm bài"); button.clicked.connect(lambda: self.open_exam.emit(room.id)); actions.addWidget(button)
            else:
                disabled = QPushButton("Không thể tham gia"); disabled.setEnabled(False); actions.addWidget(disabled)
        else:
            button = QPushButton("Xem kết quả"); button.setObjectName("secondary"); button.clicked.connect(lambda: self.open_waiting.emit(room.id)); actions.addWidget(button)
        layout.addLayout(actions)
        return frame

    def _join(self, room: Room) -> None:
        try:
            self.service.join_room(room.id, self.user.id)
            self.open_waiting.emit(room.id)
        except ServiceError as error:
            _show_error(self, error)


class CreateRoomPage(QWidget):
    created = Signal()

    def __init__(self, service: MockApiService, user: User) -> None:
        super().__init__()
        self.service, self.user = service, user
        layout = QVBoxLayout(self); layout.setContentsMargins(6, 6, 6, 6)
        layout.addWidget(PageHeader("Tạo phòng thi", "Cấu hình đề thi. Phòng mới sẽ được tạo ở trạng thái chờ."))
        form_box = QFrame(); form_box.setObjectName("card"); form = QFormLayout(form_box); form.setSpacing(12)
        self.name = QLineEdit(); self.name.setPlaceholderText("Ví dụ: Ôn tập TCP tuần 8")
        self.description = QTextEdit(); self.description.setFixedHeight(80); self.description.setPlaceholderText("Mô tả ngắn cho thí sinh")
        self.topic = QComboBox(); self.topic.addItems(TOPICS[1:])
        self.difficulty = QComboBox(); self.difficulty.addItems(DIFFICULTIES[1:])
        self.count = QSpinBox(); self.count.setRange(1, 20); self.count.setValue(5)
        self.duration = QSpinBox(); self.duration.setRange(1, 180); self.duration.setValue(15); self.duration.setSuffix(" phút")
        self.capacity = QSpinBox(); self.capacity.setRange(1, 200); self.capacity.setValue(30)
        for label, field in [("Tên phòng *", self.name), ("Mô tả", self.description), ("Chủ đề", self.topic), ("Độ khó", self.difficulty), ("Số lượng câu *", self.count), ("Thời gian *", self.duration), ("Số người tối đa", self.capacity)]: form.addRow(label, field)
        create = QPushButton("Tạo phòng")
        create.clicked.connect(self._create); form.addRow("", create)
        layout.addWidget(form_box); layout.addStretch()

    def _create(self) -> None:
        try:
            self.service.create_room(self.user.id, {"name": self.name.text(), "description": self.description.toPlainText(), "topic": self.topic.currentText(), "difficulty": self.difficulty.currentText(), "question_count": self.count.value(), "duration_minutes": self.duration.value(), "max_participants": self.capacity.value()})
            QMessageBox.information(self, "Đã tạo phòng", "Phòng thi mới đã xuất hiện trong danh sách ở trạng thái Chờ.")
            self.name.clear(); self.description.clear(); self.created.emit()
        except ServiceError as error:
            _show_error(self, error)


class WaitingRoomPage(QWidget):
    open_exam = Signal(int)
    refresh_rooms = Signal()

    def __init__(self, service: MockApiService, user: User) -> None:
        super().__init__()
        self.service, self.user, self.room_id = service, user, None
        self.layout = QVBoxLayout(self); self.layout.setContentsMargins(6, 6, 6, 6)

    def set_room(self, room_id: int) -> None:
        self.room_id = room_id
        self.refresh()

    def refresh(self) -> None:
        while self.layout.count():
            item = self.layout.takeAt(0)
            if item.widget(): item.widget().deleteLater()
        if self.room_id is None: return
        try: room = self.service._room(self.room_id)
        except ServiceError as error: _show_error(self, error); return
        self.layout.addWidget(PageHeader(room.name, "Sảnh chờ" if room.status == "WAITING" else "Thông tin phòng thi"))
        info = QFrame(); info.setObjectName("card"); contents = QVBoxLayout(info)
        contents.addWidget(QLabel(f"{room.topic} • {room.difficulty} • {room.question_count} câu • {room.duration_minutes} phút"))
        state = QLabel("Đang chờ chủ phòng bắt đầu" if room.status == "WAITING" else "Phòng đã bắt đầu" if room.status == "RUNNING" else "Phòng đã kết thúc")
        state.setStyleSheet("color:#a15c00;font-weight:700;"); contents.addWidget(state)
        self.layout.addWidget(info)
        people = QFrame(); people.setObjectName("card"); people_layout = QVBoxLayout(people); heading = QLabel("Người đã tham gia"); heading.setStyleSheet("font-size:16px;font-weight:700;"); people_layout.addWidget(heading)
        owner = QLabel(f"{room.owner_name}  •  HOST"); owner.setStyleSheet("background:#e8f1fe;color:#1769aa;padding:8px;border-radius:6px;font-weight:600;"); people_layout.addWidget(owner)
        for participant in self.service.room_participants(room.id):
            people_layout.addWidget(QLabel(f"{participant.full_name}  •  Thí sinh"))
        self.layout.addWidget(people)
        if self.user.role == "HOST" and room.owner_id == self.user.id and room.status == "ENDED":
            result_box = QFrame(); result_box.setObjectName("card"); result_layout = QVBoxLayout(result_box)
            heading = QLabel("Kết quả thí sinh"); heading.setStyleSheet("font-size:16px;font-weight:700;"); result_layout.addWidget(heading)
            table = QTableWidget(0, 5); table.setHorizontalHeaderLabels(["Thí sinh", "Điểm", "Câu đúng", "Thời gian nộp", "Trạng thái"]); table.setEditTriggers(QTableWidget.NoEditTriggers); table.verticalHeader().setVisible(False); table.horizontalHeader().setStretchLastSection(True)
            attempts = self.service.room_results(room.id)
            table.setRowCount(len(attempts))
            for index, attempt in enumerate(attempts):
                student = self.service._user(attempt.user_id)
                values = [student.full_name, f"{attempt.score}/10", f"{attempt.correct_count}/{attempt.total}", attempt.created_at, "Hết giờ" if attempt.status == "AUTO_SUBMITTED" else "Đã nộp"]
                for column, value in enumerate(values): table.setItem(index, column, QTableWidgetItem(value))
            table.resizeColumnsToContents(); result_layout.addWidget(table)
            self.layout.addWidget(result_box)
        actions = QHBoxLayout(); actions.addStretch()
        if self.user.role == "HOST" and room.owner_id == self.user.id:
            if room.status == "WAITING":
                start = QPushButton("Bắt đầu thi"); start.clicked.connect(self._start); actions.addWidget(start)
                cancel = QPushButton("Hủy phòng"); cancel.setObjectName("danger"); cancel.clicked.connect(self._end); actions.addWidget(cancel)
            else:
                end = QPushButton("Kết thúc phòng"); end.setObjectName("danger"); end.clicked.connect(self._end); actions.addWidget(end)
        elif self.user.role == "STUDENT" and room.status == "WAITING":
            leave = QPushButton("Rời phòng"); leave.setObjectName("secondary"); leave.clicked.connect(self._leave); actions.addWidget(leave)
        elif self.user.role == "STUDENT" and room.status == "RUNNING" and self.user.id in room.participant_ids:
            take = QPushButton("Vào làm bài"); take.clicked.connect(lambda: self.open_exam.emit(room.id)); actions.addWidget(take)
        self.layout.addLayout(actions); self.layout.addStretch()

    def _start(self) -> None:
        try:
            self.service.start_room(self.room_id, self.user.id); self.refresh(); self.refresh_rooms.emit()
            QMessageBox.information(self, "Đã bắt đầu", "Phòng đang diễn ra. Thí sinh có thể vào làm bài.")
        except ServiceError as error: _show_error(self, error)

    def _end(self) -> None:
        try:
            self.service.end_room(self.room_id, self.user.id); self.refresh(); self.refresh_rooms.emit()
        except ServiceError as error: _show_error(self, error)

    def _leave(self) -> None:
        try:
            self.service.leave_room(self.room_id, self.user.id); self.refresh_rooms.emit(); QMessageBox.information(self, "Đã rời phòng", "Bạn đã rời khỏi phòng chờ.")
        except ServiceError as error: _show_error(self, error)


class PracticePage(QWidget):
    start_practice = Signal(object, object, int, str)

    def __init__(self, service: MockApiService, user: User) -> None:
        super().__init__()
        self.service, self.user = service, user
        layout = QVBoxLayout(self); layout.setContentsMargins(6, 6, 6, 6)
        layout.addWidget(PageHeader("Luyện tập cá nhân", "Chọn cấu hình để tạo một bài luyện tập từ ngân hàng câu hỏi."))
        box = QFrame(); box.setObjectName("card"); form = QFormLayout(box)
        self.topic = QComboBox(); self.topic.addItems(TOPICS)
        self.difficulty = QComboBox(); self.difficulty.addItems(DIFFICULTIES)
        self.count = QComboBox(); self.count.addItems(["5", "10", "15", "20"])
        self.minutes = QComboBox(); self.minutes.addItems(["Không giới hạn", "10", "20", "30"])
        for label, field in [("Chủ đề", self.topic), ("Độ khó", self.difficulty), ("Số lượng câu", self.count), ("Thời gian", self.minutes)]: form.addRow(label, field)
        go = QPushButton("Bắt đầu luyện tập"); go.clicked.connect(self._start); form.addRow("", go)
        layout.addWidget(box); layout.addStretch()

    def _start(self) -> None:
        try:
            questions = self.service.get_exam_questions(self.topic.currentText(), self.difficulty.currentText(), int(self.count.currentText()))
            minutes = 0 if self.minutes.currentText() == "Không giới hạn" else int(self.minutes.currentText())
            self.start_practice.emit(questions, {"topic": self.topic.currentText(), "minutes": minutes}, minutes, "Luyện tập cá nhân")
        except ServiceError as error: _show_error(self, error)
