"""Application-wide QSS tokens and status colors."""

APP_QSS = """
* { font-family: Inter, 'Segoe UI', Arial; color: #0F172A; font-size: 14px; }
QMainWindow, QWidget#root, QScrollArea, QWidget#workspace { background: #F8FAFC; }
QScrollArea { border: none; }

QFrame#sidebar { background: #FFFFFF; border-right: 1px solid #E2E8F0; }
QFrame#topbar { background: #FFFFFF; border: 1px solid #E2E8F0; border-radius: 12px; }
QLabel#brand { color: #0F172A; font-size: 20px; font-weight: 700; }
QLabel#brandMark { background: #2563EB; color: white; border-radius: 9px; font-size: 17px; font-weight: 700; padding: 6px; }
QLabel#sideUser { color: #334155; font-size: 12px; }
QLabel#pageTitle { font-size: 26px; font-weight: 700; color: #0F172A; }
QLabel#sectionTitle { font-size: 17px; font-weight: 600; color: #0F172A; }
QLabel#subtle, QLabel#muted { color: #64748B; }
QLabel#caption { color: #94A3B8; font-size: 12px; }

QFrame#card, QFrame#sectionCard, QFrame#metric, QFrame#roomCard, QFrame#heroCard {
    background: #FFFFFF; border: 1px solid #E2E8F0; border-radius: 12px;
}
QFrame#heroCard { border-color: #BFDBFE; background: #F8FBFF; }
QFrame#metric { min-height: 96px; }
QLabel#metricValue { color: #0F172A; font-size: 25px; font-weight: 700; }
QLabel#metricLabel { color: #64748B; font-size: 12px; }
QLabel#metricHint { color: #16A34A; font-size: 12px; }

QFrame#roomCard:hover { border: 1px solid #BFDBFE; background: #FCFEFF; }
QFrame#toast { border-radius: 10px; padding: 2px; }

QLineEdit, QComboBox, QSpinBox, QTextEdit {
    background: #FFFFFF; border: 1px solid #CBD5E1; border-radius: 8px; padding: 8px 10px; min-height: 20px;
}
QLineEdit:focus, QComboBox:focus, QSpinBox:focus, QTextEdit:focus { border: 2px solid #2563EB; }
QLineEdit::placeholder, QTextEdit::placeholder { color: #94A3B8; }
QComboBox::drop-down { border: none; width: 24px; }

QPushButton { background: #2563EB; color: #FFFFFF; border: none; border-radius: 8px; padding: 9px 14px; font-weight: 600; min-height: 18px; }
QPushButton:hover { background: #1D4ED8; }
QPushButton:pressed { background: #1E40AF; }
QPushButton:disabled { background: #E2E8F0; color: #94A3B8; }
QPushButton#secondary { background: #FFFFFF; color: #334155; border: 1px solid #CBD5E1; }
QPushButton#secondary:hover { background: #F1F5F9; border-color: #94A3B8; }
QPushButton#danger { background: #DC2626; color: #FFFFFF; }
QPushButton#danger:hover { background: #B91C1C; }
QPushButton#dangerOutline { background: #FFFFFF; color: #DC2626; border: 1px solid #FCA5A5; }
QPushButton#dangerOutline:hover { background: #FEF2F2; }
QPushButton#nav { background: transparent; color: #64748B; text-align: left; padding: 10px 12px; border-radius: 8px; font-weight: 500; }
QPushButton#nav:hover { background: #F1F5F9; color: #2563EB; }
QPushButton#nav:checked { background: #DBEAFE; color: #1D4ED8; font-weight: 700; border-left: 3px solid #2563EB; }
QPushButton#chip { background: #FFFFFF; color: #64748B; border: 1px solid #E2E8F0; padding: 7px 12px; min-height: 16px; }
QPushButton#chip:hover { background: #F1F5F9; color: #2563EB; }
QPushButton#chip:checked { background: #DBEAFE; color: #1D4ED8; border-color: #93C5FD; }
QPushButton#questionNumber { background: #FFFFFF; color: #475569; border: 1px solid #CBD5E1; border-radius: 7px; padding: 6px; min-width: 28px; min-height: 22px; }
QPushButton#questionNumber:hover { border-color: #2563EB; color: #1D4ED8; }
QPushButton#questionNumber:checked { border: 2px solid #2563EB; color: #1D4ED8; background: #EFF6FF; }
QPushButton#questionNumber[answered="true"] { background: #2563EB; color: #FFFFFF; border-color: #2563EB; }

QRadioButton#answerOption { background: #FFFFFF; border: 1px solid #E2E8F0; border-radius: 10px; padding: 13px; spacing: 10px; }
QRadioButton#answerOption:hover { background: #F8FAFC; border-color: #93C5FD; }
QRadioButton#answerOption:checked { background: #EFF6FF; border: 2px solid #2563EB; color: #1E3A8A; }
QRadioButton::indicator { width: 18px; height: 18px; }

QProgressBar { border: none; background: #E2E8F0; border-radius: 5px; height: 9px; text-align: center; }
QProgressBar::chunk { background: #2563EB; border-radius: 5px; }
QTableWidget { background: #FFFFFF; border: 1px solid #E2E8F0; border-radius: 10px; gridline-color: #F1F5F9; selection-background-color: #EFF6FF; selection-color: #0F172A; }
QTableWidget::item { padding: 7px; border-bottom: 1px solid #F1F5F9; }
QTableWidget::item:hover { background: #F8FAFC; }
QHeaderView::section { background: #F8FAFC; color: #64748B; border: none; border-bottom: 1px solid #E2E8F0; padding: 9px; font-size: 12px; font-weight: 700; }
QToolBox::tab { background: #FFFFFF; border: 1px solid #E2E8F0; border-radius: 8px; padding: 9px; font-weight: 600; }
QToolBox::tab:selected { background: #EFF6FF; color: #1D4ED8; border-color: #BFDBFE; }
QToolTip { background: #0F172A; color: #FFFFFF; border: none; border-radius: 5px; padding: 5px; }
QMenu { background: #FFFFFF; border: 1px solid #E2E8F0; border-radius: 8px; padding: 5px; }
QMenu::item { padding: 7px 22px 7px 10px; border-radius: 5px; }
QMenu::item:selected { background: #EFF6FF; color: #1D4ED8; }
QMessageBox { background: #FFFFFF; }
"""

STATUS_STYLES = {
    "WAITING": ("Chờ", "#FEF3C7", "#B45309"),
    "RUNNING": ("Đang diễn ra", "#E0F2FE", "#0369A1"),
    "ENDED": ("Đã kết thúc", "#F1F5F9", "#475569"),
    "correct": ("Đúng", "#DCFCE7", "#15803D"),
    "wrong": ("Sai", "#FEE2E2", "#B91C1C"),
    "easy": ("Dễ", "#DCFCE7", "#15803D"),
    "medium": ("Trung bình", "#FEF3C7", "#B45309"),
    "hard": ("Khó", "#FEE2E2", "#B91C1C"),
}
