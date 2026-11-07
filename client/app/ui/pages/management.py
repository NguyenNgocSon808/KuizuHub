from __future__ import annotations

from collections import defaultdict

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (QComboBox, QDialog, QDialogButtonBox, QFormLayout, QFrame, QHBoxLayout, QLabel,
                               QLineEdit, QMessageBox, QPushButton, QScrollArea, QTableWidget, QTableWidgetItem,
                               QTextEdit, QVBoxLayout, QWidget)

from ...config import DIFFICULTIES, TOPICS
from ...models import Question, User
from ...services import MockApiService, ServiceError
from ..widgets import ChartCanvas, MetricCard, PageHeader


def _message(parent: QWidget, title: str, body: str, error: bool = False) -> None:
    (QMessageBox.warning if error else QMessageBox.information)(parent, title, body)


class QuestionDialog(QDialog):
    def __init__(self, service: MockApiService, question: Question | None = None, parent: QWidget | None = None) -> None:
        super().__init__(parent); self.service, self.question = service, question
        self.setWindowTitle("Sửa câu hỏi" if question else "Thêm câu hỏi"); self.resize(560, 520)
        layout = QVBoxLayout(self); form = QFormLayout()
        self.content = QTextEdit(); self.content.setFixedHeight(72)
        self.options = [QLineEdit() for _ in range(4)]
        self.correct = QComboBox(); self.correct.addItems(["A", "B", "C", "D"])
        self.topic = QComboBox(); self.topic.addItems(TOPICS[1:])
        self.difficulty = QComboBox(); self.difficulty.addItems(DIFFICULTIES[1:3])
        self.explanation = QTextEdit(); self.explanation.setFixedHeight(60)
        form.addRow("Nội dung", self.content)
        for index, field in enumerate(self.options): form.addRow(f"Đáp án {chr(65 + index)}", field)
        form.addRow("Đáp án đúng", self.correct); form.addRow("Chủ đề", self.topic); form.addRow("Độ khó", self.difficulty); form.addRow("Giải thích", self.explanation)
        layout.addLayout(form)
        controls = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel); controls.accepted.connect(self.accept); controls.rejected.connect(self.reject); layout.addWidget(controls)
        if question:
            self.content.setPlainText(question.content)
            for field, value in zip(self.options, question.options): field.setText(value)
            self.correct.setCurrentIndex(question.correct_index); self.topic.setCurrentText(question.topic); self.difficulty.setCurrentText(question.difficulty); self.explanation.setPlainText(question.explanation)

    def data(self) -> dict:
        return {"content": self.content.toPlainText(), "options": [field.text() for field in self.options], "correct_index": self.correct.currentIndex(), "topic": self.topic.currentText(), "difficulty": self.difficulty.currentText(), "explanation": self.explanation.toPlainText()}


class QuestionBankPage(QWidget):
    def __init__(self, service: MockApiService, user: User) -> None:
        super().__init__(); self.service, self.user = service, user
        root = QVBoxLayout(self); root.setContentsMargins(6, 6, 6, 6); root.addWidget(PageHeader("Ngân hàng câu hỏi", "Dữ liệu được lưu mock/local JSON trong bản frontend này."))
        filters = QHBoxLayout(); self.search = QLineEdit(); self.search.setPlaceholderText("Tìm theo nội dung…"); self.search.textChanged.connect(self.refresh)
        self.topic = QComboBox(); self.topic.addItems(TOPICS); self.topic.currentTextChanged.connect(self.refresh)
        self.difficulty = QComboBox(); self.difficulty.addItems(DIFFICULTIES[:4]); self.difficulty.currentTextChanged.connect(self.refresh)
        add = QPushButton("+ Thêm câu hỏi"); add.clicked.connect(self._add)
        filters.addWidget(self.search, 4); filters.addWidget(self.topic); filters.addWidget(self.difficulty); filters.addWidget(add); root.addLayout(filters)
        self.table = QTableWidget(0, 6); self.table.setHorizontalHeaderLabels(["ID", "Nội dung", "Chủ đề", "Độ khó", "Đáp án đúng", "Thao tác"]); self.table.setEditTriggers(QTableWidget.NoEditTriggers); self.table.verticalHeader().setVisible(False); self.table.horizontalHeader().setStretchLastSection(True)
        root.addWidget(self.table, 1); self.refresh()

    def refresh(self) -> None:
        questions = self.service.get_questions(self.search.text(), self.topic.currentText(), self.difficulty.currentText())
        self.table.setRowCount(len(questions))
        for row, question in enumerate(questions):
            values = [str(question.id), question.content[:70] + ("…" if len(question.content) > 70 else ""), question.topic, question.difficulty, chr(65 + question.correct_index)]
            for col, value in enumerate(values): self.table.setItem(row, col, QTableWidgetItem(value))
            controls = QWidget(); actions = QHBoxLayout(controls); actions.setContentsMargins(2, 2, 2, 2)
            edit = QPushButton("Sửa"); edit.setObjectName("secondary"); edit.clicked.connect(lambda _=False, q=question: self._edit(q))
            remove = QPushButton("Xóa"); remove.setObjectName("danger"); remove.clicked.connect(lambda _=False, q=question: self._delete(q))
            actions.addWidget(edit); actions.addWidget(remove); self.table.setCellWidget(row, 5, controls)
        self.table.resizeColumnsToContents()

    def _add(self) -> None:
        dialog = QuestionDialog(self.service, parent=self)
        if dialog.exec() == QDialog.Accepted:
            try: self.service.save_question(dialog.data()); self.refresh()
            except ServiceError as error: _message(self, "Không thể lưu", str(error), True)

    def _edit(self, question: Question) -> None:
        dialog = QuestionDialog(self.service, question, self)
        if dialog.exec() == QDialog.Accepted:
            try: self.service.save_question(dialog.data(), question.id); self.refresh()
            except ServiceError as error: _message(self, "Không thể lưu", str(error), True)

    def _delete(self, question: Question) -> None:
        if QMessageBox.question(self, "Xóa câu hỏi", f"Xóa câu hỏi #{question.id}?", QMessageBox.Yes | QMessageBox.No) == QMessageBox.Yes:
            try: self.service.delete_question(question.id); self.refresh()
            except ServiceError as error: _message(self, "Không thể xóa", str(error), True)


