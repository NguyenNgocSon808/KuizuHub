from __future__ import annotations

import os
import tempfile

# Avoid a non-writable user-home cache from delaying chart startup on lab PCs.
os.environ.setdefault("MPLCONFIGDIR", os.path.join(tempfile.gettempdir(), "kuizuhub-matplotlib"))

from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg
from matplotlib.figure import Figure
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QSizePolicy, QVBoxLayout, QWidget

from ..design import STATUS_STYLES


class PageHeader(QWidget):
    def __init__(self, title: str, subtitle: str = "") -> None:
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 10)
        heading = QLabel(title)
        heading.setObjectName("pageTitle")
        layout.addWidget(heading)
        if subtitle:
            detail = QLabel(subtitle)
            detail.setObjectName("subtle")
            layout.addWidget(detail)


class MetricCard(QFrame):
    def __init__(self, label: str, value: str, accent: str = "", icon: str = "", hint: str = "") -> None:
        super().__init__()
        self.setObjectName("metric")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(15, 12, 15, 12)
        header = QHBoxLayout()
        self.label = QLabel(label)
        self.label.setObjectName("metricLabel")
        header.addWidget(self.label)
        header.addStretch()
        if icon:
            symbol = QLabel(icon)
            symbol.setStyleSheet("background:#EFF6FF;color:#2563EB;border-radius:8px;padding:4px;font-size:15px;")
            header.addWidget(symbol)
        self.value = QLabel(value)
        self.value.setObjectName("metricValue")
        if accent:
            self.value.setStyleSheet(f"color: {accent};")
        layout.addLayout(header)
        layout.addWidget(self.value)
        if hint:
            trend = QLabel(hint)
            trend.setObjectName("metricHint")
            layout.addWidget(trend)

    def set_value(self, value: str) -> None:
        self.value.setText(value)


class StatusBadge(QLabel):
    def __init__(self, status: str) -> None:
        super().__init__()
        self.setAlignment(Qt.AlignCenter)
        self.set_status(status)

    def set_status(self, status: str) -> None:
        text, bg, color = STATUS_STYLES.get(status, (status, "#eef2f6", "#344054"))
        self.setText(text)
        self.setStyleSheet(f"background:{bg}; color:{color}; border-radius:10px; padding:4px 8px; font-weight:600;")


class ChartCanvas(FigureCanvasQTAgg):
    def __init__(self, width: float = 5.0, height: float = 2.6) -> None:
        self.figure = Figure(figsize=(width, height), facecolor="white", tight_layout=True)
        super().__init__(self.figure)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

    def axes(self):
        self.figure.clear()
        axis = self.figure.add_subplot(111)
        axis.spines[["top", "right"]].set_visible(False)
        axis.grid(axis="y", color="#e9edf3", linewidth=.8)
        axis.tick_params(colors="#667085")
        return axis


def card(widget: QWidget) -> QFrame:
    frame = QFrame()
    frame.setObjectName("card")
    layout = QVBoxLayout(frame)
    layout.setContentsMargins(16, 16, 16, 16)
    layout.addWidget(widget)
    return frame
