"""Small reusable visual widgets used by all feature pages."""

from __future__ import annotations

from PySide6.QtCore import QTimer, Qt, Signal
from PySide6.QtWidgets import QFrame, QGridLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton, QVBoxLayout, QWidget


class PrimaryButton(QPushButton):
    pass


class SecondaryButton(QPushButton):
    def __init__(self, text: str, parent: QWidget | None = None) -> None:
        super().__init__(text, parent)
        self.setObjectName("secondary")


class DangerButton(QPushButton):
    def __init__(self, text: str, parent: QWidget | None = None, outline: bool = False) -> None:
        super().__init__(text, parent)
        self.setObjectName("dangerOutline" if outline else "danger")


class UserAvatar(QLabel):
    def __init__(self, name: str, size: int = 36, parent: QWidget | None = None) -> None:
        super().__init__(name[:1].upper() if name else "?", parent)
        self.setAlignment(Qt.AlignCenter)
        self.setFixedSize(size, size)
        self.setStyleSheet(f"background:#2563EB;color:white;border-radius:{size // 2}px;font-size:{max(12, size // 3)}px;font-weight:700;")
        self.setToolTip(name)


class SectionCard(QFrame):
    def __init__(self, title: str = "", subtitle: str = "", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("sectionCard")
        self.layout = QVBoxLayout(self)
        self.layout.setContentsMargins(16, 16, 16, 16)
        self.layout.setSpacing(10)
        if title:
            label = QLabel(title)
            label.setObjectName("sectionTitle")
            self.layout.addWidget(label)
        if subtitle:
            detail = QLabel(subtitle)
            detail.setObjectName("caption")
            detail.setWordWrap(True)
            self.layout.addWidget(detail)


class EmptyStateWidget(QFrame):
    def __init__(self, title: str, detail: str, action: QPushButton | None = None, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("sectionCard")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 28, 24, 28)
        layout.setAlignment(Qt.AlignCenter)
        icon = QLabel("⌕")
        icon.setAlignment(Qt.AlignCenter)
        icon.setStyleSheet("color:#2563EB;font-size:30px;")
        layout.addWidget(icon)
        heading = QLabel(title)
        heading.setObjectName("sectionTitle")
        heading.setAlignment(Qt.AlignCenter)
        layout.addWidget(heading)
        text = QLabel(detail)
        text.setObjectName("subtle")
        text.setAlignment(Qt.AlignCenter)
        text.setWordWrap(True)
        layout.addWidget(text)
        if action:
            layout.addWidget(action, alignment=Qt.AlignCenter)


class SearchInput(QLineEdit):
    def __init__(self, placeholder: str = "Tìm kiếm…", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setPlaceholderText(f"⌕  {placeholder}")
        self.setClearButtonEnabled(True)


class FilterChip(QPushButton):
    def __init__(self, text: str, checked: bool = False, parent: QWidget | None = None) -> None:
        super().__init__(text, parent)
        self.setObjectName("chip")
        self.setCheckable(True)
        self.setChecked(checked)


class ScoreBadge(QLabel):
    def __init__(self, score: float, parent: QWidget | None = None) -> None:
        super().__init__(f"{score:.1f}/10", parent)
        if score >= 8:
            background, color = "#DCFCE7", "#15803D"
        elif score >= 5:
            background, color = "#FEF3C7", "#B45309"
        else:
            background, color = "#FEE2E2", "#B91C1C"
        self.setAlignment(Qt.AlignCenter)
        self.setStyleSheet(f"background:{background};color:{color};border-radius:10px;padding:4px 8px;font-weight:700;")


class QuestionNavigator(QFrame):
    """Responsive question-number grid used by exam and practice flows."""

    question_selected = Signal(int)

    def __init__(self, total: int, current: int, answered: set[int], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("sectionCard")
        self.setMinimumHeight(500)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        title = QLabel("Câu hỏi")
        title.setObjectName("sectionTitle")
        layout.addWidget(title)
        legend = QLabel("■ Đã chọn   □ Chưa làm")
        legend.setObjectName("caption")
        layout.addWidget(legend)
        grid = QGridLayout()
        grid.setSpacing(7)
        for index in range(total):
            button = QPushButton(f"{index + 1:02d}")
            button.setObjectName("questionNumber")
            button.setCheckable(True)
            button.setChecked(index == current)
            button.setProperty("answered", "true" if index in answered else "false")
            button.clicked.connect(lambda _=False, target=index: self.question_selected.emit(target))
            grid.addWidget(button, index // 4, index % 4)
        layout.addLayout(grid)
        layout.addStretch()


class ToastNotification(QFrame):
    def __init__(self, parent: QWidget, message: str, kind: str = "success") -> None:
        super().__init__(parent)
        self.setObjectName("toast")
        colors = {"success": ("#DCFCE7", "#166534", "✓"), "warning": ("#FEF3C7", "#92400E", "!"), "info": ("#E0F2FE", "#075985", "i")}
        background, text_color, marker = colors.get(kind, colors["success"])
        self.setStyleSheet(f"QFrame#toast{{background:{background};border:1px solid {background};}} QLabel{{color:{text_color};font-weight:600;}}")
        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 9, 12, 9)
        layout.addWidget(QLabel(marker))
        layout.addWidget(QLabel(message))
        self.adjustSize()
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self.close)

    def show_for(self, milliseconds: int = 2800) -> None:
        parent = self.parentWidget()
        if parent:
            self.move(max(12, parent.width() - self.sizeHint().width() - 28), max(12, parent.height() - self.sizeHint().height() - 28))
        self.show()
        self.raise_()
        self._timer.start(milliseconds)


def show_toast(parent: QWidget, message: str, kind: str = "success") -> None:
    ToastNotification(parent.window(), message, kind).show_for()