class HistoryPage(QWidget):
    def __init__(self, service: MockApiService, user: User) -> None:
        super().__init__(); self.service, self.user = service, user
        root = QVBoxLayout(self); root.setContentsMargins(6, 6, 6, 6); root.addWidget(PageHeader("Lịch sử & thống kê", "Theo dõi tiến độ và nhận gợi ý luyện tập theo từng chủ đề."))
        filters = QHBoxLayout(); self.topic = QComboBox(); self.topic.addItems(TOPICS); self.topic.currentTextChanged.connect(self.refresh)
        self.kind = QComboBox(); self.kind.addItems(["Tất cả", "Thi phòng", "Luyện tập"]); self.kind.currentTextChanged.connect(self.refresh)
        self.score = QComboBox(); self.score.addItems(["Mọi mức điểm", "Dưới 5", "5 đến 8", "Từ 8 trở lên"]); self.score.currentTextChanged.connect(self.refresh)
        filters.addWidget(QLabel("Lọc:")); filters.addWidget(self.topic); filters.addWidget(self.kind); filters.addWidget(self.score); filters.addStretch(); root.addLayout(filters)
        self.table = QTableWidget(0, 6); self.table.setHorizontalHeaderLabels(["Tên bài", "Loại", "Chủ đề", "Điểm", "Đúng", "Ngày làm"]); self.table.setEditTriggers(QTableWidget.NoEditTriggers); self.table.horizontalHeader().setStretchLastSection(True); self.table.verticalHeader().setVisible(False); root.addWidget(self.table, 1)
        charts = QHBoxLayout(); self.line = ChartCanvas(4, 2.4); self.bar = ChartCanvas(4, 2.4); self.pie = ChartCanvas(3, 2.4)
        for title, chart in [("Điểm theo thời gian", self.line), ("Điểm TB theo chủ đề", self.bar), ("Tỷ lệ đúng/sai", self.pie)]:
            box = QFrame(); box.setObjectName("card"); inside = QVBoxLayout(box); heading = QLabel(title); heading.setStyleSheet("font-weight:700;"); inside.addWidget(heading); inside.addWidget(chart); charts.addWidget(box)
        root.addLayout(charts); self.tip = QLabel(); self.tip.setStyleSheet("background:#fff3cd;color:#8a5600;padding:10px;border-radius:7px;"); root.addWidget(self.tip); self.refresh()

    def refresh(self) -> None:
        attempts = self.service.history(self.user.id)
        if self.topic.currentText() != "Tất cả": attempts = [item for item in attempts if item.topic == self.topic.currentText()]
        if self.kind.currentText() != "Tất cả": attempts = [item for item in attempts if item.kind == self.kind.currentText()]
        selected = self.score.currentText()
        if selected == "Dưới 5": attempts = [item for item in attempts if item.score < 5]
        elif selected == "5 đến 8": attempts = [item for item in attempts if 5 <= item.score < 8]
        elif selected == "Từ 8 trở lên": attempts = [item for item in attempts if item.score >= 8]
        self.table.setRowCount(len(attempts))
        for row, item in enumerate(attempts):
            for col, value in enumerate([item.title, item.kind, item.topic, f"{item.score}/10", f"{item.correct_count}/{item.total}", item.created_at]): self.table.setItem(row, col, QTableWidgetItem(value))
        self.table.resizeColumnsToContents()
        chronological = list(reversed(attempts)); axis = self.line.axes(); axis.plot(range(1, len(chronological)+1), [item.score for item in chronological], marker="o", color="#2f80ed"); axis.set_ylim(0, 10.5); axis.set_ylabel("Điểm")
        grouped: dict[str, list[float]] = defaultdict(list)
        for item in attempts: grouped[item.topic].append(item.score)
        axis = self.bar.axes(); labels = list(grouped) or ["Chưa có"]; values = [sum(values)/len(values) for values in grouped.values()] or [0]; axis.bar(labels, values, color="#61a5fa"); axis.set_ylim(0, 10.5); axis.tick_params(axis="x", rotation=25)
        axis = self.pie.axes(); correct, total = sum(item.correct_count for item in attempts), sum(item.total for item in attempts); axis.pie([correct or 1, max(total-correct, 0) or 1], labels=["Đúng", "Sai"], colors=["#35a36b", "#f39c88"], autopct="%1.0f%%")
        weak = min(grouped, key=lambda key: sum(grouped[key]) / len(grouped[key])) if grouped else "TCP Socket"
        self.tip.setText(f"Gợi ý: Bạn nên luyện thêm chủ đề {weak} để cải thiện sự ổn định.")


