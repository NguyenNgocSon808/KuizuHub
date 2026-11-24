"""Shared server-backed auth, dashboard, and question-bank UI surfaces."""

from __future__ import annotations

from dataclasses import dataclass
import csv
import json
from pathlib import Path
from typing import Any

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPushButton,
    QStackedWidget,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from ..config import APP_TITLE, WINDOW_MIN_HEIGHT, WINDOW_MIN_WIDTH
from ..services.tcp_api_service import PhaseOneApiService
from .widgets import PrimaryButton, SecondaryButton, UserAvatar, show_toast


@dataclass(frozen=True)
class LiveUser:
    id: int
    username: str
    role: str
    created_at: str = ""

    @classmethod
    def from_wire(cls, value: object) -> "LiveUser":
        if not isinstance(value, dict):
            raise ValueError("Server did not return user data")
        user_id = value.get("id")
        username = value.get("username")
        role = value.get("role")
        if not isinstance(user_id, int) or not isinstance(username, str) or not isinstance(role, str):
            raise ValueError("Server returned invalid user data")
        created_at = value.get("created_at", "")
        return cls(user_id, username, role, created_at if isinstance(created_at, str) else "")


def _response_data(response: object) -> dict[str, Any]:
    if not isinstance(response, dict) or not isinstance(response.get("data"), dict):
        raise ValueError("Server returned an invalid success response")
    return response["data"]


