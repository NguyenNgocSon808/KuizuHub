"""Modern desktop shell: role-aware sidebar, topbar and page navigation."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QFrame, QHBoxLayout, QLabel, QMainWindow, QMenu, QMessageBox,
                               QPushButton, QStackedWidget, QToolButton, QVBoxLayout, QWidget)

from ..config import APP_TITLE, WINDOW_MIN_HEIGHT, WINDOW_MIN_WIDTH
from ..models import User
from ..services import MockApiService, ServiceError
from .pages import (AuthPage, CreateRoomPage, DashboardPage, ExamPage, HistoryPage,
                    PracticePage, ProfilePage, QuestionBankPage, ResultPage, RoomsPage,
                    WaitingRoomPage)
from .widgets import SearchInput, SecondaryButton, UserAvatar, show_toast


class MainWindow(QMainWindow):
    """Coordinates navigation only; feature data remains behind the service layer."""

    def __init__(self, service: MockApiService) -> None:
        super().__init__()
        self.service, self.user = service, None
        self.setWindowTitle(APP_TITLE)
        self.setMinimumSize(WINDOW_MIN_WIDTH, WINDOW_MIN_HEIGHT)
        self.resize(1360, 860)
        self.root = QStackedWidget()
        self.root.setObjectName("root")
        self.setCentralWidget(self.root)
        self.auth = AuthPage(service)
        self.auth.authenticated.connect(self._on_login)
        self.root.addWidget(self.auth)

    def _on_login(self, user: User) -> None:
        self.user = user
        if self.root.count() > 1:
            old_shell = self.root.widget(1)
            self.root.removeWidget(old_shell)
            old_shell.deleteLater()
        self.shell = self._build_shell(user)
        self.root.addWidget(self.shell)
        self.root.setCurrentWidget(self.shell)
        show_toast(self, f"Chào mừng trở lại, {user.full_name.split()[0]}!")

    def _build_shell(self, user: User) -> QWidget:
        shell = QWidget()
        layout = QHBoxLayout(shell)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self._sidebar(user))

        workspace = QWidget()
        workspace.setObjectName("workspace")
        workspace_layout = QVBoxLayout(workspace)
        workspace_layout.setContentsMargins(22, 16, 22, 18)
        workspace_layout.setSpacing(14)
        workspace_layout.addWidget(self._topbar(user))
        self.pages = QStackedWidget()
        workspace_layout.addWidget(self.pages, 1)
        layout.addWidget(workspace, 1)

        self.dashboard = DashboardPage(self.service, user)
        self.rooms = RoomsPage(self.service, user)
        self.waiting = WaitingRoomPage(self.service, user)
        self.exam = ExamPage(self.service, user)
        self.result = ResultPage(self.service, user)
        self.profile = ProfilePage(self.service, user)
        self.page_map = {"dashboard": self.dashboard, "rooms": self.rooms, "waiting": self.waiting,
                         "exam": self.exam, "result": self.result, "profile": self.profile}
        if user.role == "STUDENT":
            self.practice = PracticePage(self.service, user)
            self.history = HistoryPage(self.service, user)
            self.page_map.update({"practice": self.practice, "history": self.history})
        else:
            self.create_room = CreateRoomPage(self.service, user)
            self.questions = QuestionBankPage(self.service, user)
            self.page_map.update({"create_room": self.create_room, "questions": self.questions})
        for page in self.page_map.values():
            self.pages.addWidget(page)

        self.dashboard.navigate.connect(self.show_page)
        self.rooms.open_waiting.connect(self.open_waiting)
        self.rooms.open_exam.connect(self.open_room_exam)
        self.rooms.create_requested.connect(lambda: self.show_page("create_room"))
        self.waiting.open_exam.connect(self.open_room_exam)
        self.waiting.refresh_rooms.connect(self._refresh_rooms)
        self.exam.submitted.connect(self.open_result)
        self.result.go_dashboard.connect(lambda: self.show_page("dashboard"))
        self.result.new_practice.connect(lambda: self.show_page("practice"))
        self.result.go_history.connect(lambda: self.show_page("history"))
        self.profile.logged_out.connect(self._logout)
        if user.role == "STUDENT":
            self.practice.start_practice.connect(self.open_practice)
        else:
            self.create_room.created.connect(self._room_created)
        self.show_page("dashboard")
        return shell

    def _sidebar(self, user: User) -> QWidget:
        side = QFrame()
        side.setObjectName("sidebar")
        side.setFixedWidth(252)
        layout = QVBoxLayout(side)
        layout.setContentsMargins(16, 18, 16, 16)
        layout.setSpacing(6)
        brand_row = QHBoxLayout()
        mark = QLabel("K")
        mark.setObjectName("brandMark")
        mark.setAlignment(Qt.AlignCenter)
        mark.setFixedSize(36, 36)
        brand_row.addWidget(mark)
        brand = QLabel("Online Exam")
        brand.setObjectName("brand")
        brand_row.addWidget(brand)
        brand_row.addStretch()
        layout.addLayout(brand_row)
        layout.addSpacing(22)
        menu_label = QLabel("KHÔNG GIAN HỌC TẬP")
        menu_label.setObjectName("caption")
        layout.addWidget(menu_label)
        layout.addSpacing(4)
        links = [("▦  Tổng quan", "dashboard"), ("◫  Phòng thi", "rooms")]
        if user.role == "STUDENT":
            links.extend([("✦  Luyện tập", "practice"), ("◔  Lịch sử & thống kê", "history")])
        else:
            links.extend([("＋  Tạo phòng thi", "create_room"), ("☷  Ngân hàng câu hỏi", "questions")])
        self.nav_buttons: dict[str, QPushButton] = {}
        for title, key in links:
            button = QPushButton(title)
            button.setObjectName("nav")
            button.setCheckable(True)
            button.clicked.connect(lambda _=False, destination=key: self.show_page(destination))
            layout.addWidget(button)
            self.nav_buttons[key] = button
        layout.addStretch()
        divider = QFrame()
        divider.setFrameShape(QFrame.HLine)
        divider.setStyleSheet("color:#E2E8F0;")
        layout.addWidget(divider)
        profile_button = QPushButton("◉  Hồ sơ cá nhân")
        profile_button.setObjectName("nav")
        profile_button.setCheckable(True)
        profile_button.clicked.connect(lambda: self.show_page("profile"))
        layout.addWidget(profile_button)
        self.nav_buttons["profile"] = profile_button
        account = QFrame()
        account.setStyleSheet("background:#F8FAFC;border-radius:10px;")
        account_layout = QHBoxLayout(account)
        account_layout.setContentsMargins(9, 9, 9, 9)
        account_layout.addWidget(UserAvatar(user.full_name, 32))
        account_copy = QLabel(f"{user.full_name}\n{'Chủ phòng' if user.role == 'HOST' else 'Thí sinh'}")
        account_copy.setObjectName("sideUser")
        account_layout.addWidget(account_copy, 1)
        layout.addWidget(account)
        return side

    def _topbar(self, user: User) -> QWidget:
        topbar = QFrame()
        topbar.setObjectName("topbar")
        layout = QHBoxLayout(topbar)
        layout.setContentsMargins(14, 8, 12, 8)
        self.breadcrumb = QLabel("Không gian học tập  /  Tổng quan")
        self.breadcrumb.setStyleSheet("color:#64748B;font-weight:600;")
        layout.addWidget(self.breadcrumb)
        layout.addStretch()
        search = SearchInput("Tìm nhanh phòng hoặc câu hỏi")
        search.setFixedWidth(250)
        search.setToolTip("Tìm kiếm nhanh (minh họa)")
        layout.addWidget(search)
        bell = SecondaryButton("♧")
        bell.setFixedWidth(40)
        bell.setToolTip("Thông báo")
        notification_menu = QMenu(bell)
        notification_menu.addAction("✓ Dữ liệu demo đã sẵn sàng")
        notification_menu.addAction("Phòng TCP Socket đang chờ thí sinh")
        bell.setMenu(notification_menu)
        layout.addWidget(bell)
        layout.addWidget(UserAvatar(user.full_name, 34))
        identity = QLabel(f"{user.full_name}\n{'Chủ phòng' if user.role == 'HOST' else 'Thí sinh'}")
        identity.setStyleSheet("font-size:12px;color:#475569;")
        layout.addWidget(identity)
        role = QLabel("HOST" if user.role == "HOST" else "STUDENT")
        role.setStyleSheet("background:#EFF6FF;color:#1D4ED8;border-radius:8px;padding:4px 6px;font-size:10px;font-weight:700;")
        layout.addWidget(role)
        menu_button = QToolButton()
        menu_button.setText("⌄")
        menu_button.setToolTip("Menu tài khoản")
        menu = QMenu(menu_button)
        profile_action = menu.addAction("Hồ sơ cá nhân")
        profile_action.triggered.connect(lambda: self.show_page("profile"))
        logout_action = menu.addAction("Đăng xuất")
        logout_action.triggered.connect(self._confirm_logout)
        menu_button.setMenu(menu)
        menu_button.setPopupMode(QToolButton.InstantPopup)
        layout.addWidget(menu_button)
        return topbar

    def show_page(self, key: str) -> None:
        page = self.page_map.get(key)
        if not page:
            return
        if key in ("dashboard", "history", "profile") and hasattr(page, "refresh"):
            page.refresh()
        if key == "rooms":
            self.rooms.refresh()
        self.pages.setCurrentWidget(page)
        names = {"dashboard": "Tổng quan", "rooms": "Phòng thi", "practice": "Luyện tập",
                 "history": "Lịch sử & thống kê", "create_room": "Tạo phòng thi",
                 "questions": "Ngân hàng câu hỏi", "profile": "Hồ sơ cá nhân",
                 "waiting": "Sảnh chờ", "exam": "Làm bài", "result": "Kết quả"}
        title = names.get(key, "Online Exam")
        self.breadcrumb.setText(f"Không gian học tập  /  {title}")
        for name, button in self.nav_buttons.items():
            button.setChecked(name == key)

    def open_waiting(self, room_id: int) -> None:
        self.waiting.set_room(room_id)
        self.show_page("waiting")

    def open_room_exam(self, room_id: int) -> None:
        try:
            room, questions = self.service.get_room_exam(room_id, self.user.id)
            self.exam.load_exam(questions, title=room.name, topic=room.topic,
                                minutes=room.duration_minutes, room_id=room.id)
            self.show_page("exam")
        except ServiceError as error:
            QMessageBox.warning(self, "Không thể vào làm bài", str(error))

    def open_practice(self, questions: object, config: object, minutes: int, title: str) -> None:
        settings = config if isinstance(config, dict) else {}
        self.exam.load_exam(questions, title=title, topic=settings.get("topic", "Trộn"),
                            minutes=minutes, practice=True)
        self.show_page("exam")

    def open_result(self, attempt: object) -> None:
        self.result.set_attempt(attempt)
        self._refresh_rooms()
        show_toast(self, "Đã nộp bài và lưu kết quả demo.")
        self.show_page("result")

    def _room_created(self) -> None:
        self._refresh_rooms()
        show_toast(self, "Tạo phòng thi thành công.")
        self.show_page("rooms")

    def _refresh_rooms(self) -> None:
        self.rooms.refresh()
        self.dashboard.refresh()

    def _confirm_logout(self) -> None:
        if QMessageBox.question(self, "Đăng xuất", "Bạn có chắc muốn đăng xuất khỏi phiên demo này?", QMessageBox.Yes | QMessageBox.No) == QMessageBox.Yes:
            self._logout()

    def _logout(self) -> None:
        self.root.setCurrentWidget(self.auth)
        self.user = None
