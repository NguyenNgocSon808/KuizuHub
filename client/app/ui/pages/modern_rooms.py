"""Room discovery, creation, waiting-room and practice pages."""

from __future__ import annotations

from PySide6.QtCore import Signal, Qt
from PySide6.QtWidgets import (QComboBox, QFormLayout, QFrame, QGridLayout, QHBoxLayout, QLabel,
                               QLineEdit, QMessageBox, QPushButton, QScrollArea, QSpinBox,
                               QTableWidget, QTableWidgetItem, QTextEdit, QVBoxLayout, QWidget)

from ...config import DIFFICULTIES, TOPICS
from ...models import Room, User
from ...services import MockApiService, ServiceError
from ..widgets import (DangerButton, EmptyStateWidget, FilterChip, PageHeader, PrimaryButton,
                       SearchInput, SecondaryButton, SectionCard, StatusBadge, UserAvatar,
                       show_toast)


def _show_error(parent: QWidget, error: Exception) -> None:
    QMessageBox.warning(parent, "Không thể thực hiện", str(error))


class _TagBadge(QLabel):
    def __init__(self, text: str, kind: str = "topic") -> None:
        super().__init__(text)
        palette = {"topic": ("#EFF6FF", "#1D4ED8"), "easy": ("#DCFCE7", "#15803D"),
                   "medium": ("#FEF3C7", "#B45309"), "hard": ("#FEE2E2", "#B91C1C"),
                   "mix": ("#F1F5F9", "#475569")}
        background, color = palette.get(kind, palette["topic"])
        self.setStyleSheet(f"background:{background};color:{color};border-radius:9px;padding:4px 8px;font-size:12px;font-weight:600;")


class RoomCard(QFrame):
    action_requested = Signal(int)

    def __init__(self, room: Room, user: User) -> None:
        super().__init__()
        self.room, self.user = room, user
        self.setObjectName("roomCard")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 15, 16, 15)
        layout.setSpacing(10)
        top = QHBoxLayout()
        copy = QVBoxLayout()
        heading = QLabel(room.name)
        heading.setStyleSheet("font-size:16px;font-weight:700;")
        copy.addWidget(heading)
        owner = QLabel(f"Chủ phòng · {room.owner_name}")
        owner.setObjectName("caption")
        copy.addWidget(owner)
        top.addLayout(copy, 1)
        top.addWidget(StatusBadge(room.status))
        layout.addLayout(top)
        tags = QHBoxLayout()
        tags.addWidget(_TagBadge(room.topic))
        difficulty = {"Dễ": "easy", "Trung bình": "medium", "Khó": "hard"}.get(room.difficulty, "mix")
        tags.addWidget(_TagBadge(room.difficulty, difficulty))
        tags.addStretch()
        layout.addLayout(tags)
        description = QLabel(room.description or "Chưa có mô tả cho phòng thi này.")
        description.setWordWrap(True)
        description.setObjectName("subtle")
        description.setFixedHeight(40)
        layout.addWidget(description)
        metadata = QLabel(f"▤  {room.question_count} câu     ◷  {room.duration_minutes} phút     ♙  {len(room.participant_ids)}/{room.max_participants}")
        metadata.setStyleSheet("color:#475569;font-size:12px;")
        layout.addWidget(metadata)
        action_row = QHBoxLayout()
        action_row.addStretch()
        if user.role == "HOST":
            button = SecondaryButton("Quản lý phòng")
        elif room.status == "WAITING":
            button = PrimaryButton("Vào phòng" if user.id in room.participant_ids else "Tham gia phòng")
        elif room.status == "RUNNING" and user.id in room.participant_ids:
            button = PrimaryButton("Tiếp tục làm bài")
        elif room.status == "RUNNING":
            button = SecondaryButton("Không thể tham gia")
            button.setEnabled(False)
        else:
            button = SecondaryButton("Xem kết quả")
        button.clicked.connect(lambda: self.action_requested.emit(room.id))
        action_row.addWidget(button)
        layout.addLayout(action_row)


