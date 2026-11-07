# KuizuHub desktop mock frontend

Phiên bản này là frontend PySide6 độc lập: không mở TCP socket, không chạy C server và không cần database. Tất cả thao tác sử dụng `MockApiService`, lưu thay đổi demo ở `client/data/mock_state.json`.

## Chạy

Từ thư mục gốc repository (Python 3.12+):

```bash
python -m venv .venv
.venv\Scripts\activate        # Windows PowerShell
pip install -r requirements.txt
python main.py
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

## Thay bằng C TCP server sau này

Màn hình chỉ gọi service layer. Giữ API tương thích với `MockApiService`, hiện thực `NetworkClient` bằng worker thread và NDJSON (`\n`-delimited), rồi inject client đó vào `MainWindow` thay cho `MockApiService`. `NetworkClient` hiện là stub rõ ràng, nên frontend này không vô tình mở kết nối mạng trong phiên bản mock.