class LiveAuthPage(QWidget):
    authenticated = Signal(object)

    def __init__(self, service: PhaseOneApiService) -> None:
        super().__init__()
        self.service = service
        self._pending: dict[str, str] = {}
        self.stack = QStackedWidget()
        self.stack.addWidget(self._login_form())
        self.stack.addWidget(self._register_form())

        outer = QHBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        outer.addWidget(self._brand_panel(), 5)
        form_area = QWidget()
        form_layout = QVBoxLayout(form_area)
        form_layout.setContentsMargins(72, 42, 72, 42)
        form_layout.addStretch()
        form_layout.addWidget(self.stack)
        form_layout.addStretch()
        outer.addWidget(form_area, 6)

        self.service.request_succeeded.connect(self._on_success)
        self.service.request_failed.connect(self._on_failure)

    def _brand_panel(self) -> QFrame:
        panel = QFrame()
        panel.setStyleSheet("background:#0F2742;")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(54, 48, 54, 48)
        mark = QLabel("K")
        mark.setAlignment(Qt.AlignCenter)
        mark.setFixedSize(42, 42)
        mark.setStyleSheet("background:#2563EB;color:white;border-radius:11px;font-size:20px;font-weight:700;")
        layout.addWidget(mark)
        layout.addStretch()
        title = QLabel("KuizuHub")
        title.setStyleSheet("color:white;font-size:34px;font-weight:700;")
        layout.addWidget(title)
        copy = QLabel("TCP NDJSON thực\nĐăng nhập để làm bài, luyện tập và quản lý câu hỏi.")
        copy.setStyleSheet("color:#BFD4EA;font-size:16px;")
        copy.setWordWrap(True)
        layout.addWidget(copy)
        layout.addSpacing(22)
        facts = QLabel("✓  Xác thực qua server C\n✓  Không dùng dữ liệu mock\n✓  Mạng chạy ngoài UI thread")
        facts.setStyleSheet("color:#D7E5F3;line-height:1.8;")
        layout.addWidget(facts)
        layout.addStretch()
        caption = QLabel("Kết nối tới 127.0.0.1:5050 mặc định")
        caption.setStyleSheet("color:#8CA8C1;font-size:12px;")
        layout.addWidget(caption)
        return panel

    @staticmethod
    def _form_shell(title: str, detail: str) -> tuple[QFrame, QVBoxLayout]:
        frame = QFrame()
        frame.setObjectName("sectionCard")
        frame.setMaximumWidth(480)
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(28, 28, 28, 28)
        layout.setSpacing(12)
        heading = QLabel(title)
        heading.setObjectName("pageTitle")
        layout.addWidget(heading)
        description = QLabel(detail)
        description.setObjectName("subtle")
        description.setWordWrap(True)
        layout.addWidget(description)
        return frame, layout

    @staticmethod
    def _notice_label() -> QLabel:
        label = QLabel()
        label.setWordWrap(True)
        label.setStyleSheet("color:#DC2626;font-size:12px;")
        return label

    def _login_form(self) -> QWidget:
        frame, layout = self._form_shell("Chào mừng trở lại", "Đăng nhập bằng tài khoản đã có trên server.")
        form = QFormLayout()
        self.login_username = QLineEdit()
        self.login_username.setPlaceholderText("Username")
        self.login_password = QLineEdit()
        self.login_password.setPlaceholderText("Mật khẩu")
        self.login_password.setEchoMode(QLineEdit.Password)
        form.addRow("Username", self.login_username)
        form.addRow("Mật khẩu", self.login_password)
        layout.addLayout(form)
        self.login_notice = self._notice_label()
        layout.addWidget(self.login_notice)
        self.login_button = PrimaryButton("Đăng nhập")
        self.login_button.clicked.connect(self._login)
        self.login_password.returnPressed.connect(self._login)
        layout.addWidget(self.login_button)
        switch = SecondaryButton("Chưa có tài khoản? Đăng ký")
        switch.clicked.connect(lambda: self.stack.setCurrentIndex(1))
        layout.addWidget(switch)
        return frame

    def _register_form(self) -> QWidget:
        frame, layout = self._form_shell(
            "Tạo tài khoản",
            "Vai trò được gửi theo contract REGISTER hiện tại của server.",
        )
        form = QFormLayout()
        self.register_username = QLineEdit()
        self.register_username.setPlaceholderText("3–32 ký tự: chữ, số, _, -, .")
        self.register_password = QLineEdit()
        self.register_password.setPlaceholderText("Ít nhất 8 ký tự")
        self.register_password.setEchoMode(QLineEdit.Password)
        self.register_confirm = QLineEdit()
        self.register_confirm.setPlaceholderText("Nhập lại mật khẩu")
        self.register_confirm.setEchoMode(QLineEdit.Password)
        self.register_role = QComboBox()
        self.register_role.addItem("Thí sinh", "STUDENT")
        self.register_role.addItem("Chủ phòng", "HOST")
        self.register_role.addItem("Quản trị viên", "ADMIN")
        form.addRow("Username", self.register_username)
        form.addRow("Mật khẩu", self.register_password)
        form.addRow("Xác nhận", self.register_confirm)
        form.addRow("Vai trò", self.register_role)
        layout.addLayout(form)
        self.register_notice = self._notice_label()
        layout.addWidget(self.register_notice)
        self.register_button = PrimaryButton("Tạo tài khoản")
        self.register_button.clicked.connect(self._register)
        self.register_confirm.returnPressed.connect(self._register)
        layout.addWidget(self.register_button)
        back = SecondaryButton("← Quay về đăng nhập")
        back.clicked.connect(lambda: self.stack.setCurrentIndex(0))
        layout.addWidget(back)
        return frame

    def _login(self) -> None:
        username, password = self.login_username.text().strip(), self.login_password.text()
        if not username or not password:
            self.login_notice.setText("Hãy nhập username và mật khẩu.")
            return
        self.login_notice.clear()
        self.login_button.setEnabled(False)
        self.login_button.setText("Đang đăng nhập…")
        request_id = self.service.login(username, password)
        self._pending[request_id] = "login"

    def _register(self) -> None:
        username = self.register_username.text().strip()
        password = self.register_password.text()
        if not username or not password:
            self.register_notice.setText("Username và mật khẩu là bắt buộc.")
            return
        if password != self.register_confirm.text():
            self.register_notice.setText("Xác nhận mật khẩu chưa khớp.")
            return
        self.register_notice.clear()
        self.register_button.setEnabled(False)
        self.register_button.setText("Đang tạo tài khoản…")
        request_id = self.service.register(username, password, str(self.register_role.currentData()))
        self._pending[request_id] = "register"

    def _on_success(self, request_id: str, response: object) -> None:
        action = self._pending.pop(request_id, None)
        if action == "register":
            self.register_button.setEnabled(True)
            self.register_button.setText("Tạo tài khoản")
            self.stack.setCurrentIndex(0)
            self.login_username.setText(self.register_username.text().strip())
            self.login_password.clear()
            self.login_notice.setStyleSheet("color:#16A34A;font-size:12px;")
            self.login_notice.setText("Đăng ký thành công. Hãy đăng nhập.")
        elif action == "login":
            self.login_button.setEnabled(True)
            self.login_button.setText("Đăng nhập")
            try:
                user = LiveUser.from_wire(_response_data(response).get("user"))
            except ValueError as error:
                self.login_notice.setText(str(error))
                return
            self.login_notice.clear()
            self.authenticated.emit(user)

    def _on_failure(self, request_id: str, message: str) -> None:
        action = self._pending.pop(request_id, None)
        if action == "register":
            self.register_button.setEnabled(True)
            self.register_button.setText("Tạo tài khoản")
            self.register_notice.setText(message)
        elif action == "login":
            self.login_button.setEnabled(True)
            self.login_button.setText("Đăng nhập")
            self.login_notice.setText(message)


