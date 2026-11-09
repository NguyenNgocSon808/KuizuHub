# KuizuHub desktop client

GUI PySide6 hiện dùng `MockApiService` để demo màn hình. Phase 0 cũng có `NetworkClient` TCP/NDJSON và command-line client `ping_client.py` để kiểm tra kết nối tới C server; GUI sẽ được thay sang network worker ở Phase 1.

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

## Tài khoản demo

| Vai trò | Username | Password |
|---|---|---|
| Chủ phòng | `son` | `123456` |
| Thí sinh | `bao` | `123456` |
| Thí sinh | `vuong` | `123456` |

## Kiểm thử

```bash
python -m pytest client/tests -q
```

## Cấu trúc

```
main.py                       entry point
client/app/models/            dataclass User, Room, Question, Attempt
client/app/services/          MockApiService và NetworkClient stub
client/app/ui/                shell, pages, widgets, theme
client/data/                  dữ liệu seed JSON
client/tests/                 unit tests service
```

## Lộ trình nối GUI

Màn hình tiếp tục gọi service layer. `NetworkClient` đã thực hiện NDJSON cho PING; Phase 1 sẽ thêm worker thread, persistent connection, request correlation và Qt signals trước khi inject nó vào `MainWindow` thay cho `MockApiService`.
