"""Consistent administrative, analytics and profile pages."""

from __future__ import annotations

from collections import defaultdict

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (QComboBox, QDialog, QDialogButtonBox, QFormLayout, QFrame, QHBoxLayout,
                               QLabel, QLineEdit, QMenu, QMessageBox, QPushButton, QScrollArea,
                               QTableWidget, QTableWidgetItem, QTextEdit, QToolButton, QVBoxLayout, QWidget)

from ...config import DIFFICULTIES, TOPICS
from ...models import Question, User
from ...services import MockApiService, ServiceError
from ..widgets import (ChartCanvas, DangerButton, EmptyStateWidget, PageHeader, PrimaryButton,
                       ScoreBadge, SearchInput, SecondaryButton, SectionCard, UserAvatar,
                       show_toast)


def _message(parent: QWidget, title: str, detail: str, error: bool = False) -> None:
    (QMessageBox.warning if error else QMessageBox.information)(parent, title, detail)


class QuestionDialog(QDialog):
    def __init__(self, question: Question | None = None, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.question = question
        self.setWindowTitle("Sửa câu hỏi" if question else "Thêm câu hỏi")
        self.resize(610, 570)
        layout = QVBoxLayout(self)
        layout.setSpacing(12)
        heading = QLabel("Cập nhật nội dung câu hỏi")
        heading.setObjectName("pageTitle")
        layout.addWidget(heading)
        form = QFormLayout()
        form.setSpacing(10)
        self.content = QTextEdit()
        self.content.setFixedHeight(70)
        self.options = [QLineEdit() for _ in range(4)]
        self.correct = QComboBox(); self.correct.addItems(["A", "B", "C", "D"])
        self.topic = QComboBox(); self.topic.addItems(TOPICS[1:])
        self.difficulty = QComboBox(); self.difficulty.addItems(DIFFICULTIES[1:4])
        self.explanation = QTextEdit(); self.explanation.setFixedHeight(62)
        form.addRow("Nội dung *", self.content)
        for index, field in enumerate(self.options):
            field.setPlaceholderText(f"Nội dung đáp án {chr(65 + index)}")
            form.addRow(f"Đáp án {chr(65 + index)} *", field)
        form.addRow("Đáp án đúng", self.correct)
        form.addRow("Chủ đề", self.topic)
        form.addRow("Độ khó", self.difficulty)
        form.addRow("Giải thích", self.explanation)
        layout.addLayout(form)
        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Save).setText("Lưu câu hỏi")
        buttons.button(QDialogButtonBox.Cancel).setText("Hủy")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        if question:
            self.content.setPlainText(question.content)
            for field, option in zip(self.options, question.options):
                field.setText(option)
            self.correct.setCurrentIndex(question.correct_index)
            self.topic.setCurrentText(question.topic)
            self.difficulty.setCurrentText(question.difficulty)
            self.explanation.setPlainText(question.explanation)

    def data(self) -> dict:
        return {"content": self.content.toPlainText(), "options": [field.text() for field in self.options],
                "correct_index": self.correct.currentIndex(), "topic": self.topic.currentText(),
                "difficulty": self.difficulty.currentText(), "explanation": self.explanation.toPlainText()}