class LiveDashboardPage(QWidget):
    open_questions = Signal()
    logged_out = Signal()

    def __init__(self, service: PhaseOneApiService, user: LiveUser) -> None:
        super().__init__()
        self.service, self.user = service, user
        self._pending_profile: str | None = None
        self._pending_logout: str | None = None
        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(16)

        hero = QFrame()
        hero.setObjectName("heroCard")
        hero_layout = QVBoxLayout(hero)
        hero_layout.setContentsMargins(24, 22, 24, 22)
        title = QLabel(f"Xin chào, {user.username}!")
        title.setObjectName("pageTitle")
        hero_layout.addWidget(title)
        copy = QLabel("Bạn đang dùng dữ liệu thật từ TCP server. Phòng thi, luyện tập, lịch sử và thống kê đều được đồng bộ từ server.")
        copy.setObjectName("subtle")
        copy.setWordWrap(True)
        hero_layout.addWidget(copy)
        root.addWidget(hero)

        profile = QFrame()
        profile.setObjectName("sectionCard")
        profile_layout = QVBoxLayout(profile)
        profile_layout.setContentsMargins(18, 16, 18, 16)
        profile_layout.addWidget(QLabel("Phiên hiện tại", objectName="sectionTitle"))
        self.profile_label = QLabel("Đang xác minh phiên với server…")
        self.profile_label.setObjectName("subtle")
        self.profile_label.setWordWrap(True)
        profile_layout.addWidget(self.profile_label)
        root.addWidget(profile)

        action_card = QFrame()
        action_card.setObjectName("sectionCard")
        actions = QVBoxLayout(action_card)
        actions.setContentsMargins(18, 16, 18, 16)
        actions.addWidget(QLabel("Thao tác tài khoản", objectName="sectionTitle"))
        if user.role == "ADMIN":
            questions = PrimaryButton("Mở ngân hàng câu hỏi")
            questions.clicked.connect(self.open_questions)
            actions.addWidget(questions, alignment=Qt.AlignLeft)
        else:
            limited = QLabel("Ngân hàng câu hỏi chỉ mở cho vai trò ADMIN. Hãy đăng nhập bằng tài khoản ADMIN để tạo, sửa, disable hoặc import câu hỏi.")
            limited.setObjectName("subtle")
            limited.setWordWrap(True)
            actions.addWidget(limited)
        self.logout_button = SecondaryButton("Đăng xuất")
        self.logout_button.clicked.connect(self._logout)
        actions.addWidget(self.logout_button, alignment=Qt.AlignLeft)
        root.addWidget(action_card)
        root.addStretch()

        self.service.request_succeeded.connect(self._on_success)
        self.service.request_failed.connect(self._on_failure)
        self.refresh_profile()

    def refresh_profile(self) -> None:
        self.profile_label.setText("Đang xác minh phiên với server…")
        self._pending_profile = self.service.get_my_profile()

    def _logout(self) -> None:
        self.logout_button.setEnabled(False)
        self.logout_button.setText("Đang đăng xuất…")
        self._pending_logout = self.service.logout()

    def _on_success(self, request_id: str, response: object) -> None:
        if request_id == self._pending_profile:
            self._pending_profile = None
            try:
                self.user = LiveUser.from_wire(_response_data(response).get("user"))
                joined = f" · tạo lúc {self.user.created_at}" if self.user.created_at else ""
                self.profile_label.setText(
                    f"Username: @{self.user.username} · Vai trò: {self.user.role}{joined}"
                )
            except ValueError as error:
                self.profile_label.setText(str(error))
        elif request_id == self._pending_logout:
            self._pending_logout = None
            self.logged_out.emit()

    def _on_failure(self, request_id: str, message: str) -> None:
        if request_id == self._pending_profile:
            self._pending_profile = None
            self.profile_label.setText(f"Không thể lấy profile: {message}")
        elif request_id == self._pending_logout:
            self._pending_logout = None
            self.logout_button.setEnabled(True)
            self.logout_button.setText("Đăng xuất")
            QMessageBox.warning(self, "Không thể đăng xuất", message)


