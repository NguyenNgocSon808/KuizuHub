# KuizuHub – Online Exam TCP

KuizuHub là hệ thống thi trực tuyến dùng giao thức TCP/NDJSON: C99 + SQLite ở server và PySide6 ở desktop client. Toàn bộ màn hình đang dùng API server thật; dữ liệu mock chỉ còn là tài sản cũ, không nằm trên luồng chạy chính.

## Phạm vi đã hoàn thiện

- **Chặng 0–1:** khung TCP, đăng ký/đăng nhập, phân quyền và ngân hàng câu hỏi.
- **Chặng 2:** tạo/join/start phòng, sảnh chờ, đề thi được snapshot, autosave, đồng hồ theo server, nộp bài và xem kết quả sau khi phòng kết thúc; cùng gói **Reliability & Security** (Rate Limiting cho `LOGIN`, khôi phục bài thi khi mất kết nối `GET_MY_ACTIVE_EXAM`, timeout nhàn rỗi `SO_RCVTIMEO` cấu hình qua `KUIZUHUB_IDLE_TIMEOUT_SEC`).
- **Chặng 3:** luyện tập, lịch sử, thống kê theo chủ đề/độ khó, streak, leaderboard, hồ sơ cá nhân và nhập/xuất CSV câu hỏi.
- **Chặng 4 (đóng gói cốt lõi):** migration có thể lặp lại, seed/reset demo, kiểm thử backend và client, kịch bản demo.

## Yêu cầu

- Windows: Python 3.12+, MSYS2/MinGW-w64 có `gcc`, `make`, SQLite3 và OpenSSL.
- Ubuntu 24.04: `build-essential`, `libsqlite3-dev`, `libssl-dev`, `python3`, `python3-venv`.

Trên Ubuntu, cài một lần bằng:

```bash
sudo apt update
sudo apt install -y build-essential libsqlite3-dev libssl-dev python3 python3-venv
```

## Chạy nhanh

### Windows PowerShell

Từ thư mục gốc dự án, mở terminal cho server.

```powershell
if (-not (Test-Path server/data/exam.db)) { python scripts/seed_db.py }
mingw32-make run
```

Giữ terminal server mở. Trong một terminal khác ở thư mục gốc, tạo môi trường
client và cài thư viện một lần. Dùng Python 3.13 đã cài qua Python Launcher.

```powershell
py -3.13 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe main.py
```

Từ lần sau, chạy `mingw32-make run` ở terminal server và
`.\.venv\Scripts\python.exe main.py` ở terminal client.

### Ubuntu/macOS

```bash
bash scripts/reset_demo.sh  # chỉ chạy khi server đang dừng
make
make run
```

Mở terminal khác:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python3 main.py
```

Server mặc định bind `0.0.0.0:5050`; client mặc định kết nối `127.0.0.1:5050`. Có thể đổi địa chỉ client qua `KUIZUHUB_HOST` và `KUIZUHUB_PORT` trước khi chạy. Tạo tài khoản `HOST`, `STUDENT` và `ADMIN` trực tiếp ở màn đăng ký để demo các vai trò.

## Kiểm thử

```powershell
mingw32-make test
.\.venv\Scripts\python.exe -m pytest client/tests -q
```

Trên Unix chạy `make test` và `python -m pytest client/tests -q` trong môi trường ảo đã cài thư viện. Bộ kiểm thử server bao gồm framing, auth/session, ngân hàng câu hỏi, phòng thi, luyện tập, analytics và gói Reliability (`server/tests/test_phase2_reliability.py`: rate limiting, phân quyền chủ phòng, reconnect `GET_MY_ACTIVE_EXAM`, stress test 15 client đồng thời và idle socket timeout). Kế hoạch test và luồng trình diễn nằm tại [docs/test-plan.md](docs/test-plan.md) và [docs/demo-script.md](docs/demo-script.md).

## Reset dữ liệu demo

Chỉ dùng khi server đã dừng. Lệnh này xóa cơ sở dữ liệu runtime và tạo lại schema/seed.

```powershell
.\scripts\reset_demo.ps1
```

```bash
bash scripts/reset_demo.sh
```

## Cấu trúc chính

```text
server/                 server C11, SQLite, migration và test tích hợp
client/                 desktop client PySide6
docs/protocol.md        hợp đồng TCP/NDJSON
docs/database.md        schema, snapshot và migration
docs/test-plan.md       checklist kiểm thử
docs/demo-script.md     kịch bản demo
scripts/                seed và reset dữ liệu demo
```

Xem [client/README.md](client/README.md) để biết phạm vi giao diện, và [docs/protocol.md](docs/protocol.md) để tích hợp một client TCP khác.

admin: admin
       12345678
student: sinhvien
        12345678
chủ phòng: chuphong 
          12345678
