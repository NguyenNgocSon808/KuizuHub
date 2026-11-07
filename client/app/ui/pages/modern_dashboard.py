"""Role-aware dashboard with a clear primary action and readable analytics."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton, QScrollArea, QVBoxLayout, QWidget

from ...models import User
from ...services import MockApiService
from ..widgets import (ChartCanvas, EmptyStateWidget, MetricCard, PageHeader, PrimaryButton,
                       ScoreBadge, SectionCard, StatusBadge)


class DashboardPage(QWidget):
    navigate = Signal(str)

    def __init__(self, service: MockApiService, user: User) -> None:
        super().__init__()
        self.service, self.user = service, user
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.body = QWidget()
        self.layout = QVBoxLayout(self.body)
        self.layout.setContentsMargins(4, 4, 4, 22)
        self.layout.setSpacing(16)
        scroll.setWidget(self.body)
        outer.addWidget(scroll)
        self.refresh()

    def refresh(self) -> None:
        while self.layout.count():
            item = self.layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self.layout.addWidget(self._welcome())
        self.layout.addLayout(self._metrics())
        body = QHBoxLayout()
        body.setSpacing(16)
        body.addWidget(self._featured_rooms(), 6)
        body.addWidget(self._right_column(), 4)
        self.layout.addLayout(body)
        self.layout.addStretch()

    def _welcome(self) -> QFrame:
        hero = QFrame()
        hero.setObjectName("heroCard")
        layout = QHBoxLayout(hero)
        layout.setContentsMargins(22, 18, 22, 18)
        hour_copy = "Chào buổi sáng" if self.user.role == "STUDENT" else "Chào mừng trở lại"
        copy = QVBoxLayout()
        title = QLabel(f"{hour_copy}, {self.user.full_name.split()[0]}!")
        title.setObjectName("pageTitle")
        copy.addWidget(title)
        description = QLabel("Sẵn sàng chinh phục bài thi tiếp theo?" if self.user.role == "STUDENT" else "Theo dõi phòng thi, thí sinh và ngân hàng câu hỏi ở một nơi.")
        description.setObjectName("subtle")
        copy.addWidget(description)
        layout.addLayout(copy)
        layout.addStretch()
        target = "practice" if self.user.role == "STUDENT" else "create_room"
        label = "✦  Bắt đầu luyện tập" if self.user.role == "STUDENT" else "＋  Tạo phòng thi"
        action = PrimaryButton(label)
        action.clicked.connect(lambda: self.navigate.emit(target))
        layout.addWidget(action)
        return hero

    def _metrics(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setSpacing(12)
        if self.user.role == "STUDENT":
            stats = self.service.user_stats(self.user.id)
            values = [
                ("Bài đã làm", str(stats["attempts"]), "▣", "+2 tuần này"),
                ("Điểm trung bình", f"{stats['average']}/10", "◔", "Ổn định"),
                ("Câu trả lời đúng", str(stats["correct"]), "✓", f"/{stats['total_questions']} câu"),
                ("Chuỗi luyện tập", f"{stats['streak']} ngày", "✦", "Tiếp tục nhé"),
            ]
        else:
            stats = self.service.host_stats(self.user.id)
            values = [
                ("Tổng phòng thi", str(stats["rooms"]), "▦", "Trong học kỳ này"),
                ("Phòng đang chờ", str(stats["waiting"]), "◌", "Cần bạn bắt đầu"),
                ("Đang diễn ra", str(stats["running"]), "◉", "Theo dõi trực tiếp"),
                ("Tổng thí sinh", str(stats["students"]), "♙", "Đã tham gia"),
            ]
        for label, value, icon, hint in values:
            row.addWidget(MetricCard(label, value, icon=icon, hint=hint))
        return row

    def _featured_rooms(self) -> SectionCard:
        card = SectionCard("Phòng thi nổi bật", "Các phòng đang cần sự chú ý của bạn.")
        rooms = self.service.get_rooms()[:3]
        if not rooms:
            card.layout.addWidget(EmptyStateWidget("Chưa có phòng thi", "Khi có phòng mới, chúng sẽ hiển thị tại đây."))
            return card
        for room in rooms:
            row = QFrame()
            row.setStyleSheet("QFrame{background:#F8FAFC;border-radius:9px;} QFrame:hover{background:#EFF6FF;}")
            inside = QHBoxLayout(row)
            inside.setContentsMargins(12, 10, 12, 10)
            copy = QVBoxLayout()
            name = QLabel(room.name)
            name.setStyleSheet("font-weight:700;")
            copy.addWidget(name)
            detail = QLabel(f"{room.topic}  ·  {room.difficulty}  ·  {room.question_count} câu  ·  {room.duration_minutes} phút")
            detail.setObjectName("caption")
            copy.addWidget(detail)
            inside.addLayout(copy, 1)
            inside.addWidget(StatusBadge(room.status))
            manage = QPushButton("Xem")
            manage.setObjectName("secondary")
            manage.clicked.connect(lambda _=False, room_id=room.id: self.navigate.emit("rooms"))
            inside.addWidget(manage)
            card.layout.addWidget(row)
        explore = QPushButton("Xem tất cả phòng thi →")
        explore.setObjectName("secondary")
        explore.clicked.connect(lambda: self.navigate.emit("rooms"))
        card.layout.addWidget(explore)
        return card

    def _right_column(self) -> QWidget:
        frame = QWidget()
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(16)
        if self.user.role == "STUDENT":
            layout.addWidget(self._recent_attempts())
        else:
            layout.addWidget(self._host_message())
        layout.addWidget(self._chart_card(), 1)
        return frame

    def _recent_attempts(self) -> SectionCard:
        card = SectionCard("Kết quả gần đây", "Kết quả mới nhất của bạn.")
        attempts = self.service.history(self.user.id)[:3]
        if not attempts:
            card.layout.addWidget(EmptyStateWidget("Chưa có bài làm", "Hãy bắt đầu một bài luyện tập để theo dõi tiến độ."))
            return card
        for attempt in attempts:
            row = QHBoxLayout()
            info = QLabel(f"{attempt.title}\n{attempt.topic} · {attempt.created_at}")
            info.setStyleSheet("font-weight:600;")
            row.addWidget(info, 1)
            row.addWidget(ScoreBadge(attempt.score))
            card.layout.addLayout(row)
        return card

    def _host_message(self) -> SectionCard:
        card = SectionCard("Việc cần làm", "Ưu tiên những thao tác tiếp theo cho buổi thi.")
        stats = self.service.host_stats(self.user.id)
        note = QLabel(f"Có {stats['waiting']} phòng đang chờ. Hãy kiểm tra số thí sinh trước khi bắt đầu bài thi.")
        note.setWordWrap(True)
        note.setStyleSheet("background:#EFF6FF;color:#1E3A8A;border-radius:8px;padding:12px;")
        card.layout.addWidget(note)
        button = QPushButton("Quản lý phòng chờ")
        button.setObjectName("secondary")
        button.clicked.connect(lambda: self.navigate.emit("rooms"))
        card.layout.addWidget(button)
        return card

    def _chart_card(self) -> SectionCard:
        title = "Tiến độ điểm số" if self.user.role == "STUDENT" else "Hiệu quả phòng thi"
        card = SectionCard(title, "Dữ liệu mock được cập nhật theo lịch sử bài làm.")
        chart = ChartCanvas(4.2, 2.25)
        axis = chart.axes()
        if self.user.role == "STUDENT":
            attempts = list(reversed(self.service.history(self.user.id)[:6]))
            if attempts:
                axis.plot(range(1, len(attempts) + 1), [item.score for item in attempts], marker="o", color="#2563EB", linewidth=2.2)
                axis.fill_between(range(1, len(attempts) + 1), [item.score for item in attempts], alpha=.08, color="#2563EB")
            axis.set_ylim(0, 10.5)
            axis.set_ylabel("Điểm")
        else:
            rooms = [room for room in self.service.get_rooms() if room.owner_id == self.user.id][:5]
            values = [7.2, 8.3, 7.8, 8.0, 7.5][:len(rooms)]
            axis.bar(range(len(rooms)), values, color="#60A5FA", width=.55)
            axis.set_xticks(range(len(rooms)), [f"P{room.id}" for room in rooms])
            axis.set_ylim(0, 10.5)
            axis.set_ylabel("Điểm TB")
        card.layout.addWidget(chart)
        return card
