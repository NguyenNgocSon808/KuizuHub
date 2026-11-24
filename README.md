# KuizuHub – Online Exam TCP

KuizuHub là ứng dụng thi trắc nghiệm gồm server C99 chạy TCP và client desktop Python/PySide6. Giao thức chung là **NDJSON qua TCP**: mỗi bản tin là một JSON UTF-8, kết thúc bởi đúng một ký tự `\n`.

Phase 0 cung cấp server TCP, migration SQLite, 30 câu hỏi seed và kiểm tra `PING`. Phase 1 hiện đã có xác thực/session, protocol NDJSON, activity log, ngân hàng câu hỏi quản trị và GUI PySide6 kết nối TCP thật cho Register, Login, Dashboard và Question Bank. Gói Reliability & Security (Phase 2 – Người 1) cũng đã được tích hợp trên server gồm: giới hạn số lần đăng nhập sai (Rate Limiting), khôi phục bài thi khi mất kết nối (`GET_MY_ACTIVE_EXAM`), timeout nhàn rỗi cho socket (`SO_RCVTIMEO`, cấu hình qua `KUIZUHUB_IDLE_TIMEOUT_SEC`) và bộ kiểm thử tải đồng thời. Phòng thi, luyện tập, lịch sử và analytics vẫn thuộc phần còn lại của Phase 2–3 nên không được giả lập là dữ liệu thật trong GUI Phase 1.

## Yêu cầu trên Ubuntu 24.04

```bash
sudo apt update
sudo apt install -y build-essential libsqlite3-dev libssl-dev python3 python3-venv
python3 -m venv client/.venv
client/.venv/bin/pip install -r client/requirements.txt
```

`sqlite3` CLI không bắt buộc: script khởi tạo dùng module `sqlite3` có sẵn của Python.

## Chạy Phase 1 trên Windows (PowerShell)

Từ thư mục gốc repository, khởi tạo database và build server:

```powershell
python scripts/seed_db.py --reset
mingw32-make
```

Chạy server ở terminal thứ nhất (lệnh này giữ terminal mở):

```powershell
mingw32-make run
```

Server mặc định lắng nghe tại `0.0.0.0:5050`. Mở terminal thứ hai để kiểm tra client TCP skeleton:

```powershell
python client/ping_client.py
```

Kết quả mong đợi:

```json
{"type":"OK","request_id":"phase0-ping","data":{"message":"pong"}}
```

Nếu port `5050` đang được dùng, chạy cùng một port ở cả hai lệnh:

```powershell
mingw32-make run PORT=5051
python client/ping_client.py --port 5051
```

Mở GUI PySide6 kết nối TCP thật:

```powershell
python -m pip install -r requirements.txt
python main.py
```

GUI mặc định kết nối `127.0.0.1:5050`. Nếu đổi port/host, đặt cùng biến môi trường trước khi chạy GUI:

```powershell
$env:KUIZUHUB_HOST = "127.0.0.1"
$env:KUIZUHUB_PORT = "5051"
python main.py
```

Đăng ký một tài khoản có vai trò `ADMIN` trong màn đăng ký để nghiệm thu ngân hàng câu hỏi. Quy tắc role hiện theo contract `REGISTER` trong `docs/protocol.md`.

## Chạy Phase 1 trên Ubuntu 24.04

Từ thư mục gốc repository:

```bash
bash scripts/init_db.sh
make
make run
```

Server mặc định lắng nghe tại `0.0.0.0:5050`; có thể đổi port bằng `make run PORT=5051`.

Ở terminal khác, kiểm tra client TCP skeleton:

```bash
python3 client/ping_client.py
```

Kết quả mong đợi là response `OK` với `data.message` bằng `pong`. GUI chạy bằng `python3 main.py` và kết nối đến server thật qua TCP.

## Kiểm thử

```bash
make test
python3 -m pytest client/tests -q
```

`make test` (hoặc `mingw32-make test` trên Windows) build server và chạy toàn bộ 20 kiểm thử TCP tích hợp cho: framing cắt/dính gói và giới hạn 64 KB, auth/session, ngân hàng câu hỏi (migration nâng cấp DB cũ, phân quyền ADMIN, create/list/update/disable, import atomic) và gói Reliability (`server/tests/test_phase2_reliability.py`: rate limiting đăng nhập sai, kiểm soát quyền chủ phòng, reconnect `GET_MY_ACTIVE_EXAM`, stress test 15 client đồng thời và idle socket timeout). Test client kiểm tra persistent TCP NDJSON với response bị chia nhỏ.

## Cấu trúc quan trọng

- `server/src/main.c`, `server/src/core/server_socket.c`: TCP server NDJSON đa luồng, port mặc định 5050, hỗ trợ `SO_RCVTIMEO` (`KUIZUHUB_IDLE_TIMEOUT_SEC`, mặc định 300s).
- `server/src/auth/auth.c`: Đăng ký/đăng nhập PBKDF2, quản lý session token hash, Rate Limiting cho `LOGIN`, middleware phân quyền và `GET_MY_ACTIVE_EXAM`.
- `server/src/question/question.c`: CRUD/import ngân hàng câu hỏi chỉ dành cho ADMIN.
- `server/migrations/001_initial.sql`, `server/migrations/002_question_explanation.sql`: schema và migration Phase 1.
- `server/seed/questions.json`: 30 câu hỏi seed hợp lệ.
- `server/tests/test_phase2_reliability.py`: bộ kiểm thử tự động framing, rate limit, phân quyền, reconnect, stress test 15 client và idle timeout.
- `scripts/init_db.sh`: tái tạo `server/data/exam.db` từ migration và seed.
- `client/app/services/tcp_api_service.py`: worker `QThread` chạy TCP ngoài UI thread.
- `client/app/ui/phase1_main_window.py`: các màn Phase 1 dùng API thật.
- `docs/protocol.md`, `docs/database.md`: hợp đồng tích hợp.

Không commit database cục bộ, `.venv`, binary, object file hoặc log server.
