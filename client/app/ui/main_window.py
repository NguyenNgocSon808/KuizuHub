from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (QFrame, QHBoxLayout, QLabel, QMainWindow, QMessageBox,
                               QPushButton, QStackedWidget, QVBoxLayout, QWidget)

from ..config import APP_TITLE, WINDOW_MIN_HEIGHT, WINDOW_MIN_WIDTH
from ..models import User
from ..services import MockApiService, ServiceError
from .pages import (AuthPage, CreateRoomPage, DashboardPage, ExamPage, HistoryPage,
                    PracticePage, ProfilePage, QuestionBankPage, ResultPage, RoomsPage,
                    WaitingRoomPage)


class MainWindow(QMainWindow):
    """Shell/navigation coordinator. Pages only know service methods and signals."""

    def __init__(self, service: MockApiService) -> None:
        super().__init__()
        self.service, self.user = service, None
        self.setWindowTitle(APP_TITLE); self.setMinimumSize(WINDOW_MIN_WIDTH, WINDOW_MIN_HEIGHT); self.resize(1280, 820)
        self.root = QStackedWidget(); self.root.setObjectName("root"); self.setCentralWidget(self.root)
        self.auth = AuthPage(service); self.auth.authenticated.connect(self._on_login); self.root.addWidget(self.auth)

    def _on_login(self, user: User) -> None:
        self.user = user
        if self.root.count() > 1:
            old = self.root.widget(1); self.root.removeWidget(old); old.deleteLater()
        self.shell = self._build_shell(user); self.root.addWidget(self.shell); self.root.setCurrentWidget(self.shell)

    def _build_shell(self, user: User) -> QWidget:
        shell = QWidget(); layout = QHBoxLayout(shell); layout.setContentsMargins(0, 0, 0, 0); layout.setSpacing(0)
        sidebar = self._sidebar(user); layout.addWidget(sidebar)
        workspace = QWidget(); work_layout = QVBoxLayout(workspace); work_layout.setContentsMargins(22, 16, 22, 10); work_layout.setSpacing(12)
        topbar = QHBoxLayout(); self.top_title = QLabel("Dashboard"); self.top_title.setStyleSheet("font-size:17px;font-weight:700;color:#102a43;"); topbar.addWidget(self.top_title); topbar.addStretch()
        avatar = QLabel(user.full_name[:1].upper()); avatar.setAlignment(Qt.AlignCenter); avatar.setFixedSize(34,34); avatar.setStyleSheet("background:#2f80ed;color:white;border-radius:17px;font-weight:700;")
        topbar.addWidget(avatar); person = QLabel(f"{user.full_name}\n{'Chủ phòng' if user.role == 'HOST' else 'Thí sinh'}"); person.setStyleSheet("font-size:12px;color:#475467;"); topbar.addWidget(person)
        out = QPushButton("Đăng xuất"); out.setObjectName("secondary"); out.clicked.connect(self._logout); topbar.addWidget(out); work_layout.addLayout(topbar)
        self.pages = QStackedWidget(); work_layout.addWidget(self.pages, 1); layout.addWidget(workspace, 1)
        self.dashboard = DashboardPage(self.service, user); self.rooms = RoomsPage(self.service, user); self.waiting = WaitingRoomPage(self.service, user); self.exam = ExamPage(self.service, user); self.result = ResultPage(self.service, user); self.profile = ProfilePage(self.service, user)
        self.page_map = {"dashboard": self.dashboard, "rooms": self.rooms, "waiting": self.waiting, "exam": self.exam, "result": self.result, "profile": self.profile}
        if user.role == "STUDENT":
            self.practice = PracticePage(self.service, user); self.history = HistoryPage(self.service, user); self.page_map.update({"practice": self.practice, "history": self.history})
        else:
            self.create_room = CreateRoomPage(self.service, user); self.questions = QuestionBankPage(self.service, user); self.page_map.update({"create_room": self.create_room, "questions": self.questions})
        for page in self.page_map.values(): self.pages.addWidget(page)
        self.dashboard.navigate.connect(self.show_page); self.rooms.open_waiting.connect(self.open_waiting); self.rooms.open_exam.connect(self.open_room_exam); self.waiting.open_exam.connect(self.open_room_exam); self.waiting.refresh_rooms.connect(self._refresh_rooms)
        self.exam.submitted.connect(self.open_result); self.result.go_dashboard.connect(lambda: self.show_page("dashboard")); self.result.new_practice.connect(lambda: self.show_page("practice"))
        self.profile.logged_out.connect(self._logout)
        if user.role == "STUDENT": self.practice.start_practice.connect(self.open_practice)
        else: self.create_room.created.connect(self._room_created)
        self.show_page("dashboard")
        return shell

    def _sidebar(self, user: User) -> QWidget:
        side = QFrame(); side.setObjectName("sidebar"); side.setFixedWidth(218); layout = QVBoxLayout(side); layout.setContentsMargins(14, 20, 14, 14); layout.setSpacing(5)
        brand = QLabel("◈  KuizuHub"); brand.setObjectName("brand"); layout.addWidget(brand); layout.addSpacing(18)
        identity = QLabel(f"{user.full_name}\n{'HOST · Chủ phòng' if user.role == 'HOST' else 'STUDENT · Thí sinh'}")
        identity.setObjectName("sideUser")
        layout.addWidget(identity); layout.addSpacing(12)
        links = [("⌂  Tổng quan", "dashboard"), ("▣  Phòng thi", "rooms")]
        if user.role == "STUDENT": links += [("✦  Luyện tập", "practice"), ("◔  Lịch sử & thống kê", "history")]
        else: links += [("＋  Tạo phòng thi", "create_room"), ("☷  Ngân hàng câu hỏi", "questions")]
        self.nav_buttons: dict[str, QPushButton] = {}
        for label, key in links:
            button = QPushButton(label); button.setObjectName("nav"); button.setCheckable(True); button.clicked.connect(lambda _=False, target=key: self.show_page(target)); layout.addWidget(button); self.nav_buttons[key] = button
        layout.addStretch(); profile = QPushButton("◉  Hồ sơ & cài đặt"); profile.setObjectName("nav"); profile.setCheckable(True); profile.clicked.connect(lambda: self.show_page("profile")); layout.addWidget(profile); self.nav_buttons["profile"] = profile
        return side

    def show_page(self, key: str) -> None:
        page = self.page_map.get(key)
        if not page: return
        if key in ("dashboard", "history", "profile") and hasattr(page, "refresh"): page.refresh()
        if key == "rooms": self.rooms.refresh()
        self.pages.setCurrentWidget(page)
        titles = {"dashboard": "Dashboard", "rooms": "Phòng thi", "practice": "Luyện tập", "history": "Lịch sử & thống kê", "create_room": "Tạo phòng thi", "questions": "Ngân hàng câu hỏi", "profile": "Hồ sơ cá nhân", "waiting": "Sảnh chờ", "exam": "Làm bài", "result": "Kết quả"}
        self.top_title.setText(titles.get(key, "KuizuHub"))
        for name, button in self.nav_buttons.items(): button.setChecked(name == key)

    def open_waiting(self, room_id: int) -> None:
        self.waiting.set_room(room_id); self.show_page("waiting")

    def open_room_exam(self, room_id: int) -> None:
        try:
            room, questions = self.service.get_room_exam(room_id, self.user.id)
            self.exam.load_exam(questions, title=room.name, topic=room.topic, minutes=room.duration_minutes, room_id=room.id)
            self.show_page("exam")
        except ServiceError as error:
            QMessageBox.warning(self, "Không thể vào làm bài", str(error))

    def open_practice(self, questions: object, config: object, minutes: int, title: str) -> None:
        settings = config if isinstance(config, dict) else {}
        self.exam.load_exam(questions, title=title, topic=settings.get("topic", "Trộn"), minutes=minutes, practice=True)
        self.show_page("exam")

    def open_result(self, attempt: object) -> None:
        self.result.set_attempt(attempt); self._refresh_rooms(); self.show_page("result")

    def _room_created(self) -> None:
        self._refresh_rooms(); self.show_page("rooms")

    def _refresh_rooms(self) -> None:
        self.rooms.refresh(); self.dashboard.refresh()

    def _logout(self) -> None:
        self.root.setCurrentWidget(self.auth); self.user = None
