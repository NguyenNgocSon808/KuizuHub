import os
from pathlib import Path

APP_TITLE = "KuizuHub | Online Exam"
CLIENT_DIR = Path(__file__).resolve().parents[1]
DATA_DIR = CLIENT_DIR / "data"
WINDOW_MIN_WIDTH = 1100
WINDOW_MIN_HEIGHT = 720


def _server_port() -> int:
    try:
        port = int(os.environ.get("KUIZUHUB_PORT", "5050"))
    except ValueError:
        return 5050
    return port if 1 <= port <= 65535 else 5050


SERVER_HOST = os.environ.get("KUIZUHUB_HOST", "127.0.0.1").strip() or "127.0.0.1"
SERVER_PORT = _server_port()

# Shared visual tokens. Keep component code free from ad-hoc colors.
COLORS = {
    "primary": "#2563EB", "primary_hover": "#1D4ED8", "primary_light": "#DBEAFE",
    "background": "#F8FAFC", "surface": "#FFFFFF", "border": "#E2E8F0",
    "text": "#0F172A", "secondary": "#64748B", "muted": "#94A3B8",
    "success": "#16A34A", "success_light": "#DCFCE7", "warning": "#D97706",
    "warning_light": "#FEF3C7", "danger": "#DC2626", "danger_light": "#FEE2E2",
    "info": "#0284C7", "info_light": "#E0F2FE", "navy": "#0F2742",
}

TOPICS = ["Tất cả", "TCP Socket", "UDP", "DNS", "HTTP/HTTPS", "IP Address", "Port"]
DIFFICULTIES = ["Tất cả", "Dễ", "Trung bình", "Khó", "Trộn"]
ROOM_STATUSES = {"WAITING": "Chờ", "RUNNING": "Đang diễn ra", "ENDED": "Đã kết thúc"}
