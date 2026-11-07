from PySide6.QtCore import Signal, Qt
from PySide6.QtWidgets import (QCheckBox, QFormLayout, QFrame, QHBoxLayout, QLabel,
                               QLineEdit, QPushButton, QStackedWidget, QVBoxLayout, QWidget)

from ...services import MockApiService, ServiceError


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
        hero = QFrame()
        hero.setStyleSheet("background:#102a43;")
        hero_layout = QVBoxLayout(hero)
        hero_layout.setContentsMargins(60, 70, 45, 60)
        hero_layout.addStretch()
        brand = QLabel("KuizuHub")
        brand.setStyleSheet("color:white;font-size:38px;font-weight:700;")
        hero_layout.addWidget(brand)
        copy = QLabel("Nền tảng thi trắc nghiệm\ncho lớp học kết nối.")
        copy.setStyleSheet("color:#cbdced;font-size:18px;")
        hero_layout.addWidget(copy)
        hero_layout.addSpacing(25)
        note = QLabel("✓ Làm bài theo thời gian thực\n✓ Luyện tập và xem tiến độ\n✓ Quản lý phòng thi tập trung")
        note.setStyleSheet("color:#e8f1fe; line-height:1.7;")
        hero_layout.addWidget(note)
        hero_layout.addStretch()
        outer.addWidget(hero, 4)
        form_area = QWidget()
        form_layout = QVBoxLayout(form_area)
        form_layout.setContentsMargins(70, 55, 70, 55)
        form_layout.addStretch()
        form_layout.addWidget(self.stack)
        form_layout.addStretch()
        outer.addWidget(form_area, 5)

    def _form_shell(self, title: str, description: str) -> tuple[QFrame, QVBoxLayout]:
        frame = QFrame()
        frame.setObjectName("card")
        layout = QVBoxLayout(frame)
        layout.setSpacing(12)
        heading = QLabel(title)
        heading.setStyleSheet("font-size:25px;font-weight:700;color:#102a43;")
        layout.addWidget(heading)
        detail = QLabel(description)
        detail.setObjectName("subtle")
        detail.setWordWrap(True)
        layout.addWidget(detail)
        return frame, layout

    def _login_form(self) -> QWidget:
        frame, layout = self._form_shell("Chào mừng trở lại", "Đăng nhập để tiếp tục hành trình học tập của bạn.")
        form = QFormLayout()
        self.username = QLineEdit()
        self.username.setPlaceholderText("Ví dụ: bao")
        self.password = QLineEdit()
        self.password.setEchoMode(QLineEdit.Password)
        self.password.setPlaceholderText("Mật khẩu")
        form.addRow("Username", self.username)
        form.addRow("Mật khẩu", self.password)
        layout.addLayout(form)
        remember = QCheckBox("Ghi nhớ đăng nhập")
        layout.addWidget(remember)
        self.login_error = QLabel()
        self.login_error.setStyleSheet("color:#b42318;")
        layout.addWidget(self.login_error)
        login = QPushButton("Đăng nhập")
        login.clicked.connect(self._login)
        layout.addWidget(login)
        demo = QLabel("Tài khoản demo\nHost: son / 123456\nStudent: bao / 123456 hoặc vuong / 123456")
        demo.setStyleSheet("background:#edf5ff;border-radius:8px;padding:10px;color:#245078;")
        layout.addWidget(demo)
        switch = QPushButton("Chưa có tài khoản? Đăng ký")
        switch.setObjectName("secondary")
        switch.clicked.connect(lambda: self.stack.setCurrentIndex(1))
        layout.addWidget(switch)
        return frame

    def _register_form(self) -> QWidget:
        frame, layout = self._form_shell("Tạo tài khoản", "Tài khoản mới sẽ được tạo ở vai trò thí sinh.")
        form = QFormLayout()
        self.full_name = QLineEdit(); self.full_name.setPlaceholderText("Họ và tên")
        self.reg_username = QLineEdit(); self.reg_username.setPlaceholderText("Ít nhất 3 ký tự")
        self.email = QLineEdit(); self.email.setPlaceholderText("name@email.com")
        self.reg_password = QLineEdit(); self.reg_password.setEchoMode(QLineEdit.Password)
        self.confirm = QLineEdit(); self.confirm.setEchoMode(QLineEdit.Password)
        for label, field in [("Họ tên", self.full_name), ("Username", self.reg_username), ("Email", self.email), ("Mật khẩu", self.reg_password), ("Xác nhận", self.confirm)]:
            form.addRow(label, field)
        layout.addLayout(form)
        self.register_error = QLabel(); self.register_error.setStyleSheet("color:#b42318;")
        layout.addWidget(self.register_error)
        register = QPushButton("Đăng ký")
        register.clicked.connect(self._register)
        layout.addWidget(register)
        back = QPushButton("← Quay về đăng nhập")
        back.setObjectName("secondary")
        back.clicked.connect(lambda: self.stack.setCurrentIndex(0))
        layout.addWidget(back)
        return frame

    def _login(self) -> None:
        try:
            self.authenticated.emit(self.service.login(self.username.text(), self.password.text()))
            self.login_error.clear()
        except ServiceError as error:
            self.login_error.setText(str(error))

    def _register(self) -> None:
        try:
            self.service.register(self.full_name.text(), self.reg_username.text(), self.email.text(), self.reg_password.text(), self.confirm.text())
            self.stack.setCurrentIndex(0)
            self.username.setText(self.reg_username.text())
            self.password.clear()
            self.login_error.setStyleSheet("color:#18794e;")
            self.login_error.setText("Đăng ký thành công. Hãy đăng nhập.")
        except ServiceError as error:
            self.register_error.setText(str(error))