class QuestionBankPage(QWidget):
    def __init__(self, service: MockApiService, user: User) -> None:
        super().__init__()
        self.service, self.user = service, user
        root = QVBoxLayout(self)
        root.setContentsMargins(4, 4, 4, 4)
        header = QHBoxLayout()
        header.addWidget(PageHeader("Ngân hàng câu hỏi", "Quản lý nội dung mock/local JSON dành cho các phòng thi."), 1)
        add = PrimaryButton("＋  Thêm câu hỏi")
        add.clicked.connect(self._add)
        header.addWidget(add, alignment=Qt.AlignTop)
        root.addLayout(header)
        filters = QFrame()
        filters.setObjectName("sectionCard")
        filter_layout = QHBoxLayout(filters)
        filter_layout.setContentsMargins(12, 10, 12, 10)
        self.search = SearchInput("Tìm theo nội dung câu hỏi")
        self.search.textChanged.connect(self.refresh)
        self.topic = QComboBox(); self.topic.addItems(TOPICS); self.topic.currentTextChanged.connect(self.refresh)
        self.difficulty = QComboBox(); self.difficulty.addItems(DIFFICULTIES[:4]); self.difficulty.currentTextChanged.connect(self.refresh)
        filter_layout.addWidget(self.search, 4)
        filter_layout.addWidget(self.topic)
        filter_layout.addWidget(self.difficulty)
        root.addWidget(filters)
        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels(["ID", "Nội dung", "Chủ đề", "Độ khó", "Đáp án đúng", ""])
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setStretchLastSection(True)
        root.addWidget(self.table, 1)
        self.empty = EmptyStateWidget("Chưa có câu hỏi phù hợp", "Hãy thay đổi bộ lọc hoặc thêm một câu hỏi mới.")
        self.empty.hide()
        root.addWidget(self.empty)
        self.refresh()

    def refresh(self) -> None:
        questions = self.service.get_questions(self.search.text(), self.topic.currentText(), self.difficulty.currentText())
        self.table.setVisible(bool(questions))
        self.empty.setVisible(not questions)
        self.table.setRowCount(len(questions))
        for row, question in enumerate(questions):
            values = [str(question.id), question.content[:80] + ("…" if len(question.content) > 80 else ""), question.topic, question.difficulty, chr(65 + question.correct_index)]
            for column, value in enumerate(values):
                self.table.setItem(row, column, QTableWidgetItem(value))
            action = QToolButton()
            action.setText("⋯")
            action.setToolTip("Thao tác với câu hỏi")
            menu = QMenu(action)
            edit = menu.addAction("Sửa câu hỏi")
            edit.triggered.connect(lambda _=False, item=question: self._edit(item))
            remove = menu.addAction("Xóa câu hỏi")
            remove.triggered.connect(lambda _=False, item=question: self._delete(item))
            action.setMenu(menu)
            action.setPopupMode(QToolButton.InstantPopup)
            self.table.setCellWidget(row, 5, action)
        self.table.resizeColumnsToContents()
        self.table.setColumnWidth(1, 390)

    def _add(self) -> None:
        dialog = QuestionDialog(parent=self)
        if dialog.exec() == QDialog.Accepted:
            try:
                self.service.save_question(dialog.data())
                self.refresh()
                show_toast(self, "Đã thêm câu hỏi vào ngân hàng.")
            except ServiceError as error:
                _message(self, "Không thể lưu", str(error), True)

    def _edit(self, question: Question) -> None:
        dialog = QuestionDialog(question, self)
        if dialog.exec() == QDialog.Accepted:
            try:
                self.service.save_question(dialog.data(), question.id)
                self.refresh()
                show_toast(self, "Đã cập nhật câu hỏi.")
            except ServiceError as error:
                _message(self, "Không thể lưu", str(error), True)

    def _delete(self, question: Question) -> None:
        if QMessageBox.question(self, "Xóa câu hỏi", f"Bạn có chắc muốn xóa câu hỏi #{question.id}?", QMessageBox.Yes | QMessageBox.No) == QMessageBox.Yes:
            try:
                self.service.delete_question(question.id)
                self.refresh()
                show_toast(self, "Đã xóa câu hỏi.", "warning")
            except ServiceError as error:
                _message(self, "Không thể xóa", str(error), True)


