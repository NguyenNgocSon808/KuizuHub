"""Focused two-column authentication experience."""

from __future__ import annotations

from PySide6.QtCore import QTimer, Signal, Qt
from PySide6.QtWidgets import (QCheckBox, QFormLayout, QFrame, QHBoxLayout, QLabel,
                               QLineEdit, QPushButton, QStackedWidget, QVBoxLayout, QWidget)

from ...services import MockApiService, ServiceError
from ..widgets import PrimaryButton, SecondaryButton


class AuthPage(QWidget):
    authenticated = Signal(object)

    def __init__(self, service: MockApiService) -> None:
        super().__init__()
        self.service = service
        self.stack = QStackedWidget()
        self.stack.addWidget(self._login_form())
        self.stack.addWidget(self._register_form())
        outer = QHBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        outer.addWidget(self._brand_panel(), 5)
        form_area = QWidget()
        form_layout = QVBoxLayout(form_area)
        form_layout.setContentsMargins(76, 48, 76, 48)
        form_layout.addStretch()
        form_layout.addWidget(self.stack)
        form_layout.addStretch()
        outer.addWidget(form_area, 6)

    def _brand_panel(self) -> QFrame:
        panel = QFrame()
        panel.setStyleSheet("background:#0F2742;")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(58, 52, 58, 52)
        top = QHBoxLayout()
        mark = QLabel("K")
        mark.setAlignment(Qt.AlignCenter)
        mark.setFixedSize(38, 38)
        mark.setStyleSheet("background:#2563EB;color:white;border-radius:10px;font-size:18px;font-weight:700;")
        top.addWidget(mark)
        title = QLabel("Online Exam")
        title.setStyleSheet("color:white;font-size:21px;font-weight:700;")
        top.addWidget(title)
        top.addStretch()
        layout.addLayout(top)
        layout.addStretch()
        illustration = QFrame()
        illustration.setStyleSheet("background:#183958;border:1px solid #315475;border-radius:18px;")
        art = QVBoxLayout(illustration)
        art.setContentsMargins(24, 24, 24, 24)
        icon = QLabel("✦")
        icon.setAlignment(Qt.AlignCenter)
        icon.setStyleSheet("color:#93C5FD;font-size:58px;")
        art.addWidget(icon)
        illustration_title = QLabel("Học chủ động\nThi tự tin")
        illustration_title.setAlignment(Qt.AlignCenter)
        illustration_title.setStyleSheet("color:white;font-size:26px;font-weight:700;")
        art.addWidget(illustration_title)
        caption = QLabel("Một không gian gọn gàng để luyện tập,\ntheo dõi tiến độ và sẵn sàng cho bài thi.")
        caption.setAlignment(Qt.AlignCenter)
        caption.setStyleSheet("color:#BFD4EA;font-size:14px;")
        art.addWidget(caption)
        layout.addWidget(illustration)
        layout.addSpacing(22)
        value = QLabel("✓  Làm bài theo tiến độ của bạn\n✓  Phòng thi tập trung, rõ ràng\n✓  Thống kê dễ hiểu sau mỗi lần làm bài")
        value.setStyleSheet("color:#D7E5F3;line-height:1.8;")
        layout.addWidget(value)
        layout.addStretch()
        layout.addWidget(QLabel("KuizuHub · Mock desktop demo", objectName="caption"))
        return panel

    def _form_shell(self, title: str, description: str) -> tuple[QFrame, QVBoxLayout]:
        frame = QFrame()
        frame.setObjectName("sectionCard")
        frame.setMaximumWidth(470)
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(28, 28, 28, 28)
        layout.setSpacing(12)
        heading = QLabel(title)
        heading.setObjectName("pageTitle")
        layout.addWidget(heading)
        detail = QLabel(description)
        detail.setObjectName("subtle")
        detail.setWordWrap(True)
        layout.addWidget(detail)
        layout.addSpacing(8)
        return frame, layout

    @staticmethod
    def _error_label() -> QLabel:
        label = QLabel()
        label.setStyleSheet("color:#DC2626;font-size:12px;")
        label.setWordWrap(True)
        return label

    def _login_form(self) -> QWidget:
        frame, layout = self._form_shell("Chào mừng trở lại", "Đăng nhập để tiếp tục hành trình học tập của bạn.")
        form = QFormLayout()
        form.setSpacing(8)
        self.username = QLineEdit()
        self.username.setPlaceholderText("◉  Username, ví dụ: bao")
        self.username.setClearButtonEnabled(True)
        self.password = QLineEdit()
        self.password.setPlaceholderText("⌑  Mật khẩu")
        self.password.setEchoMode(QLineEdit.Password)
        self.username_error = self._error_label()
        self.password_error = self._error_label()
        form.addRow("Username", self.username)
        form.addRow("", self.username_error)
        form.addRow("Mật khẩu", self.password)
        form.addRow("", self.password_error)
        layout.addLayout(form)
        remember_row = QHBoxLayout()
        remember_row.addWidget(QCheckBox("Ghi nhớ đăng nhập"))
        remember_row.addStretch()
        layout.addLayout(remember_row)
        self.login_button = PrimaryButton("Đăng nhập")
        self.login_button.setDefault(True)
        self.login_button.clicked.connect(self._login)
        self.password.returnPressed.connect(self._login)
        layout.addWidget(self.login_button)
        demo = QFrame()
        demo.setStyleSheet("background:#EFF6FF;border:1px solid #BFDBFE;border-radius:8px;")
        demo_layout = QVBoxLayout(demo)
        demo_layout.setContentsMargins(12, 10, 12, 10)
        demo_layout.addWidget(QLabel("Tài khoản demo", objectName="sectionTitle"))
        accounts = QLabel("Chủ phòng:  son / 123456\nThí sinh:  bao / 123456  ·  vuong / 123456")
        accounts.setStyleSheet("color:#1E3A8A;font-size:12px;")
        demo_layout.addWidget(accounts)
        layout.addWidget(demo)
        switch = SecondaryButton("Chưa có tài khoản?  Đăng ký")
        switch.clicked.connect(lambda: self.stack.setCurrentIndex(1))
        layout.addWidget(switch)
        return frame

    def _register_form(self) -> QWidget:
        frame, layout = self._form_shell("Tạo tài khoản", "Tài khoản mới sẽ được tạo với vai trò thí sinh.")
        form = QFormLayout()
        form.setSpacing(8)
        self.full_name = QLineEdit(); self.full_name.setPlaceholderText("Họ và tên")
        self.reg_username = QLineEdit(); self.reg_username.setPlaceholderText("Ít nhất 3 ký tự")
        self.email = QLineEdit(); self.email.setPlaceholderText("name@email.com")
        self.reg_password = QLineEdit(); self.reg_password.setPlaceholderText("Ít nhất 6 ký tự"); self.reg_password.setEchoMode(QLineEdit.Password)
        self.confirm = QLineEdit(); self.confirm.setPlaceholderText("Nhập lại mật khẩu"); self.confirm.setEchoMode(QLineEdit.Password)
        for label, field in [("Họ tên", self.full_name), ("Username", self.reg_username), ("Email", self.email), ("Mật khẩu", self.reg_password), ("Xác nhận", self.confirm)]:
            form.addRow(label, field)
        layout.addLayout(form)
        self.register_error = self._error_label()
        layout.addWidget(self.register_error)
        register = PrimaryButton("Tạo tài khoản")
        register.clicked.connect(self._register)
        self.confirm.returnPressed.connect(self._register)
        layout.addWidget(register)
        back = SecondaryButton("← Quay về đăng nhập")
        back.clicked.connect(lambda: self.stack.setCurrentIndex(0))
        layout.addWidget(back)
        return frame

    def _login(self) -> None:
        self.username_error.clear()
        self.password_error.clear()
        if not self.username.text().strip():
            self.username_error.setText("Hãy nhập username.")
            return
        if not self.password.text():
            self.password_error.setText("Hãy nhập mật khẩu.")
            return
        self.login_button.setEnabled(False)
        self.login_button.setText("Đang đăng nhập…")

        def complete_login() -> None:
            try:
                self.authenticated.emit(self.service.login(self.username.text(), self.password.text()))
            except ServiceError as error:
                self.password_error.setText(str(error))
            finally:
                self.login_button.setEnabled(True)
                self.login_button.setText("Đăng nhập")

        QTimer.singleShot(260, complete_login)

    def _register(self) -> None:
        try:
            self.service.register(self.full_name.text(), self.reg_username.text(), self.email.text(), self.reg_password.text(), self.confirm.text())
            self.stack.setCurrentIndex(0)
            self.username.setText(self.reg_username.text())
            self.password.clear()
            self.username_error.setStyleSheet("color:#16A34A;font-size:12px;")
            self.username_error.setText("Đăng ký thành công. Hãy đăng nhập để bắt đầu.")
            self.register_error.clear()
        except ServiceError as error:
            self.register_error.setText(str(error))