class RoomsPage(QWidget):
    open_waiting = Signal(int)
    open_exam = Signal(int)
    create_requested = Signal()

    def __init__(self, service: MockApiService, user: User) -> None:
        super().__init__()
        self.service, self.user = service, user
        self.status_value, self.topic_value = "Tất cả", "Tất cả"
        root = QVBoxLayout(self)
        root.setContentsMargins(4, 4, 4, 4)
        root.setSpacing(14)
        root.addWidget(self._header())
        root.addLayout(self._toolbar())
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.content = QWidget()
        self.grid = QGridLayout(self.content)
        self.grid.setContentsMargins(0, 2, 0, 12)
        self.grid.setSpacing(14)
        self.scroll.setWidget(self.content)
        root.addWidget(self.scroll, 1)
        self.refresh()

    def _header(self) -> QWidget:
        row = QWidget()
        layout = QHBoxLayout(row)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(PageHeader("Phòng thi", "Khám phá, tham gia và quản lý các phòng thi trong lớp."), 1)
        if self.user.role == "HOST":
            button = PrimaryButton("＋  Tạo phòng thi")
            button.clicked.connect(self.create_requested)
            layout.addWidget(button, alignment=Qt.AlignTop)
        return row

    def _toolbar(self) -> QHBoxLayout:
        toolbar = QHBoxLayout()
        toolbar.setSpacing(8)
        self.search = SearchInput("Tìm theo tên phòng hoặc chủ đề")
        self.search.textChanged.connect(self.refresh)
        toolbar.addWidget(self.search, 3)
        self.status_chips: dict[str, FilterChip] = {}
        for status in ["Tất cả", "Chờ", "Đang diễn ra", "Đã kết thúc"]:
            chip = FilterChip(status, checked=status == "Tất cả")
            chip.clicked.connect(lambda _=False, value=status: self._select_status(value))
            self.status_chips[status] = chip
            toolbar.addWidget(chip)
        self.topic_filter = QComboBox()
        self.topic_filter.addItems(TOPICS)
        self.topic_filter.currentTextChanged.connect(self._select_topic)
        self.topic_filter.setFixedWidth(150)
        toolbar.addWidget(self.topic_filter)
        return toolbar

    def _select_status(self, status: str) -> None:
        self.status_value = status
        for value, chip in self.status_chips.items():
            chip.setChecked(value == status)
        self.refresh()

    def _select_topic(self, topic: str) -> None:
        self.topic_value = topic
        self.refresh()

    def refresh(self) -> None:
        while self.grid.count():
            item = self.grid.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        rooms = self.service.get_rooms(self.search.text(), self.status_value)
        if self.topic_value != "Tất cả":
            rooms = [room for room in rooms if room.topic == self.topic_value]
        if not rooms:
            action = PrimaryButton("Tạo phòng thi") if self.user.role == "HOST" else None
            if action:
                action.clicked.connect(self.create_requested)
            self.grid.addWidget(EmptyStateWidget("Không tìm thấy phòng phù hợp", "Hãy thử từ khóa hoặc bộ lọc khác.", action), 0, 0, 1, 2)
            return
        for index, room in enumerate(rooms):
            card = RoomCard(room, self.user)
            card.action_requested.connect(self._room_action)
            self.grid.addWidget(card, index // 2, index % 2)
        self.grid.setColumnStretch(0, 1)
        self.grid.setColumnStretch(1, 1)

    def _room_action(self, room_id: int) -> None:
        room = self.service._room(room_id)
        if self.user.role == "HOST" or room.status == "ENDED":
            self.open_waiting.emit(room_id)
        elif room.status == "WAITING":
            self._join(room)
        elif room.status == "RUNNING" and self.user.id in room.participant_ids:
            self.open_exam.emit(room_id)

    def _join(self, room: Room) -> None:
        try:
            self.service.join_room(room.id, self.user.id)
            show_toast(self, "Đã tham gia phòng. Hãy sẵn sàng làm bài!")
            self.open_waiting.emit(room.id)
        except ServiceError as error:
            _show_error(self, error)


class CreateRoomPage(QWidget):
    created = Signal()

    def __init__(self, service: MockApiService, user: User) -> None:
        super().__init__()
        self.service, self.user = service, user
        root = QVBoxLayout(self)
        root.setContentsMargins(4, 4, 4, 4)
        root.addWidget(PageHeader("Tạo phòng thi", "Thiết lập nội dung và xem trước trải nghiệm dành cho thí sinh."))
        stepper = QLabel("① Thông tin phòng     ② Cấu hình đề thi     ③ Cài đặt tham gia")
        stepper.setStyleSheet("background:#EFF6FF;color:#1D4ED8;border-radius:8px;padding:9px 12px;font-weight:600;")
        root.addWidget(stepper)
        columns = QHBoxLayout()
        columns.setSpacing(16)
        columns.addWidget(self._form_card(), 6)
        self.preview = SectionCard("Xem trước phòng thi", "Thông tin này sẽ hiển thị trên danh sách phòng.")
        columns.addWidget(self.preview, 4)
        root.addLayout(columns, 1)
        self._refresh_preview()

    def _form_card(self) -> SectionCard:
        card = SectionCard()
        card.layout.addWidget(QLabel("1. Thông tin phòng", objectName="sectionTitle"))
        form = QFormLayout()
        form.setSpacing(12)
        self.name = QLineEdit()
        self.name.setPlaceholderText("Ví dụ: Ôn tập TCP tuần 8")
        self.description = QTextEdit()
        self.description.setFixedHeight(72)
        self.description.setPlaceholderText("Mô tả ngắn cho thí sinh")
        form.addRow("Tên phòng *", self.name)
        form.addRow("Mô tả", self.description)
        card.layout.addLayout(form)
        card.layout.addSpacing(8)
        card.layout.addWidget(QLabel("2. Cấu hình đề thi", objectName="sectionTitle"))
        exam_form = QFormLayout()
        exam_form.setSpacing(12)
        self.topic = QComboBox(); self.topic.addItems(TOPICS[1:])
        self.difficulty = QComboBox(); self.difficulty.addItems(DIFFICULTIES[1:])
        self.count = QSpinBox(); self.count.setRange(1, 20); self.count.setValue(5); self.count.setSuffix(" câu")
        self.duration = QSpinBox(); self.duration.setRange(1, 180); self.duration.setValue(15); self.duration.setSuffix(" phút")
        exam_form.addRow("Chủ đề", self.topic)
        exam_form.addRow("Độ khó", self.difficulty)
        exam_form.addRow("Số lượng câu *", self.count)
        exam_form.addRow("Thời gian *", self.duration)
        card.layout.addLayout(exam_form)
        card.layout.addSpacing(8)
        card.layout.addWidget(QLabel("3. Cài đặt tham gia", objectName="sectionTitle"))
        settings = QFormLayout()
        self.capacity = QSpinBox(); self.capacity.setRange(1, 200); self.capacity.setValue(30); self.capacity.setSuffix(" người")
        settings.addRow("Số thí sinh tối đa", self.capacity)
        card.layout.addLayout(settings)
        actions = QHBoxLayout()
        actions.addStretch()
        clear = SecondaryButton("Hủy")
        clear.clicked.connect(self._clear)
        create = PrimaryButton("Tạo phòng thi")
        create.clicked.connect(self._create)
        actions.addWidget(clear)
        actions.addWidget(create)
        card.layout.addLayout(actions)
        for control in [self.name, self.description, self.topic, self.difficulty, self.count, self.duration, self.capacity]:
            signal = getattr(control, "textChanged", None) or getattr(control, "currentTextChanged", None) or getattr(control, "valueChanged", None)
            signal.connect(self._refresh_preview)
        return card

    def _refresh_preview(self, *_: object) -> None:
        while self.preview.layout.count():
            item = self.preview.layout.takeAt(0)
            if item.widget(): item.widget().deleteLater()
        name = self.name.text().strip() or "Tên phòng thi của bạn"
        preview_name = QLabel(name)
        preview_name.setStyleSheet("font-size:18px;font-weight:700;")
        self.preview.layout.addWidget(preview_name)
        self.preview.layout.addWidget(StatusBadge("WAITING"))
        self.preview.layout.addWidget(QLabel(self.description.toPlainText() or "Phòng thi sẽ sẵn sàng ngay sau khi bạn tạo.", objectName="subtle"))
        for text in [f"▤  {self.count.value()} câu hỏi", f"◷  {self.duration.value()} phút", f"⌁  {self.topic.currentText()}", f"◉  {self.difficulty.currentText()}", f"♙  Tối đa {self.capacity.value()} thí sinh"]:
            label = QLabel(text)
            label.setStyleSheet("background:#F8FAFC;border-radius:7px;padding:9px;color:#475569;")
            self.preview.layout.addWidget(label)
        self.preview.layout.addStretch()

    def _clear(self) -> None:
        self.name.clear(); self.description.clear(); self.topic.setCurrentIndex(0); self.difficulty.setCurrentIndex(0)
        self.count.setValue(5); self.duration.setValue(15); self.capacity.setValue(30)

    def _create(self) -> None:
        try:
            self.service.create_room(self.user.id, {"name": self.name.text(), "description": self.description.toPlainText(), "topic": self.topic.currentText(), "difficulty": self.difficulty.currentText(), "question_count": self.count.value(), "duration_minutes": self.duration.value(), "max_participants": self.capacity.value()})
            self._clear()
            self.created.emit()
        except ServiceError as error:
            _show_error(self, error)


class WaitingRoomPage(QWidget):
    open_exam = Signal(int)
    refresh_rooms = Signal()

    def __init__(self, service: MockApiService, user: User) -> None:
        super().__init__()
        self.service, self.user, self.room_id = service, user, None
        self.root = QVBoxLayout(self)
        self.root.setContentsMargins(4, 4, 4, 4)
        self.root.setSpacing(14)

    def set_room(self, room_id: int) -> None:
        self.room_id = room_id
        self.refresh()

    def refresh(self) -> None:
        while self.root.count():
            item = self.root.takeAt(0)
            if item.widget(): item.widget().deleteLater()
        if self.room_id is None:
            return
        try:
            room = self.service._room(self.room_id)
        except ServiceError as error:
            _show_error(self, error)
            return
        self.root.addWidget(self._hero(room))
        content = QHBoxLayout()
        content.setSpacing(16)
        content.addWidget(self._members(room), 6)
        content.addWidget(self._rules(room), 4)
        self.root.addLayout(content, 1)
        if self.user.role == "HOST" and room.owner_id == self.user.id and room.status == "ENDED":
            self.root.addWidget(self._results(room))

    def _hero(self, room: Room) -> QFrame:
        card = QFrame()
        card.setObjectName("heroCard")
        layout = QHBoxLayout(card)
        layout.setContentsMargins(20, 17, 20, 17)
        copy = QVBoxLayout()
        title_row = QHBoxLayout()
        title = QLabel(room.name)
        title.setObjectName("pageTitle")
        title_row.addWidget(title)
        title_row.addWidget(StatusBadge(room.status))
        title_row.addStretch()
        copy.addLayout(title_row)
        copy.addWidget(QLabel(f"{room.topic}  ·  {room.difficulty}  ·  {room.question_count} câu hỏi  ·  {room.duration_minutes} phút", objectName="subtle"))
        layout.addLayout(copy, 1)
        if room.status == "WAITING":
            note = QLabel("Bài thi sẽ bắt đầu\nkhi chủ phòng bấm Bắt đầu")
            note.setAlignment(Qt.AlignCenter)
            note.setStyleSheet("background:#FEF3C7;color:#92400E;border-radius:9px;padding:10px;font-weight:600;")
            layout.addWidget(note)
        return card

    def _members(self, room: Room) -> SectionCard:
        card = SectionCard("Thành viên trong phòng", "Mọi người sẽ nhận đề khi chủ phòng bắt đầu bài thi.")
        avatars = QHBoxLayout()
        avatars.addWidget(UserAvatar(room.owner_name, 38))
        for participant in self.service.room_participants(room.id)[:6]:
            avatars.addWidget(UserAvatar(participant.full_name, 38))
        avatars.addStretch()
        card.layout.addLayout(avatars)
        host_row = QFrame()
        host_row.setStyleSheet("background:#EFF6FF;border-radius:8px;")
        host_layout = QHBoxLayout(host_row)
        host_layout.setContentsMargins(10, 8, 10, 8)
        host_layout.addWidget(UserAvatar(room.owner_name, 28))
        host_layout.addWidget(QLabel(f"{room.owner_name}\nChủ phòng", objectName="sideUser"), 1)
        host_layout.addWidget(_TagBadge("HOST"))
        card.layout.addWidget(host_row)
        for participant in self.service.room_participants(room.id):
            row = QHBoxLayout()
            row.addWidget(UserAvatar(participant.full_name, 28))
            row.addWidget(QLabel(f"{participant.full_name}\nSẵn sàng làm bài", objectName="sideUser"), 1)
            row.addWidget(_TagBadge("Thí sinh"))
            card.layout.addLayout(row)
        return card

    def _rules(self, room: Room) -> SectionCard:
        card = SectionCard("Sẵn sàng trước khi thi", "Đọc nhanh các quy tắc để có trải nghiệm làm bài tốt nhất.")
        rules = QLabel("• Mỗi câu chỉ lưu đáp án được chọn sau cùng.\n• Bạn có thể chuyển câu và quay lại bất cứ lúc nào.\n• Nộp bài trước giờ hoặc hệ thống sẽ nộp tự động.\n• Đáp án đúng chỉ hiện sau khi hoàn thành.")
        rules.setWordWrap(True)
        rules.setStyleSheet("color:#475569;line-height:1.55;")
        card.layout.addWidget(rules)
        card.layout.addStretch()
        if self.user.role == "HOST" and room.owner_id == self.user.id:
            if room.status == "WAITING":
                start = PrimaryButton("Bắt đầu thi")
                start.clicked.connect(self._start)
                cancel = DangerButton("Hủy phòng", outline=True)
                cancel.clicked.connect(self._cancel)
                card.layout.addWidget(start)
                card.layout.addWidget(cancel)
            elif room.status == "RUNNING":
                end = DangerButton("Kết thúc phòng")
                end.clicked.connect(self._end)
                card.layout.addWidget(end)
        elif self.user.role == "STUDENT" and room.status == "WAITING":
            ready = PrimaryButton("✓  Sẵn sàng làm bài")
            ready.clicked.connect(lambda: show_toast(self, "Bạn đã sẵn sàng. Hãy chờ chủ phòng bắt đầu.", "info"))
            leave = SecondaryButton("Rời phòng")
            leave.clicked.connect(self._leave)
            card.layout.addWidget(ready)
            card.layout.addWidget(leave)
        elif self.user.role == "STUDENT" and room.status == "RUNNING" and self.user.id in room.participant_ids:
            start = PrimaryButton("Vào làm bài")
            start.clicked.connect(lambda: self.open_exam.emit(room.id))
            card.layout.addWidget(start)
        return card

    def _results(self, room: Room) -> SectionCard:
        card = SectionCard("Kết quả thí sinh", "Tổng hợp các bài đã được nộp trong phòng này.")
        table = QTableWidget(0, 5)
        table.setHorizontalHeaderLabels(["Thí sinh", "Điểm", "Câu đúng", "Thời gian nộp", "Trạng thái"])
        table.setEditTriggers(QTableWidget.NoEditTriggers)
        table.verticalHeader().setVisible(False)
        table.horizontalHeader().setStretchLastSection(True)
        attempts = self.service.room_results(room.id)
        table.setRowCount(len(attempts))
        for index, attempt in enumerate(attempts):
            user = self.service._user(attempt.user_id)
            values = [user.full_name, f"{attempt.score}/10", f"{attempt.correct_count}/{attempt.total}", attempt.created_at, "Hết giờ" if attempt.status == "AUTO_SUBMITTED" else "Đã nộp"]
            for column, value in enumerate(values):
                table.setItem(index, column, QTableWidgetItem(value))
        table.resizeColumnsToContents()
        card.layout.addWidget(table)
        return card

    def _start(self) -> None:
        try:
            self.service.start_room(self.room_id, self.user.id)
            self.refresh()
            self.refresh_rooms.emit()
            show_toast(self, "Phòng đã bắt đầu. Thí sinh có thể vào làm bài.")
        except ServiceError as error:
            _show_error(self, error)

    def _cancel(self) -> None:
        if QMessageBox.question(self, "Hủy phòng", "Hủy phòng này? Trạng thái phòng sẽ chuyển sang đã kết thúc.", QMessageBox.Yes | QMessageBox.No) == QMessageBox.Yes:
            self._end()

    def _end(self) -> None:
        try:
            self.service.end_room(self.room_id, self.user.id)
            self.refresh()
            self.refresh_rooms.emit()
            show_toast(self, "Phòng đã kết thúc.", "warning")
        except ServiceError as error:
            _show_error(self, error)

    def _leave(self) -> None:
        try:
            self.service.leave_room(self.room_id, self.user.id)
            self.refresh_rooms.emit()
            show_toast(self, "Bạn đã rời khỏi phòng chờ.", "info")
        except ServiceError as error:
            _show_error(self, error)


class PracticePage(QWidget):
    start_practice = Signal(object, object, int, str)

    def __init__(self, service: MockApiService, user: User) -> None:
        super().__init__()
        self.service, self.user = service, user
        root = QVBoxLayout(self)
        root.setContentsMargins(4, 4, 4, 4)
        root.addWidget(PageHeader("Luyện tập cá nhân", "Tạo bài luyện tập phù hợp với mục tiêu của bạn hôm nay."))
        columns = QHBoxLayout()
        columns.setSpacing(16)
        form_card = SectionCard("Thiết lập bài luyện", "Bạn có thể thay đổi cấu hình cho mỗi lần luyện tập.")
        form = QFormLayout()
        form.setSpacing(12)
        self.topic = QComboBox(); self.topic.addItems(TOPICS)
        self.difficulty = QComboBox(); self.difficulty.addItems(DIFFICULTIES)
        self.count = QComboBox(); self.count.addItems(["5", "10", "15", "20"])
        self.minutes = QComboBox(); self.minutes.addItems(["Không giới hạn", "10 phút", "20 phút", "30 phút"])
        for label, field in [("Chủ đề", self.topic), ("Độ khó", self.difficulty), ("Số lượng câu", self.count), ("Thời gian", self.minutes)]:
            form.addRow(label, field)
        form_card.layout.addLayout(form)
        start = PrimaryButton("✦  Bắt đầu luyện tập")
        start.clicked.connect(self._start)
        form_card.layout.addWidget(start)
        columns.addWidget(form_card, 6)
        side = SectionCard("Bạn sẽ nhận được gì?", "Chế độ luyện tập hiển thị phản hồi ngay sau khi chọn đáp án.")
        for text in ["✓ Biết đáp án đúng/sai ngay lập tức", "✓ Xem giải thích ngắn cho từng câu", "✓ Lưu kết quả vào lịch sử demo", "✓ Chủ động chọn thời gian hoặc không giới hạn"]:
            item = QLabel(text)
            item.setStyleSheet("background:#F8FAFC;border-radius:7px;padding:9px;color:#475569;")
            side.layout.addWidget(item)
        side.layout.addStretch()
        columns.addWidget(side, 4)
        root.addLayout(columns)
        root.addStretch()

    def _start(self) -> None:
        try:
            questions = self.service.get_exam_questions(self.topic.currentText(), self.difficulty.currentText(), int(self.count.currentText()))
            minutes = 0 if self.minutes.currentText() == "Không giới hạn" else int(self.minutes.currentText().split()[0])
            self.start_practice.emit(questions, {"topic": self.topic.currentText()}, minutes, "Luyện tập cá nhân")
        except ServiceError as error:
            _show_error(self, error)
