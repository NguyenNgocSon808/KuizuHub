APP_QSS = """
* { font-family: 'Segoe UI', Arial; color: #182230; font-size: 14px; }
QMainWindow, QWidget#root, QScrollArea { background: #f5f7fb; }
QFrame#sidebar { background: #102a43; }
QLabel#brand { color: white; font-size: 22px; font-weight: 700; }
QLabel#sideUser, QLabel#sideRole { color: #d8e5f3; }
QLabel#pageTitle { font-size: 25px; font-weight: 700; color: #102a43; }
QLabel#subtle { color: #667085; }
QFrame#card, QFrame#metric, QFrame#roomCard { background: white; border: 1px solid #e5eaf1; border-radius: 12px; }
QFrame#metric { min-height: 90px; }
QLabel#metricValue { color: #146cdb; font-size: 25px; font-weight: 700; }
QLabel#metricLabel { color: #667085; }
QLineEdit, QComboBox, QSpinBox, QTextEdit { background: white; border: 1px solid #d0d9e5; border-radius: 7px; padding: 8px; min-height: 19px; }
QLineEdit:focus, QComboBox:focus, QTextEdit:focus { border: 2px solid #2f80ed; }
QPushButton { background: #2f80ed; color: white; border: none; border-radius: 7px; padding: 9px 14px; font-weight: 600; }
QPushButton:hover { background: #196dcc; }
QPushButton:disabled { background: #b8c2d1; }
QPushButton#secondary { background: #e8f1fe; color: #196dcc; }
QPushButton#danger { background: #e74c3c; }
QPushButton#nav { background: transparent; color: #d8e5f3; text-align: left; padding: 11px 16px; border-radius: 6px; }
QPushButton#nav:hover, QPushButton#nav:checked { background: #1f4e79; color: white; }
QTableWidget { background: white; border: 1px solid #e5eaf1; border-radius: 8px; gridline-color: #eef2f7; }
QHeaderView::section { background: #edf3fa; color: #475467; border: none; padding: 8px; font-weight: 700; }
QTabWidget::pane { border: 1px solid #e5eaf1; border-radius: 8px; background: white; }
QMessageBox { background: white; }
"""

STATUS_STYLES = {
    "WAITING": ("Chờ", "#fff3cd", "#a15c00"),
    "RUNNING": ("Đang diễn ra", "#dbeafe", "#1769aa"),
    "ENDED": ("Đã kết thúc", "#eceff3", "#596273"),
    "correct": ("Đúng", "#dcfce7", "#18794e"),
    "wrong": ("Sai", "#fee2e2", "#b42318"),
}

# Compatibility exports: the modern design system is the authoritative QSS.
from .design import APP_QSS, STATUS_STYLES  # noqa: E402,F401
