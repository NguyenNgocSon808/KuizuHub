import sys

from PySide6.QtCore import QTimer
from PySide6.QtGui import QColor, QPixmap
from PySide6.QtWidgets import QApplication, QSplashScreen

from .services import MockApiService
from .ui.modern_main_window import MainWindow
from .ui.design import APP_QSS


def run() -> None:
    application = QApplication(sys.argv)
    application.setStyleSheet(APP_QSS)
    pixmap = QPixmap(420, 220); pixmap.fill(QColor("#102a43"))
    splash = QSplashScreen(pixmap); splash.showMessage("KuizuHub\nĐang chuẩn bị không gian thi…", 0x84, QColor("white")); splash.show()
    service = MockApiService(); window = MainWindow(service)
    QTimer.singleShot(700, lambda: (window.show(), splash.finish(window)))
    sys.exit(application.exec())
