"""Focused exam experience and results review."""

from __future__ import annotations

from PySide6.QtCore import QTimer, Signal, Qt
from PySide6.QtWidgets import (QButtonGroup, QFrame, QHBoxLayout, QLabel, QMessageBox,
                               QProgressBar, QPushButton, QRadioButton, QToolBox,
                               QVBoxLayout, QWidget)

from ...models import Attempt, Question, User
from ...services import MockApiService, ServiceError
from ..widgets import (ChartCanvas, MetricCard, PageHeader, PrimaryButton, QuestionNavigator,
                       SecondaryButton, SectionCard, show_toast)


class ExamPage(QWidget):
    submitted = Signal(object)

    def __init__(self, service: MockApiService, user: User) -> None:
        super().__init__()
        self.service, self.user = service, user
        self.questions: list[Question] = []
        self.answers: dict[int, int] = {}
        self.current = 0
        self.remaining = self.duration = 0
        self.kind, self.title, self.topic = "Thi phòng", "", "Trộn"
        self.room_id: int | None = None
        self.practice = False
        self.timer = QTimer(self)
        self.timer.timeout.connect(self._tick)
        self.root = QVBoxLayout(self)
        self.root.setContentsMargins(4, 4, 4, 4)
        self.root.setSpacing(14)

    def load_exam(self, questions: list[Question], *, title: str, topic: str, minutes: int,
                  practice: bool = False, room_id: int | None = None) -> None:
        self.questions, self.answers, self.current = questions, {}, 0
        self.title, self.topic = title, topic
        self.remaining = self.duration = minutes * 60
        self.practice, self.room_id = practice, room_id
        self.kind = "Luyện tập" if practice else "Thi phòng"
        self.timer.stop()
        if minutes:
            self.timer.start(1000)
        self._render()

    def _clear(self) -> None:
        while self.root.count():
            item = self.root.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
            elif item.layout():
                self._dispose_layout(item.layout())

    def _dispose_layout(self, layout: object) -> None:
        while layout.count():
            child = layout.takeAt(0)
            if child.widget():
                child.widget().deleteLater()
            elif child.layout():
                self._dispose_layout(child.layout())

    def _render(self) -> None:
        self._clear()
        if not self.questions:
            self.root.addWidget(QLabel("Chưa có đề thi."))
            return
        self.root.addWidget(self._exam_header())
        body = QHBoxLayout()
        body.setSpacing(16)
        navigator = QuestionNavigator(len(self.questions), self.current, set(self.answers))
        navigator.question_selected.connect(self._goto)
        body.addWidget(navigator, 2)
        body.addWidget(self._question_card(), 8)
        self.root.addLayout(body, 1)

    def _exam_header(self) -> QFrame:
        header = QFrame()
        header.setObjectName("sectionCard")
        layout = QHBoxLayout(header)
        layout.setContentsMargins(16, 12, 16, 12)
        title = QLabel(self.title)
        title.setStyleSheet("font-size:17px;font-weight:700;")
        layout.addWidget(title)
        layout.addStretch()
        progress_block = QVBoxLayout()
        self.progress_text = QLabel(f"Tiến độ · {len(self.answers)}/{len(self.questions)} câu")
        self.progress_text.setObjectName("caption")
        progress_block.addWidget(self.progress_text)
        self.progress = QProgressBar()
        self.progress.setFixedWidth(190)
        self.progress.setTextVisible(False)
        self.progress.setRange(0, len(self.questions))
        self.progress.setValue(len(self.answers))
        progress_block.addWidget(self.progress)
        layout.addLayout(progress_block)
        layout.addSpacing(20)
        self.clock = QLabel()
        self.clock.setAlignment(Qt.AlignCenter)
        self.clock.setMinimumWidth(76)
        self._update_clock()
        layout.addWidget(self.clock)
        layout.addSpacing(10)
        submit = PrimaryButton("Nộp bài")
        submit.setObjectName("danger")
        submit.clicked.connect(self._confirm_submit)
        layout.addWidget(submit)
        return header

    def _question_card(self) -> SectionCard:
        question = self.questions[self.current]
        card = SectionCard()
        card.setMinimumHeight(500)
        label = QLabel(f"Câu {self.current + 1:02d} / {len(self.questions):02d}")
        label.setStyleSheet("color:#2563EB;font-weight:700;")
        card.layout.addWidget(label)
        content = QLabel(question.content)
        content.setWordWrap(True)
        content.setStyleSheet("font-size:19px;font-weight:600;line-height:1.4;")
        card.layout.addWidget(content)
        card.layout.addSpacing(8)
        group = QButtonGroup(card)
        selected = self.answers.get(question.id)
        for index, option in enumerate(question.options):
            radio = QRadioButton(f"{chr(65 + index)}     {option}")
            radio.setObjectName("answerOption")
            radio.setChecked(selected == index)
            if self.practice and selected is not None:
                if index == question.correct_index:
                    radio.setStyleSheet("QRadioButton{background:#DCFCE7;color:#166534;border:2px solid #86EFAC;border-radius:10px;padding:13px;spacing:10px;}")
                elif index == selected:
                    radio.setStyleSheet("QRadioButton{background:#FEE2E2;color:#991B1B;border:2px solid #FCA5A5;border-radius:10px;padding:13px;spacing:10px;}")
            group.addButton(radio, index)
            card.layout.addWidget(radio)
        group.idClicked.connect(self._answer)
        if self.practice and selected is not None:
            correct = selected == question.correct_index
            text = (f"✓ Chính xác. {question.explanation}" if correct else
                    f"✕ Chưa đúng. Đáp án chính xác là {chr(65 + question.correct_index)}. {question.explanation}")
            feedback = QLabel(text)
            feedback.setWordWrap(True)
            feedback.setStyleSheet("background:#DCFCE7;color:#166534;border-radius:8px;padding:10px;" if correct else "background:#FEE2E2;color:#991B1B;border-radius:8px;padding:10px;")
            card.layout.addWidget(feedback)
        self.save_state = QLabel("Chọn một đáp án để tự động lưu")
        self.save_state.setObjectName("caption")
        card.layout.addWidget(self.save_state)
        card.layout.addStretch()
        actions = QHBoxLayout()
        previous = SecondaryButton("← Câu trước")
        previous.setEnabled(self.current > 0)
        previous.clicked.connect(lambda: self._goto(self.current - 1))
        actions.addWidget(previous)
        actions.addStretch()
        next_button = PrimaryButton("Câu tiếp →")
        next_button.setEnabled(self.current < len(self.questions) - 1)
        next_button.clicked.connect(lambda: self._goto(self.current + 1))
        actions.addWidget(next_button)
        card.layout.addLayout(actions)
        return card

    def _answer(self, option: int) -> None:
        self.answers[self.questions[self.current].id] = option
        show_toast(self, "Đã lưu đáp án.", "info")
        self._render()

    def _goto(self, index: int) -> None:
        self.current = index
        self._render()

    def _time_text(self) -> str:
        if not self.duration:
            return "Không giới hạn"
        return f"{self.remaining // 60:02d}:{self.remaining % 60:02d}"

    def _update_clock(self) -> None:
        if not hasattr(self, "clock"):
            return
        if not self.duration:
            color, background = "#475569", "#F1F5F9"
        elif self.remaining <= 60:
            color, background = "#B91C1C", "#FEE2E2"
        elif self.remaining <= 300:
            color, background = "#B45309", "#FEF3C7"
        else:
            color, background = "#1D4ED8", "#EFF6FF"
        self.clock.setText(self._time_text())
        self.clock.setStyleSheet(f"background:{background};color:{color};border-radius:8px;padding:8px;font-size:20px;font-weight:700;")

    def _tick(self) -> None:
        self.remaining = max(0, self.remaining - 1)
        self._update_clock()
        if self.remaining == 300:
            show_toast(self, "Còn 5 phút, hãy kiểm tra bài làm.", "warning")
        elif self.remaining == 60:
            show_toast(self, "Còn 1 phút, bài sẽ tự nộp khi hết giờ.", "warning")
        elif self.remaining == 0:
            self.timer.stop()
            QMessageBox.information(self, "Hết giờ", "Hết giờ, bài đã được nộp tự động.")
            self._submit(auto=True)

    def _confirm_submit(self) -> None:
        complete, total = len(self.answers), len(self.questions)
        dialog = QMessageBox(self)
        dialog.setWindowTitle("Xác nhận nộp bài")
        dialog.setIcon(QMessageBox.Question)
        dialog.setText("Bạn đã sẵn sàng nộp bài?")
        dialog.setInformativeText(f"Đã làm: {complete}/{total} câu\nCòn bỏ trống: {total - complete} câu")
        back = dialog.addButton("Quay lại kiểm tra", QMessageBox.RejectRole)
        confirm = dialog.addButton("Xác nhận nộp bài", QMessageBox.AcceptRole)
        dialog.exec()
        if dialog.clickedButton() == confirm:
            self._submit()

    def _submit(self, auto: bool = False) -> None:
        try:
            self.timer.stop()
            elapsed = self.duration - self.remaining if self.duration else 0
            attempt = self.service.submit_attempt(self.user.id, title=self.title, kind=self.kind,
                                                  topic=self.topic, questions=self.questions,
                                                  answers=self.answers, duration_seconds=elapsed,
                                                  room_id=self.room_id, auto=auto)
            self.submitted.emit(attempt)
        except ServiceError as error:
            QMessageBox.warning(self, "Không thể nộp bài", str(error))


