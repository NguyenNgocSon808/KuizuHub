from __future__ import annotations

from PySide6.QtCore import QTimer, Signal, Qt
from PySide6.QtWidgets import (QButtonGroup, QDialog, QDialogButtonBox, QFrame, QHBoxLayout, QLabel,
                               QGridLayout, QMessageBox, QPushButton, QRadioButton, QScrollArea, QToolBox,
                               QVBoxLayout, QWidget)

from ...models import Attempt, Question, User
from ...services import MockApiService, ServiceError
from ..widgets import ChartCanvas, MetricCard, PageHeader, StatusBadge


class ExamPage(QWidget):
    submitted = Signal(object)

    def __init__(self, service: MockApiService, user: User) -> None:
        super().__init__()
        self.service, self.user = service, user
        self.questions: list[Question] = []
        self.answers: dict[int, int] = {}
        self.current = 0; self.remaining = 0; self.duration = 0; self.kind = "Thi phòng"; self.title = ""
        self.topic = "Trộn"; self.room_id: int | None = None; self.practice = False
        self.timer = QTimer(self); self.timer.timeout.connect(self._tick)
        self.root = QVBoxLayout(self); self.root.setContentsMargins(6, 6, 6, 6)

    def load_exam(self, questions: list[Question], *, title: str, topic: str, minutes: int, practice: bool = False, room_id: int | None = None) -> None:
        self.questions, self.answers, self.current = questions, {}, 0
        self.title, self.topic, self.remaining, self.duration = title, topic, minutes * 60, minutes * 60
        self.practice, self.room_id, self.kind = practice, room_id, "Luyện tập" if practice else "Thi phòng"
        self.timer.stop()
        if minutes: self.timer.start(1000)
        self._render()

    def _clear(self) -> None:
        while self.root.count():
            item = self.root.takeAt(0)
            if item.widget(): item.widget().deleteLater()
            elif item.layout():
                while item.layout().count():
                    child = item.layout().takeAt(0)
                    if child.widget(): child.widget().deleteLater()

    def _render(self) -> None:
        self._clear()
        if not self.questions:
            self.root.addWidget(QLabel("Chưa có đề thi.")); return
        header = QFrame(); header.setObjectName("card"); top = QHBoxLayout(header)
        info = QLabel(f"{self.title}\nĐã trả lời {len(self.answers)}/{len(self.questions)} câu")
        info.setStyleSheet("font-size:16px;font-weight:700;")
        top.addWidget(info); top.addStretch()
        self.clock = QLabel(self._time_text()); self.clock.setStyleSheet("font-size:25px;font-weight:700;color:#b42318;" if self.remaining and self.remaining <= 300 else "font-size:25px;font-weight:700;color:#146cdb;")
        top.addWidget(self.clock)
        submit = QPushButton("Nộp bài"); submit.setObjectName("danger"); submit.clicked.connect(self._confirm_submit); top.addWidget(submit)
        self.root.addWidget(header)
        body = QHBoxLayout(); body.setSpacing(16)
        navigator = QFrame(); navigator.setObjectName("card"); nav = QVBoxLayout(navigator)
        nav.addWidget(QLabel("Câu hỏi")); grid = QGridLayout(); nav.addLayout(grid)
        # compact vertical navigator works at any desktop width
        for idx in range(len(self.questions)):
            number = QPushButton(str(idx + 1)); number.setCheckable(True); number.setChecked(idx == self.current); number.setFixedWidth(42)
            if self.questions[idx].id in self.answers: number.setStyleSheet("background:#35a36b;")
            elif idx == self.current: number.setStyleSheet("background:#f4a340;")
            number.clicked.connect(lambda _=False, i=idx: self._goto(i)); grid.addWidget(number, idx // 4, idx % 4)
        nav.addStretch(); body.addWidget(navigator, 2)
        panel = self._question_panel(); body.addWidget(panel, 8)
        self.root.addLayout(body, 1)

    def _question_panel(self) -> QFrame:
        question = self.questions[self.current]
        frame = QFrame(); frame.setObjectName("card"); layout = QVBoxLayout(frame); layout.setSpacing(12)
        heading = QLabel(f"Câu {self.current + 1} / {len(self.questions)}")
        heading.setStyleSheet("color:#146cdb;font-weight:700;"); layout.addWidget(heading)
        content = QLabel(question.content); content.setWordWrap(True); content.setStyleSheet("font-size:18px;font-weight:600;"); layout.addWidget(content)
        self.answer_group = QButtonGroup(frame)
        for index, option in enumerate(question.options):
            radio = QRadioButton(f"{chr(65 + index)}.  {option}")
            radio.setStyleSheet("QRadioButton { background:#f8fafc; border:1px solid #e5eaf1; border-radius:8px; padding:12px; } QRadioButton:checked { border:2px solid #2f80ed; background:#edf5ff; }")
            radio.setChecked(self.answers.get(question.id) == index)
            self.answer_group.addButton(radio, index); layout.addWidget(radio)
        self.answer_group.idClicked.connect(self._answer)
        self.feedback = QLabel()
        self.feedback.setWordWrap(True)
        if self.practice and question.id in self.answers:
            self._feedback(question)
        layout.addWidget(self.feedback)
        layout.addStretch()
        move = QHBoxLayout()
        previous = QPushButton("← Câu trước"); previous.setObjectName("secondary"); previous.setEnabled(self.current > 0); previous.clicked.connect(lambda: self._goto(self.current - 1)); move.addWidget(previous)
        move.addStretch(); nxt = QPushButton("Câu tiếp →"); nxt.setEnabled(self.current < len(self.questions) - 1); nxt.clicked.connect(lambda: self._goto(self.current + 1)); move.addWidget(nxt)
        layout.addLayout(move)
        return frame

    def _answer(self, option: int) -> None:
        self.answers[self.questions[self.current].id] = option
        if self.practice:
            self._feedback(self.questions[self.current])
        self._render()

    def _feedback(self, question: Question) -> None:
        selected = self.answers.get(question.id)
        if selected == question.correct_index:
            self.feedback.setText(f"✓ Chính xác. {question.explanation}"); self.feedback.setStyleSheet("background:#dcfce7;color:#18794e;padding:10px;border-radius:6px;")
        else:
            self.feedback.setText(f"✕ Chưa đúng. Đáp án: {chr(65 + question.correct_index)}. {question.explanation}"); self.feedback.setStyleSheet("background:#fee2e2;color:#b42318;padding:10px;border-radius:6px;")

    def _goto(self, index: int) -> None:
        self.current = index; self._render()

    def _time_text(self) -> str:
        if not self.duration: return "Không giới hạn"
        return f"{self.remaining // 60:02d}:{self.remaining % 60:02d}"

    def _tick(self) -> None:
        self.remaining = max(0, self.remaining - 1)
        if self.remaining == 300:
            QMessageBox.warning(self, "Sắp hết giờ", "Còn 5 phút, hãy kiểm tra câu trả lời.")
        if self.remaining == 60:
            QMessageBox.warning(self, "Sắp hết giờ", "Còn 1 phút, bài sẽ được nộp tự động.")
        if self.remaining == 0:
            self.timer.stop(); QMessageBox.information(self, "Hết giờ", "Hết giờ, bài đã được nộp tự động."); self._submit(auto=True)
        else:
            self._render()

    def _confirm_submit(self) -> None:
        undone = len(self.questions) - len(self.answers)
        dialog = QMessageBox(self); dialog.setWindowTitle("Xác nhận nộp bài")
        dialog.setText(f"Bạn đã làm {len(self.answers)}/{len(self.questions)} câu. Còn {undone} câu chưa làm.")
        back = dialog.addButton("Quay lại", QMessageBox.RejectRole); ok = dialog.addButton("Xác nhận nộp bài", QMessageBox.AcceptRole)
        dialog.exec()
        if dialog.clickedButton() == ok: self._submit()

    def _submit(self, auto: bool = False) -> None:
        try:
            self.timer.stop()
            elapsed = (self.duration - self.remaining) if self.duration else 0
            attempt = self.service.submit_attempt(self.user.id, title=self.title, kind=self.kind, topic=self.topic, questions=self.questions, answers=self.answers, duration_seconds=elapsed, room_id=self.room_id, auto=auto)
            self.submitted.emit(attempt)
        except ServiceError as error:
            QMessageBox.warning(self, "Không thể nộp bài", str(error))


class ResultPage(QWidget):
    go_dashboard = Signal()
    new_practice = Signal()

    def __init__(self, service: MockApiService, user: User) -> None:
        super().__init__()
        self.service, self.user, self.attempt = service, user, None
        self.root = QVBoxLayout(self); self.root.setContentsMargins(6, 6, 6, 6)

    def set_attempt(self, attempt: Attempt) -> None:
        self.attempt = attempt; self._render()

    def _render(self) -> None:
        while self.root.count():
            item = self.root.takeAt(0)
            if item.widget(): item.widget().deleteLater()
        if not self.attempt: return
        attempt = self.attempt
        self.root.addWidget(PageHeader("Kết quả bài làm", f"{attempt.title} • {attempt.created_at}"))
        metric_row = QHBoxLayout()
        metric_row.addWidget(MetricCard("Điểm số", f"{attempt.score}/10", "#18794e")); metric_row.addWidget(MetricCard("Câu đúng", f"{attempt.correct_count}/{attempt.total}")); metric_row.addWidget(MetricCard("Hoàn thành", f"{len(attempt.answers) * 100 // attempt.total if attempt.total else 0}%")); metric_row.addWidget(MetricCard("Thời gian", f"{attempt.duration_seconds // 60}:{attempt.duration_seconds % 60:02d}"))
        self.root.addLayout(metric_row)
        review_line = QHBoxLayout(); chart_box = QFrame(); chart_box.setObjectName("card"); chart_layout = QVBoxLayout(chart_box)
        note = "Xuất sắc! Bạn nắm kiến thức rất vững." if attempt.score >= 8 else "Khá tốt. Hãy luyện thêm các chủ đề còn yếu." if attempt.score >= 5 else "Cần luyện tập thêm, bắt đầu từ các câu cơ bản nhé."
        chart_layout.addWidget(QLabel(note)); chart = ChartCanvas(3.4, 2.4); axis = chart.axes(); axis.pie([attempt.correct_count, max(0, attempt.total - attempt.correct_count)], labels=["Đúng", "Sai/chưa làm"], colors=["#35a36b", "#f39c88"], autopct="%1.0f%%"); chart_layout.addWidget(chart); review_line.addWidget(chart_box, 3)
        reviews = QToolBox()
        for number, question_id in enumerate(attempt.question_ids, 1):
            question = self.service._question(question_id); selected = attempt.answers.get(str(question_id))
            is_correct = selected == question.correct_index
            content = QLabel(f"Bạn chọn: {chr(65 + selected) if selected is not None else 'Chưa chọn'}\nĐáp án đúng: {chr(65 + question.correct_index)}\n\n{question.explanation}")
            content.setWordWrap(True); content.setStyleSheet("padding:8px;color:#475467;")
            reviews.addItem(content, f"Câu {number}: {'Đúng' if is_correct else 'Sai'}")
        review_line.addWidget(reviews, 7); self.root.addLayout(review_line, 1)
        actions = QHBoxLayout(); actions.addStretch(); home = QPushButton("Về dashboard"); home.setObjectName("secondary"); home.clicked.connect(self.go_dashboard); practice = QPushButton("Làm bài luyện tập mới"); practice.clicked.connect(self.new_practice); actions.addWidget(home); actions.addWidget(practice); self.root.addLayout(actions)