class HistoryPage(QWidget):
    def __init__(self, service: MockApiService, user: User) -> None:
        super().__init__()
        self.service, self.user = service, user
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        body = QWidget()
        self.root = QVBoxLayout(body)
        self.root.setContentsMargins(4, 4, 4, 20)
        self.root.setSpacing(14)
        scroll.setWidget(body)
        outer.addWidget(scroll)
        self._build()
        self.refresh()

    def _build(self) -> None:
        self.root.addWidget(PageHeader("Lịch sử & thống kê", "Xem quá trình học và nhận gợi ý cho chủ đề cần cải thiện."))
        filter_card = QFrame()
        filter_card.setObjectName("sectionCard")
        filters = QHBoxLayout(filter_card)
        filters.setContentsMargins(12, 10, 12, 10)
        filters.addWidget(QLabel("Bộ lọc", objectName="sectionTitle"))
        self.topic = QComboBox(); self.topic.addItems(TOPICS); self.topic.currentTextChanged.connect(self.refresh)
        self.kind = QComboBox(); self.kind.addItems(["Tất cả", "Thi phòng", "Luyện tập"]); self.kind.currentTextChanged.connect(self.refresh)
        self.score = QComboBox(); self.score.addItems(["Mọi mức điểm", "Dưới 5", "5 đến 8", "Từ 8 trở lên"]); self.score.currentTextChanged.connect(self.refresh)
        filters.addWidget(self.topic); filters.addWidget(self.kind); filters.addWidget(self.score); filters.addStretch()
        self.root.addWidget(filter_card)
        history_card = SectionCard("Lịch sử bài làm", "Điểm số được tô màu để bạn nhận diện nhanh mức độ hoàn thành.")
        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels(["Tên bài", "Loại", "Chủ đề", "Điểm", "Đúng", "Ngày làm"])
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setStretchLastSection(True)
        history_card.layout.addWidget(self.table)
        self.root.addWidget(history_card)
        charts = QHBoxLayout()
        self.line, self.bar, self.pie = ChartCanvas(4, 2.4), ChartCanvas(4, 2.4), ChartCanvas(3.2, 2.4)
        for title, subtitle, chart in [("Điểm theo thời gian", "Xu hướng các bài làm gần đây", self.line), ("Điểm TB theo chủ đề", "So sánh kiến thức theo từng mảng", self.bar), ("Tỷ lệ đúng/sai", "Tổng hợp câu trả lời", self.pie)]:
            card = SectionCard(title, subtitle)
            card.layout.addWidget(chart)
            charts.addWidget(card)
        self.root.addLayout(charts)
        self.tip = QLabel()
        self.tip.setWordWrap(True)
        self.tip.setStyleSheet("background:#FEF3C7;color:#92400E;border:1px solid #FDE68A;border-radius:9px;padding:12px;")
        self.root.addWidget(self.tip)

    def refresh(self) -> None:
        attempts = self.service.history(self.user.id)
        if self.topic.currentText() != "Tất cả": attempts = [item for item in attempts if item.topic == self.topic.currentText()]
        if self.kind.currentText() != "Tất cả": attempts = [item for item in attempts if item.kind == self.kind.currentText()]
        if self.score.currentText() == "Dưới 5": attempts = [item for item in attempts if item.score < 5]
        elif self.score.currentText() == "5 đến 8": attempts = [item for item in attempts if 5 <= item.score < 8]
        elif self.score.currentText() == "Từ 8 trở lên": attempts = [item for item in attempts if item.score >= 8]
        self.table.setRowCount(len(attempts))
        for row, item in enumerate(attempts):
            for column, value in enumerate([item.title, item.kind, item.topic, "", f"{item.correct_count}/{item.total}", item.created_at]):
                self.table.setItem(row, column, QTableWidgetItem(value))
            self.table.setCellWidget(row, 3, ScoreBadge(item.score))
        self.table.resizeColumnsToContents()
        chronological = list(reversed(attempts))
        axis = self.line.axes()
        if chronological:
            axis.plot(range(1, len(chronological) + 1), [item.score for item in chronological], marker="o", color="#2563EB", linewidth=2.1)
            axis.fill_between(range(1, len(chronological) + 1), [item.score for item in chronological], alpha=.08, color="#2563EB")
        axis.set_ylim(0, 10.5); axis.set_ylabel("Điểm")
        grouped: dict[str, list[float]] = defaultdict(list)
        for item in attempts: grouped[item.topic].append(item.score)
        axis = self.bar.axes()
        labels = list(grouped) or ["Chưa có"]
        values = [sum(scores) / len(scores) for scores in grouped.values()] or [0]
        axis.bar(labels, values, color="#60A5FA", width=.55)
        axis.tick_params(axis="x", rotation=20)
        axis.set_ylim(0, 10.5)
        axis = self.pie.axes()
        correct, total = sum(item.correct_count for item in attempts), sum(item.total for item in attempts)
        axis.pie([correct or 1, max(total - correct, 0) or 1], labels=["Đúng", "Sai"], colors=["#16A34A", "#FCA5A5"], autopct="%1.0f%%", wedgeprops={"width": .45})
        weak = min(grouped, key=lambda topic: sum(grouped[topic]) / len(grouped[topic])) if grouped else "TCP Socket"
        self.tip.setText(f"Điểm cần cải thiện · Chủ đề {weak} đang có điểm trung bình thấp nhất. Hãy tạo một bài luyện tập ngắn để củng cố kiến thức.")