class QuestionDialog(QDialog):
    def __init__(self, question: dict[str, Any] | None = None, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Sửa câu hỏi" if question else "Thêm câu hỏi")
        self.resize(640, 580)
        layout = QVBoxLayout(self)
        title = QLabel("Cập nhật câu hỏi")
        title.setObjectName("pageTitle")
        layout.addWidget(title)
        form = QFormLayout()
        self.content = QTextEdit()
        self.content.setFixedHeight(72)
        self.options = [QLineEdit() for _ in range(4)]
        self.correct_index = QComboBox()
        self.correct_index.addItems(["A", "B", "C", "D"])
        self.topic = QLineEdit()
        self.topic.setPlaceholderText("Ví dụ: TCP Socket")
        self.difficulty = QComboBox()
        self.difficulty.addItem("Dễ", "easy")
        self.difficulty.addItem("Trung bình", "medium")
        self.difficulty.addItem("Khó", "hard")
        self.explanation = QTextEdit()
        self.explanation.setFixedHeight(64)
        form.addRow("Nội dung *", self.content)
        for index, option in enumerate(self.options):
            option.setPlaceholderText(f"Đáp án {chr(65 + index)}")
            form.addRow(f"Đáp án {chr(65 + index)} *", option)
        form.addRow("Đáp án đúng", self.correct_index)
        form.addRow("Chủ đề *", self.topic)
        form.addRow("Độ khó", self.difficulty)
        form.addRow("Giải thích", self.explanation)
        layout.addLayout(form)
        self.error = QLabel()
        self.error.setStyleSheet("color:#DC2626;font-size:12px;")
        self.error.setWordWrap(True)
        layout.addWidget(self.error)
        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self._validate_and_accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        if question is not None:
            self._load(question)

    def _load(self, question: dict[str, Any]) -> None:
        self.content.setPlainText(str(question.get("content", "")))
        options = question.get("options", [])
        if isinstance(options, list):
            for field, option in zip(self.options, options):
                field.setText(str(option.get("content", "")) if isinstance(option, dict) else str(option))
        correct = question.get("correct_option_index", 0)
        self.correct_index.setCurrentIndex(correct if isinstance(correct, int) and 0 <= correct < 4 else 0)
        self.topic.setText(str(question.get("topic", "")))
        difficulty_index = self.difficulty.findData(question.get("difficulty"))
        self.difficulty.setCurrentIndex(difficulty_index if difficulty_index >= 0 else 0)
        self.explanation.setPlainText(str(question.get("explanation", "")))

    def _validate_and_accept(self) -> None:
        data = self.question_data()
        if not data["content"].strip() or not data["topic"].strip() or not all(data["options"]):
            self.error.setText("Nội dung, chủ đề và đủ bốn đáp án là bắt buộc.")
            return
        self.accept()

    def question_data(self) -> dict[str, Any]:
        return {
            "content": self.content.toPlainText().strip(),
            "topic": self.topic.text().strip(),
            "difficulty": str(self.difficulty.currentData()),
            "options": [field.text().strip() for field in self.options],
            "correct_option_index": self.correct_index.currentIndex(),
            "explanation": self.explanation.toPlainText().strip(),
        }


class QuestionBankPage(QWidget):
    back_to_dashboard = Signal()

    def __init__(self, service: PhaseOneApiService) -> None:
        super().__init__()
        self.service = service
        self.questions: list[dict[str, Any]] = []
        self.offset = 0
        self._pending: dict[str, str] = {}
        self._has_more = False
        self._export_path: Path | None = None
        self._export_rows: list[dict[str, Any]] = []
        self._export_offset = 0
        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(12)
        header = QHBoxLayout()
        copy = QVBoxLayout()
        title = QLabel("Ngân hàng câu hỏi")
        title.setObjectName("pageTitle")
        copy.addWidget(title)
        subtitle = QLabel("Dữ liệu đọc và ghi trực tiếp qua TCP server; chỉ ADMIN có quyền thao tác.")
        subtitle.setObjectName("subtle")
        copy.addWidget(subtitle)
        header.addLayout(copy, 1)
        add = PrimaryButton("＋ Thêm câu hỏi")
        add.clicked.connect(self._add)
        header.addWidget(add)
        import_button = SecondaryButton("Nhập JSON")
        import_button.clicked.connect(self._import_json_file)
        header.addWidget(import_button)
        import_csv_button = SecondaryButton("Nhập CSV")
        import_csv_button.clicked.connect(self._import_csv_file)
        header.addWidget(import_csv_button)
        export_csv_button = SecondaryButton("Xuất CSV")
        export_csv_button.clicked.connect(self._export_csv)
        header.addWidget(export_csv_button)
        root.addLayout(header)

        filters = QFrame()
        filters.setObjectName("sectionCard")
        filter_layout = QHBoxLayout(filters)
        filter_layout.setContentsMargins(12, 10, 12, 10)
        self.query = QLineEdit()
        self.query.setPlaceholderText("Tìm theo nội dung")
        self.query.returnPressed.connect(self._apply_filters)
        self.topic = QLineEdit()
        self.topic.setPlaceholderText("Chủ đề (tùy chọn)")
        self.topic.returnPressed.connect(self._apply_filters)
        self.difficulty = QComboBox()
        self.difficulty.addItem("Mọi độ khó", "")
        self.difficulty.addItem("Dễ", "easy")
        self.difficulty.addItem("Trung bình", "medium")
        self.difficulty.addItem("Khó", "hard")
        self.include_inactive = QCheckBox("Hiện câu đã disable")
        self.include_inactive.setChecked(True)
        refresh = SecondaryButton("Lọc")
        refresh.clicked.connect(self._apply_filters)
        filter_layout.addWidget(self.query, 3)
        filter_layout.addWidget(self.topic, 2)
        filter_layout.addWidget(self.difficulty)
        filter_layout.addWidget(self.include_inactive)
        filter_layout.addWidget(refresh)
        root.addWidget(filters)

        self.notice = QLabel("Đang tải câu hỏi…")
        self.notice.setObjectName("subtle")
        root.addWidget(self.notice)
        self.table = QTableWidget(0, 7)
        self.table.setHorizontalHeaderLabels(["ID", "Nội dung", "Chủ đề", "Độ khó", "Đúng", "Trạng thái", ""])
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setStretchLastSection(True)
        root.addWidget(self.table, 1)
        pagination = QHBoxLayout()
        self.previous = SecondaryButton("← Trước")
        self.previous.clicked.connect(self._previous)
        self.next = SecondaryButton("Sau →")
        self.next.clicked.connect(self._next)
        pagination.addWidget(self.previous)
        pagination.addWidget(self.next)
        pagination.addStretch()
        root.addLayout(pagination)

        self.service.request_succeeded.connect(self._on_success)
        self.service.request_failed.connect(self._on_failure)
        self.refresh()

    def _apply_filters(self) -> None:
        self.offset = 0
        self.refresh()

    def _previous(self) -> None:
        if self.offset >= 20:
            self.offset -= 20
            self.refresh()

    def _next(self) -> None:
        if self._has_more:
            self.offset += 20
            self.refresh()

    def refresh(self) -> None:
        self.notice.setText("Đang tải câu hỏi…")
        request_id = self.service.list_questions(
            query=self.query.text().strip(),
            topic=self.topic.text().strip(),
            difficulty=str(self.difficulty.currentData()),
            include_inactive=self.include_inactive.isChecked(),
            limit=20,
            offset=self.offset,
        )
        self._pending[request_id] = "list"

    def _add(self) -> None:
        dialog = QuestionDialog(parent=self)
        if dialog.exec() == QDialog.Accepted:
            request_id = self.service.create_question(dialog.question_data())
            self._pending[request_id] = "create"
            self.notice.setText("Đang tạo câu hỏi…")

    def _edit(self, question: dict[str, Any]) -> None:
        dialog = QuestionDialog(question, self)
        if dialog.exec() == QDialog.Accepted:
            request_id = self.service.update_question(int(question["id"]), question=dialog.question_data())
            self._pending[request_id] = "update"
            self.notice.setText("Đang cập nhật câu hỏi…")

    def _toggle_active(self, question: dict[str, Any]) -> None:
        active = bool(question.get("is_active"))
        action = "disable" if active else "enable"
        if QMessageBox.question(
            self,
            "Xác nhận",
            f"Bạn muốn {'disable' if active else 'enable'} câu hỏi #{question['id']}?",
            QMessageBox.Yes | QMessageBox.No,
        ) != QMessageBox.Yes:
            return
        request_id = self.service.update_question(int(question["id"]), is_active=not active)
        self._pending[request_id] = action
        self.notice.setText("Đang cập nhật trạng thái…")

    def _import_json_file(self) -> None:
        file_name, _ = QFileDialog.getOpenFileName(self, "Chọn file JSON câu hỏi", "", "JSON files (*.json)")
        if not file_name:
            return
        try:
            raw = json.loads(Path(file_name).read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            QMessageBox.warning(self, "Không thể đọc file", str(error))
            return
        if not isinstance(raw, list) or not all(isinstance(item, dict) for item in raw):
            QMessageBox.warning(self, "File không hợp lệ", "File phải là một mảng JSON các câu hỏi.")
            return
        request_id = self.service.import_questions(raw)
        self._pending[request_id] = "import"
        self.notice.setText("Đang import câu hỏi…")

    @staticmethod
    def _csv_question_rows(file_name: str) -> list[dict[str, Any]]:
        required = {
            "content", "topic", "difficulty", "option_a", "option_b", "option_c", "option_d",
            "correct_option_index",
        }
        with Path(file_name).open("r", encoding="utf-8-sig", newline="") as source:
            reader = csv.DictReader(source)
            if reader.fieldnames is None or not required.issubset(set(reader.fieldnames)):
                raise ValueError("CSV cần các cột: " + ", ".join(sorted(required)))
            questions: list[dict[str, Any]] = []
            for line_number, row in enumerate(reader, start=2):
                content = (row.get("content") or "").strip()
                topic = (row.get("topic") or "").strip()
                difficulty = (row.get("difficulty") or "").strip()
                options = [(row.get(f"option_{letter}") or "").strip() for letter in "abcd"]
                correct_raw = (row.get("correct_option_index") or "").strip().upper()
                if correct_raw in {"A", "B", "C", "D"}:
                    correct_index = "ABCD".index(correct_raw)
                else:
                    try:
                        correct_index = int(correct_raw)
                    except ValueError as error:
                        raise ValueError(f"Dòng {line_number}: correct_option_index phải là 0-3 hoặc A-D.") from error
                if not content or not topic or difficulty not in {"easy", "medium", "hard"} or not all(options):
                    raise ValueError(
                        f"Dòng {line_number}: content, topic, difficulty (easy/medium/hard) và 4 đáp án là bắt buộc."
                    )
                if correct_index not in range(4):
                    raise ValueError(f"Dòng {line_number}: correct_option_index phải từ 0 đến 3.")
                questions.append({
                    "content": content,
                    "topic": topic,
                    "difficulty": difficulty,
                    "options": options,
                    "correct_option_index": correct_index,
                    "explanation": (row.get("explanation") or "").strip(),
                })
        if not questions:
            raise ValueError("CSV không có câu hỏi nào.")
        if len(questions) > 100:
            raise ValueError("Mỗi lần import tối đa 100 dòng để đảm bảo transaction atomic.")
        return questions

    def _import_csv_file(self) -> None:
        file_name, _ = QFileDialog.getOpenFileName(self, "Chọn file CSV câu hỏi", "", "CSV files (*.csv)")
        if not file_name:
            return
        try:
            questions = self._csv_question_rows(file_name)
        except (OSError, ValueError) as error:
            QMessageBox.warning(self, "CSV không hợp lệ", str(error))
            return
        request_id = self.service.import_questions(questions)
        self._pending[request_id] = "import_csv"
        self.notice.setText(f"Đang import {len(questions)} câu hỏi từ CSV…")

    def _export_csv(self) -> None:
        file_name, _ = QFileDialog.getSaveFileName(
            self, "Xuất ngân hàng câu hỏi", "questions.csv", "CSV files (*.csv)"
        )
        if not file_name:
            return
        output = Path(file_name)
        if output.suffix.lower() != ".csv":
            output = output.with_suffix(".csv")
        self._export_path = output
        self._export_rows = []
        self._export_offset = 0
        self._request_export_page()

    def _request_export_page(self) -> None:
        request_id = self.service.list_questions(
            query=self.query.text().strip(),
            topic=self.topic.text().strip(),
            difficulty=str(self.difficulty.currentData()),
            include_inactive=self.include_inactive.isChecked(),
            limit=20,
            offset=self._export_offset,
        )
        self._pending[request_id] = "export"
        self.notice.setText("Đang lấy dữ liệu để xuất CSV…")

    def _write_export_csv(self) -> None:
        if self._export_path is None:
            return
        fields = [
            "content", "topic", "difficulty", "option_a", "option_b", "option_c", "option_d",
            "correct_option_index", "explanation", "is_active",
        ]
        try:
            with self._export_path.open("w", encoding="utf-8-sig", newline="") as destination:
                writer = csv.DictWriter(destination, fieldnames=fields)
                writer.writeheader()
                for question in self._export_rows:
                    raw_options = question.get("options")
                    options = raw_options if isinstance(raw_options, list) else []
                    option_contents = [
                        str(option.get("content", "")) if isinstance(option, dict) else str(option)
                        for option in options
                    ]
                    option_contents.extend([""] * (4 - len(option_contents)))
                    writer.writerow({
                        "content": question.get("content", ""),
                        "topic": question.get("topic", ""),
                        "difficulty": question.get("difficulty", ""),
                        "option_a": option_contents[0],
                        "option_b": option_contents[1],
                        "option_c": option_contents[2],
                        "option_d": option_contents[3],
                        "correct_option_index": question.get("correct_option_index", 0),
                        "explanation": question.get("explanation", ""),
                        "is_active": 1 if question.get("is_active") else 0,
                    })
        except OSError as error:
            QMessageBox.warning(self, "Không thể xuất CSV", str(error))
            return
        self.notice.setText(f"Đã xuất {len(self._export_rows)} câu hỏi vào {self._export_path.name}.")
        show_toast(self, "Đã xuất CSV thành công.")
        self._export_path = None
        self._export_rows = []

    def _render(self) -> None:
        self.table.setRowCount(len(self.questions))
        for row, question in enumerate(self.questions):
            content = str(question.get("content", ""))
            values = [
                str(question.get("id", "")),
                content[:90] + ("…" if len(content) > 90 else ""),
                str(question.get("topic", "")),
                str(question.get("difficulty", "")),
                chr(65 + int(question.get("correct_option_index", 0))),
                "Hoạt động" if question.get("is_active") else "Đã disable",
            ]
            for column, value in enumerate(values):
                self.table.setItem(row, column, QTableWidgetItem(value))
            actions = QToolButton()
            actions.setText("⋯")
            menu = QMenu(actions)
            edit = menu.addAction("Sửa câu hỏi")
            edit.triggered.connect(lambda _checked=False, item=question: self._edit(item))
            status = menu.addAction("Disable" if question.get("is_active") else "Enable")
            status.triggered.connect(lambda _checked=False, item=question: self._toggle_active(item))
            actions.setMenu(menu)
            actions.setPopupMode(QToolButton.InstantPopup)
            self.table.setCellWidget(row, 6, actions)
        self.table.resizeColumnsToContents()
        self.table.setColumnWidth(1, 430)
        self.previous.setEnabled(self.offset > 0)
        self.next.setEnabled(self._has_more)

    def _on_success(self, request_id: str, response: object) -> None:
        action = self._pending.pop(request_id, None)
        if action is None:
            return
        if action == "list":
            try:
                data = _response_data(response)
                raw_questions = data.get("questions")
                if not isinstance(raw_questions, list) or not all(isinstance(item, dict) for item in raw_questions):
                    raise ValueError("Server returned invalid question data")
                self.questions = raw_questions
                self._has_more = bool(data.get("has_more"))
                self.notice.setText(f"Hiển thị {len(self.questions)} câu hỏi · trang từ vị trí {self.offset + 1}")
                self._render()
            except ValueError as error:
                self.notice.setText(str(error))
            return
        if action == "export":
            try:
                data = _response_data(response)
                raw_questions = data.get("questions")
                if not isinstance(raw_questions, list) or not all(isinstance(item, dict) for item in raw_questions):
                    raise ValueError("Server returned invalid question data")
                self._export_rows.extend(raw_questions)
                if bool(data.get("has_more")):
                    self._export_offset += len(raw_questions)
                    self._request_export_page()
                else:
                    self._write_export_csv()
            except ValueError as error:
                self.notice.setText(str(error))
            return
        messages = {
            "create": "Đã tạo câu hỏi.",
            "update": "Đã cập nhật câu hỏi.",
            "disable": "Đã disable câu hỏi.",
            "enable": "Đã enable câu hỏi.",
            "import": "Đã import câu hỏi.",
            "import_csv": "Đã import câu hỏi từ CSV.",
        }
        message = messages.get(action, "Đã hoàn tất.")
        self.notice.setText(message)
        show_toast(self, message)
        self.refresh()

    def _on_failure(self, request_id: str, message: str) -> None:
        if self._pending.pop(request_id, None) is not None:
            self.notice.setText(f"Không thể hoàn tất: {message}")
            QMessageBox.warning(self, "Yêu cầu thất bại", message)


class PhaseOneMainWindow(QMainWindow):
    """Legacy compact window for the shared server-backed surfaces."""

    def __init__(self, service: PhaseOneApiService) -> None:
        super().__init__()
        self.service = service
        self.user: LiveUser | None = None
        self.setWindowTitle(APP_TITLE)
        self.setMinimumSize(WINDOW_MIN_WIDTH, WINDOW_MIN_HEIGHT)
        self.resize(1180, 760)
        self.root = QStackedWidget()
        self.root.setObjectName("root")
        self.setCentralWidget(self.root)
        self.auth = LiveAuthPage(service)
        self.auth.authenticated.connect(self._on_authenticated)
        self.root.addWidget(self.auth)

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
        self.pages = QStackedWidget()
        self.dashboard = LiveDashboardPage(self.service, user)
        self.dashboard.open_questions.connect(self.show_questions)
        self.dashboard.logged_out.connect(self._on_logged_out)
        self.pages.addWidget(self.dashboard)
        self.question_bank: QuestionBankPage | None = None
        if user.role == "ADMIN":
            self.question_bank = QuestionBankPage(self.service)
            self.question_bank.back_to_dashboard.connect(self.show_dashboard)
            self.pages.addWidget(self.question_bank)
        main_layout.addWidget(self._topbar(user))
        main_layout.addWidget(self.pages, 1)
        layout.addWidget(main, 1)
        self.root.addWidget(workspace)
        self.root.setCurrentWidget(workspace)
        self.show_dashboard()

    def _sidebar(self, user: LiveUser) -> QFrame:
        sidebar = QFrame()
        sidebar.setObjectName("sidebar")
        sidebar.setFixedWidth(225)
        layout = QVBoxLayout(sidebar)
        layout.setContentsMargins(16, 20, 16, 16)
        brand = QLabel("◈  KuizuHub")
        brand.setObjectName("brand")
        layout.addWidget(brand)
        layout.addSpacing(24)
        identity = QLabel(f"@{user.username}\n{user.role}")
        identity.setObjectName("sideUser")
        layout.addWidget(identity)
        layout.addSpacing(16)
        self.dashboard_nav = QPushButton("⌂  Tổng quan")
        self.dashboard_nav.setObjectName("nav")
        self.dashboard_nav.setCheckable(True)
        self.dashboard_nav.clicked.connect(self.show_dashboard)
        layout.addWidget(self.dashboard_nav)
        self.questions_nav: QPushButton | None = None
        if user.role == "ADMIN":
            self.questions_nav = QPushButton("☷  Ngân hàng câu hỏi")
            self.questions_nav.setObjectName("nav")
            self.questions_nav.setCheckable(True)
            self.questions_nav.clicked.connect(self.show_questions)
            layout.addWidget(self.questions_nav)
        layout.addStretch()
        note = QLabel("Kết nối TCP thật")
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

    def show_dashboard(self) -> None:
        self.pages.setCurrentWidget(self.dashboard)
        self.page_title.setText("Tổng quan")
        self.dashboard_nav.setChecked(True)
        if self.questions_nav is not None:
            self.questions_nav.setChecked(False)

    def show_questions(self) -> None:
        if self.question_bank is None:
            return
        self.pages.setCurrentWidget(self.question_bank)
        self.question_bank.refresh()
        self.page_title.setText("Ngân hàng câu hỏi")
        self.dashboard_nav.setChecked(False)
        if self.questions_nav is not None:
            self.questions_nav.setChecked(True)

    def _on_logged_out(self) -> None:
        self.user = None
        self.root.setCurrentWidget(self.auth)
        self.auth.login_password.clear()

    def closeEvent(self, event: object) -> None:  # type: ignore[override]
        self.service.close()
        super().closeEvent(event)  # type: ignore[arg-type]
