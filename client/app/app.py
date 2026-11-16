import sys

from PySide6.QtCore import QTimer
from PySide6.QtGui import QColor, QPixmap
from PySide6.QtWidgets import QApplication, QSplashScreen

from .config import SERVER_HOST, SERVER_PORT
from .services.tcp_api_service import PhaseOneApiService
from .ui.phase1_main_window import PhaseOneMainWindow
from .ui.design import APP_QSS


def run() -> None:
    application = QApplication(sys.argv)
    application.setStyleSheet(APP_QSS)
    pixmap = QPixmap(420, 220); pixmap.fill(QColor("#102a43"))
    splash = QSplashScreen(pixmap); splash.showMessage("KuizuHub\nĐang kết nối TCP Phase 1…", 0x84, QColor("white")); splash.show()
    service = PhaseOneApiService(SERVER_HOST, SERVER_PORT)
    application.aboutToQuit.connect(service.close)
    window = PhaseOneMainWindow(service)
    QTimer.singleShot(700, lambda: (window.show(), splash.finish(window)))
    sys.exit(application.exec())
