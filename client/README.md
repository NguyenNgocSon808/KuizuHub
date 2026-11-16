# KuizuHub desktop client

GUI mặc định là giao diện Phase 1 dùng TCP server thật cho Register, Login, Dashboard và Question Bank. `NetworkClient` giữ socket NDJSON persistent; `PhaseOneApiService` đặt mọi network I/O trong một `QThread`, vì vậy UI không bị block khi server phản hồi chậm.

## Chạy

Từ thư mục gốc repository (Python 3.12+):

```bash
python -m venv .venv
.venv\Scripts\activate        # Windows PowerShell
pip install -r requirements.txt
python main.py
```

Sau khi chạy server bằng `make run` ở thư mục gốc, kiểm tra giao thức thật:

```bash
python3 client/ping_client.py
```

Trên macOS/Linux, kích hoạt bằng `source .venv/bin/activate`.

## Tài khoản

| Vai trò | Username | Password |
|---|---|---|
| Quản trị câu hỏi | Đăng ký từ GUI với role `ADMIN` | Mật khẩu tối thiểu 8 ký tự |
| Chủ phòng / thí sinh | Đăng ký từ GUI với role tương ứng | Mật khẩu tối thiểu 8 ký tự |

Tài khoản mock cũ trong `client/data/` không được dùng bởi entry point Phase 1.

## Kiểm thử

```bash
python -m pytest client/tests -q
```

## Cấu trúc

```
main.py                                      entry point
client/app/services/network_client.py        TCP NDJSON persistent transport
client/app/services/tcp_api_service.py       QThread API service
client/app/ui/phase1_main_window.py          Register/Login/Dashboard/Question Bank thật
client/app/ui/                               legacy mock pages và shared widgets
client/data/                                 dữ liệu mock cũ
client/tests/                                unit tests service/transport
```

## Phạm vi Phase 1

- `REGISTER`, `LOGIN`, `LOGOUT`, `GET_MY_PROFILE` qua TCP.
- Admin có thể list, tạo, sửa, disable/enable và import JSON câu hỏi.
- Room, practice, history và analytics chờ API của các phase sau; GUI Phase 1 không hiển thị dữ liệu mock cho các luồng này.

Có thể đổi địa chỉ server bằng `KUIZUHUB_HOST` và `KUIZUHUB_PORT` trước khi chạy `python main.py`.