class ProfilePage(QWidget):
    logged_out = Signal()

    def __init__(self, service: MockApiService, user: User) -> None:
        super().__init__()
        self.service, self.user = service, user
        self.root = QVBoxLayout(self)
        self.root.setContentsMargins(4, 4, 4, 4)
        self.root.setSpacing(14)
        self.refresh()

    def refresh(self) -> None:
        while self.root.count():
            item = self.root.takeAt(0)
            if item.widget(): item.widget().deleteLater()
        self.root.addWidget(PageHeader("Hồ sơ cá nhân", "Quản lý thông tin tài khoản và phiên dữ liệu demo."))
        profile_hero = QFrame()
        profile_hero.setObjectName("heroCard")
        hero_layout = QHBoxLayout(profile_hero)
        hero_layout.setContentsMargins(20, 18, 20, 18)
        hero_layout.addWidget(UserAvatar(self.user.full_name, 68))
        copy = QVBoxLayout()
        name = QLabel(self.user.full_name)
        name.setObjectName("pageTitle")
        copy.addWidget(name)
        copy.addWidget(QLabel(f"@{self.user.username}  ·  {'Chủ phòng' if self.user.role == 'HOST' else 'Thí sinh'}  ·  Tham gia {self.user.joined_at}", objectName="subtle"))
        hero_layout.addLayout(copy, 1)
        self.root.addWidget(profile_hero)
        columns = QHBoxLayout()
        columns.setSpacing(16)
        columns.addWidget(self._details(), 6)
        columns.addWidget(self._actions(), 4)
        self.root.addLayout(columns)
        self.root.addStretch()

    def _details(self) -> SectionCard:
        card = SectionCard("Thông tin cá nhân", "Các thay đổi sẽ được lưu vào mock_state.json của bản demo.")
        form = QFormLayout()
        form.setSpacing(12)
        self.name = QLineEdit(self.user.full_name)
        self.email = QLineEdit(self.user.email)
        form.addRow("Họ và tên", self.name)
        form.addRow("Username", QLabel(self.user.username))
        form.addRow("Email", self.email)
        form.addRow("Vai trò", QLabel("Chủ phòng" if self.user.role == "HOST" else "Thí sinh"))
        form.addRow("Ngày tham gia", QLabel(self.user.joined_at))
        card.layout.addLayout(form)
        save = PrimaryButton("Lưu thay đổi")
        save.clicked.connect(self._save)
        card.layout.addWidget(save)
        return card

    def _actions(self) -> SectionCard:
        card = SectionCard("Cài đặt tài khoản", "Các thao tác dưới đây chỉ áp dụng cho dữ liệu mock cục bộ.")
        change = SecondaryButton("Đổi mật khẩu mock")
        change.clicked.connect(self._password)
        reset = SecondaryButton("Khôi phục dữ liệu demo")
        reset.clicked.connect(self._reset)
        logout = DangerButton("Đăng xuất", outline=True)
        logout.clicked.connect(self._logout)
        card.layout.addWidget(change)
        card.layout.addWidget(reset)
        card.layout.addStretch()
        card.layout.addWidget(logout)
        return card

    def _save(self) -> None:
        try:
            self.user = self.service.update_profile(self.user.id, self.name.text(), self.email.text())
            show_toast(self, "Đã lưu thông tin cá nhân.")
            self.refresh()
        except ServiceError as error:
            _message(self, "Không thể cập nhật", str(error), True)

    def _password(self) -> None:
        dialog = QDialog(self)
        dialog.setWindowTitle("Đổi mật khẩu mock")
        form = QFormLayout(dialog)
        current, new = QLineEdit(), QLineEdit()
        current.setEchoMode(QLineEdit.Password); new.setEchoMode(QLineEdit.Password)
        form.addRow("Mật khẩu hiện tại", current)
        form.addRow("Mật khẩu mới", new)
        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        form.addRow(buttons)
        buttons.rejected.connect(dialog.reject); buttons.accepted.connect(dialog.accept)
        if dialog.exec() == QDialog.Accepted:
            try:
                self.service.change_password(self.user.id, current.text(), new.text())
                show_toast(self, "Đã đổi mật khẩu mock.")
            except ServiceError as error:
                _message(self, "Không thể đổi mật khẩu", str(error), True)

    def _reset(self) -> None:
        if QMessageBox.question(self, "Khôi phục dữ liệu", "Mọi thay đổi mock trong phiên demo sẽ bị xóa.", QMessageBox.Yes | QMessageBox.No) == QMessageBox.Yes:
            self.service.reset_demo()
            self.logged_out.emit()

    def _logout(self) -> None:
        if QMessageBox.question(self, "Đăng xuất", "Bạn có chắc muốn đăng xuất?", QMessageBox.Yes | QMessageBox.No) == QMessageBox.Yes:
            self.logged_out.emit()
