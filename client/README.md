# KuizuHub desktop client

Desktop client PySide6 kết nối trực tiếp tới TCP/NDJSON server. Entry point dùng `LiveMainWindow`; luồng chạy chính không đọc `MockApiService` hay dữ liệu mock. `NetworkClient` giữ socket NDJSON persistent và `PhaseOneApiService` đặt mọi network I/O trong một `QThread`, nên UI không bị block khi server phản hồi chậm.

## Chạy

Từ thư mục gốc repository (Python 3.12+):

```bash
python -m venv .venv
.venv\Scripts\activate        # Windows PowerShell
pip install -r requirements.txt
python main.py
```

Sau khi chạy server bằng `mingw32-make run` (Windows) hoặc `make run` (Unix) ở thư mục gốc, có thể kiểm tra giao thức thật:

```bash
python3 client/ping_client.py
```

Trên macOS/Linux, kích hoạt bằng `source .venv/bin/activate`.

## Tài khoản

| Vai trò | Username | Password |
|---|---|---|
| Quản trị câu hỏi | Đăng ký từ GUI với role `ADMIN` | Mật khẩu tối thiểu 8 ký tự |
| Chủ phòng / thí sinh | Đăng ký từ GUI với role tương ứng | Mật khẩu tối thiểu 8 ký tự |

Tài khoản/dữ liệu mock cũ trong `client/data/` không được dùng bởi entry point hiện tại.

## Kiểm thử

```bash
python -m pytest client/tests -q
```

## Cấu trúc

```
main.py                                      entry point
client/app/services/network_client.py        TCP NDJSON persistent transport
client/app/services/tcp_api_service.py       QThread API service
client/app/ui/live_main_window.py            Workspace Phase 2–3 dùng server thật
client/app/ui/phase1_main_window.py          Auth/Dashboard/Question Bank thật, được tái sử dụng
client/app/ui/                               legacy mock pages và shared widgets
client/data/                                 dữ liệu mock cũ
client/tests/                                unit tests service/transport
```

## Phạm vi giao diện hiện tại

- `REGISTER`, `LOGIN`, `LOGOUT`, `GET_MY_PROFILE`, `UPDATE_MY_PROFILE` qua TCP.
- Admin có thể list, tạo, sửa, disable/enable, import JSON/CSV và xuất CSV câu hỏi.
- Chủ phòng tạo/bắt đầu phòng; thí sinh join, xem sảnh chờ, làm bài với autosave và đồng hồ theo hạn server.
- Có luyện tập, lịch sử, thống kê theo chủ đề/độ khó, streak, kết quả phòng và leaderboard.

Có thể đổi địa chỉ server bằng `KUIZUHUB_HOST` và `KUIZUHUB_PORT` trước khi chạy `python main.py`.