class ResultPage(QWidget):
    go_dashboard = Signal()
    new_practice = Signal()
    go_history = Signal()

    def __init__(self, service: MockApiService, user: User) -> None:
        super().__init__()
        self.service, self.user, self.attempt = service, user, None
        self.root = QVBoxLayout(self)
        self.root.setContentsMargins(4, 4, 4, 4)
        self.root.setSpacing(14)

    def set_attempt(self, attempt: Attempt) -> None:
        self.attempt = attempt
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
        if not self.attempt:
            return
        attempt = self.attempt
        self.root.addWidget(PageHeader("Kết quả bài làm", f"{attempt.title} · {attempt.created_at}"))
        self.root.addWidget(self._hero(attempt))
        rows = QHBoxLayout()
        rows.setSpacing(16)
        rows.addWidget(self._review(attempt), 7)
        rows.addWidget(self._summary(attempt), 3)
        self.root.addLayout(rows, 1)
        actions = QHBoxLayout()
        actions.addStretch()
        history = SecondaryButton("Xem lịch sử")
        history.clicked.connect(self.go_history)
        home = SecondaryButton("Về tổng quan")
        home.clicked.connect(self.go_dashboard)
        practice = PrimaryButton("Làm bài mới")
        practice.clicked.connect(self.new_practice)
        actions.addWidget(history); actions.addWidget(home); actions.addWidget(practice)
        self.root.addLayout(actions)

    def _hero(self, attempt: Attempt) -> QFrame:
        card = QFrame()
        card.setObjectName("heroCard")
        layout = QHBoxLayout(card)
        layout.setContentsMargins(22, 18, 22, 18)
        score_copy = QVBoxLayout()
        percent = int(attempt.correct_count * 100 / attempt.total) if attempt.total else 0
        message = "Xuất sắc!" if percent >= 90 else "Làm tốt!" if percent >= 70 else "Bạn đang tiến bộ." if percent >= 50 else "Hãy luyện tập thêm."
        score_copy.addWidget(QLabel(message, objectName="pageTitle"))
        score_copy.addWidget(QLabel("Đây là kết quả của bạn. Hãy xem lại đáp án để rút kinh nghiệm.", objectName="subtle"))
        layout.addLayout(score_copy, 1)
        score = QLabel(f"{attempt.score:.1f}")
        score.setAlignment(Qt.AlignCenter)
        score.setFixedSize(100, 100)
        score.setStyleSheet("background:#2563EB;color:white;border-radius:50px;font-size:30px;font-weight:700;")
        layout.addWidget(score)
        layout.addWidget(QLabel("/10\nĐiểm số", objectName="subtle"))
        return card

    def _summary(self, attempt: Attempt) -> SectionCard:
        card = SectionCard("Tóm tắt", "Kết quả theo bài làm vừa hoàn thành.")
        metrics = [("Câu đúng", f"{attempt.correct_count}/{attempt.total}", "✓"),
                   ("Câu sai", str(attempt.total - attempt.correct_count), "×"),
                   ("Thời gian", f"{attempt.duration_seconds // 60}:{attempt.duration_seconds % 60:02d}", "◷"),
                   ("Chủ đề", attempt.topic, "⌁")]
        for label, value, icon in metrics:
            card.layout.addWidget(MetricCard(label, value, icon=icon))
        chart = ChartCanvas(3.1, 2.2)
        axis = chart.axes()
        axis.pie([attempt.correct_count, max(0, attempt.total - attempt.correct_count)], labels=["Đúng", "Sai"],
                 colors=["#16A34A", "#FCA5A5"], autopct="%1.0f%%", wedgeprops={"width": .46})
        card.layout.addWidget(chart)
        return card

    def _review(self, attempt: Attempt) -> SectionCard:
        card = SectionCard("Xem lại đáp án", "Mở từng câu để xem đáp án của bạn, đáp án đúng và giải thích.")
        accordion = QToolBox()
        for number, question_id in enumerate(attempt.question_ids, 1):
            question = self.service._question(question_id)
            selected = attempt.answers.get(str(question_id))
            correct = selected == question.correct_index
            content = QLabel(f"Bạn chọn: {chr(65 + selected) if selected is not None else 'Chưa chọn'}\nĐáp án đúng: {chr(65 + question.correct_index)}\n\nGiải thích: {question.explanation}")
            content.setWordWrap(True)
            content.setStyleSheet("padding:10px;color:#475569;")
            accordion.addItem(content, f"{'✓' if correct else '×'}  Câu {number:02d} · {'Đúng' if correct else 'Chưa đúng'}")
        card.layout.addWidget(accordion)
        return card
