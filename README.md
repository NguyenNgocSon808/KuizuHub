# KuizuHub – Online Exam TCP

KuizuHub là ứng dụng thi trắc nghiệm gồm server C99 chạy TCP và client desktop Python/PySide6. Giao thức chung là **NDJSON qua TCP**: mỗi bản tin là một JSON UTF-8, kết thúc bởi đúng một ký tự `\n`.

Phase 0 cung cấp một server skeleton đa client, migration SQLite, 30 câu hỏi seed và client TCP tối thiểu để kiểm tra `PING`. Các chức năng đăng nhập, phòng thi và GUI dùng dữ liệu thật sẽ được triển khai ở các phase sau.

## Yêu cầu trên Ubuntu 24.04

```bash
sudo apt update
sudo apt install -y build-essential libsqlite3-dev libssl-dev python3 python3-venv
python3 -m venv client/.venv
client/.venv/bin/pip install -r client/requirements.txt
```

`sqlite3` CLI không bắt buộc: script khởi tạo dùng module `sqlite3` có sẵn của Python.

## Chạy Phase 0 trên Windows (PowerShell)

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

Mở GUI PySide6 (GUI hiện vẫn dùng dữ liệu mock ở Phase 0):

```powershell
python -m pip install -r requirements.txt
python main.py
```

## Chạy Phase 0 trên Ubuntu 24.04

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

Kết quả mong đợi là response `OK` với `data.message` bằng `pong`. GUI mock vẫn chạy độc lập bằng `python3 main.py`; nó chưa được nối vào backend thật ở Phase 0.

## Kiểm thử

```bash
make test
python3 -m pytest client/tests -q
```

`make test` build server và chạy các kiểm thử TCP integration cho bản tin bị chia nhỏ, nhiều bản tin trong một lần gửi, và JSON lỗi.

## Cấu trúc quan trọng

- `server/src/main.c`: TCP server skeleton NDJSON, port mặc định 5050.
- `server/migrations/001_initial.sql`: schema SQLite ban đầu.
- `server/seed/questions.json`: 30 câu hỏi seed hợp lệ.
- `scripts/init_db.sh`: tái tạo `server/data/exam.db` từ migration và seed.
- `docs/protocol.md`, `docs/database.md`: hợp đồng tích hợp.

Không commit database cục bộ, `.venv`, binary, object file hoặc log server.
