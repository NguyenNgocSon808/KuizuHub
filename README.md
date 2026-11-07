# KuizuHub – Online Exam System

Repository này gồm phần server C đang phát triển và frontend desktop mock độc lập cho demo giao diện.

## Frontend mock (PySide6)

Chạy ở thư mục gốc:

```bash
pip install -r requirements.txt
python main.py
```

Xem hướng dẫn đầy đủ, tài khoản demo, kiểm thử và lộ trình thay bằng TCP C server tại [client/README.md](client/README.md).

Phiên bản frontend hiện tại **không** tạo kết nối socket hay phụ thuộc backend; dữ liệu mock JSON được tách sau service layer.
