from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (QFrame, QGridLayout, QHBoxLayout, QLabel, QPushButton,
                               QScrollArea, QVBoxLayout, QWidget)

from ...models import User
from ...services import MockApiService
from ..widgets import ChartCanvas, MetricCard, PageHeader, StatusBadge


class DashboardPage(QWidget):
    navigate = Signal(str)

    def __init__(self, service: MockApiService, user: User) -> None:
        super().__init__()
        self.service, self.user = service, user
        outer = QVBoxLayout(self); outer.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea(); scroll.setWidgetResizable(True); scroll.setFrameShape(QFrame.NoFrame)
        self.body = QWidget(); self.layout = QVBoxLayout(self.body); self.layout.setContentsMargins(6, 6, 6, 20); self.layout.setSpacing(16)
        scroll.setWidget(self.body); outer.addWidget(scroll)
        self.refresh()

    def refresh(self) -> None:
        while self.layout.count():
            item = self.layout.takeAt(0)
            if item.widget(): item.widget().deleteLater()
        self.layout.addWidget(PageHeader(f"Chào, {self.user.full_name.split()[0]}!", "Đây là tổng quan hoạt động học tập hôm nay." if self.user.role == "STUDENT" else "Quản lý phòng thi và theo dõi thí sinh của bạn."))
        self.layout.addLayout(self._metrics())
        quick = QFrame(); quick.setObjectName("card")
        quick_layout = QHBoxLayout(quick)
        title = QLabel("Thao tác nhanh"); title.setStyleSheet("font-size:16px;font-weight:700;")
        quick_layout.addWidget(title); quick_layout.addStretch()
        if self.user.role == "STUDENT":
            for text, target in [("Vào luyện tập", "practice"), ("Xem phòng thi", "rooms")]:
                button = QPushButton(text); button.clicked.connect(lambda _=False, page=target: self.navigate.emit(page)); quick_layout.addWidget(button)
        else:
            for text, target in [("Tạo phòng thi", "create_room"), ("Quản lý câu hỏi", "questions")]:
                button = QPushButton(text); button.clicked.connect(lambda _=False, page=target: self.navigate.emit(page)); quick_layout.addWidget(button)
        self.layout.addWidget(quick)
        content = QHBoxLayout(); content.setSpacing(16)
        content.addWidget(self._recent_panel(), 5)
        content.addWidget(self._chart_panel(), 5)
        self.layout.addLayout(content)
        self.layout.addStretch()

    def _metrics(self) -> QHBoxLayout:
        layout = QHBoxLayout(); layout.setSpacing(12)
        if self.user.role == "STUDENT":
            stats = self.service.user_stats(self.user.id)
            values = [("Tổng bài đã làm", str(stats["attempts"])), ("Điểm trung bình", f"{stats['average']}/10"), ("Câu trả lời đúng", str(stats["correct"])), ("Chuỗi luyện tập", f"{stats['streak']} ngày")]
        else:
            stats = self.service.host_stats(self.user.id)
            values = [("Tổng phòng thi", str(stats["rooms"])), ("Phòng đang chờ", str(stats["waiting"])), ("Đang diễn ra", str(stats["running"])), ("Tổng thí sinh", str(stats["students"]))]
        for label, value in values: layout.addWidget(MetricCard(label, value))
        return layout

    def _recent_panel(self) -> QFrame:
        frame = QFrame(); frame.setObjectName("card")
        layout = QVBoxLayout(frame)
        label = QLabel("Phòng thi gần đây" if self.user.role == "HOST" else "Phòng thi đang mở")
        label.setStyleSheet("font-size:16px;font-weight:700;"); layout.addWidget(label)
        rooms = self.service.get_rooms()[:4]
        for room in rooms:
            row = QHBoxLayout(); title = QLabel(f"{room.name}\n{room.topic} · {room.question_count} câu")
            title.setStyleSheet("font-weight:600;")
            row.addWidget(title); row.addStretch(); row.addWidget(StatusBadge(room.status)); layout.addLayout(row)
        more = QPushButton("Xem toàn bộ phòng")
        more.setObjectName("secondary"); more.clicked.connect(lambda: self.navigate.emit("rooms")); layout.addWidget(more)
        return frame

    def _chart_panel(self) -> QFrame:
        frame = QFrame(); frame.setObjectName("card")
        layout = QVBoxLayout(frame)
        title = QLabel("Điểm các bài gần đây" if self.user.role == "STUDENT" else "Thống kê điểm trung bình theo phòng")
        title.setStyleSheet("font-size:16px;font-weight:700;"); layout.addWidget(title)
        chart = ChartCanvas(4.8, 2.5); axis = chart.axes()
        if self.user.role == "STUDENT":
            data = list(reversed(self.service.history(self.user.id)[:6]))
            axis.plot(range(1, len(data) + 1), [item.score for item in data], marker="o", color="#2f80ed", linewidth=2.4)
            axis.set_ylim(0, 10.5); axis.set_ylabel("Điểm"); axis.set_xlabel("Bài làm")
        else:
            rooms = [room for room in self.service.get_rooms() if room.owner_id == self.user.id][:6]
            values = [7.4, 8.1, 6.8, 7.7, 8.3, 7.0][:len(rooms)]
            axis.bar(range(len(rooms)), values, color="#61a5fa")
            axis.set_xticks(range(len(rooms)), [str(room.id) for room in rooms]); axis.set_ylim(0, 10.5); axis.set_ylabel("Điểm TB")
        layout.addWidget(chart)
        return frame