class ProfilePage(QWidget):
    logged_out = Signal()

    def __init__(self, service: MockApiService, user: User) -> None:
        super().__init__(); self.service, self.user = service, user
        self.root = QVBoxLayout(self); self.root.setContentsMargins(6, 6, 6, 6); self.refresh()

    def refresh(self) -> None:
        while self.root.count():
            item = self.root.takeAt(0)
            if item.widget(): item.widget().deleteLater()
        self.root.addWidget(PageHeader("Hồ sơ cá nhân", "Cập nhật thông tin mock hoặc khôi phục dữ liệu demo khi cần."))
        card = QFrame(); card.setObjectName("card"); layout = QVBoxLayout(card)
        avatar = QLabel(self.user.full_name[:1].upper()); avatar.setAlignment(Qt.AlignCenter); avatar.setFixedSize(70,70); avatar.setStyleSheet("background:#2f80ed;color:white;border-radius:35px;font-size:28px;font-weight:700;"); layout.addWidget(avatar)
        self.name = QLineEdit(self.user.full_name); self.email = QLineEdit(self.user.email)
        form = QFormLayout(); form.addRow("Họ tên", self.name); form.addRow("Username", QLabel(self.user.username)); form.addRow("Email", self.email); form.addRow("Vai trò", QLabel("Chủ phòng" if self.user.role == "HOST" else "Thí sinh")); form.addRow("Ngày tham gia", QLabel(self.user.joined_at)); layout.addLayout(form)
        save = QPushButton("Cập nhật thông tin"); save.clicked.connect(self._save); layout.addWidget(save)
        change = QPushButton("Đổi mật khẩu mock"); change.setObjectName("secondary"); change.clicked.connect(self._password); layout.addWidget(change)
        reset = QPushButton("Khôi phục dữ liệu demo"); reset.setObjectName("secondary"); reset.clicked.connect(self._reset); layout.addWidget(reset)
        logout = QPushButton("Đăng xuất"); logout.setObjectName("danger"); logout.clicked.connect(self.logged_out); layout.addWidget(logout)
        self.root.addWidget(card); self.root.addStretch()

    def _save(self) -> None:
        try: self.user = self.service.update_profile(self.user.id, self.name.text(), self.email.text()); _message(self, "Đã cập nhật", "Thông tin mock đã được lưu."); self.refresh()
        except ServiceError as error: _message(self, "Không thể cập nhật", str(error), True)

    def _password(self) -> None:
        dialog = QDialog(self); dialog.setWindowTitle("Đổi mật khẩu"); form = QFormLayout(dialog); current = QLineEdit(); current.setEchoMode(QLineEdit.Password); new = QLineEdit(); new.setEchoMode(QLineEdit.Password); form.addRow("Mật khẩu hiện tại", current); form.addRow("Mật khẩu mới", new); buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel); form.addRow(buttons); buttons.rejected.connect(dialog.reject); buttons.accepted.connect(dialog.accept)
        if dialog.exec() == QDialog.Accepted:
            try: self.service.change_password(self.user.id, current.text(), new.text()); _message(self, "Đã đổi mật khẩu", "Mật khẩu mock mới đã được lưu.")
            except ServiceError as error: _message(self, "Không thể đổi mật khẩu", str(error), True)

    def _reset(self) -> None:
        if QMessageBox.question(self, "Khôi phục dữ liệu", "Mọi thay đổi mock trong phiên demo sẽ bị xóa.", QMessageBox.Yes | QMessageBox.No) == QMessageBox.Yes:
            self.service.reset_demo(); _message(self, "Đã khôi phục", "Dữ liệu demo đã trở về trạng thái ban đầu."); self.logged_out.emit()
