# Kế hoạch triển khai Online Exam TCP cho 3 người

## 1. Mục tiêu và nguyên tắc chốt

Xây dựng ứng dụng thi trắc nghiệm chạy trên Ubuntu 24.04. Server viết bằng C, dùng TCP socket thật và cho phép nhiều client cùng kết nối. Client là ứng dụng desktop Python + PySide6, giao tiếp trực tiếp với server qua TCP. Dữ liệu lưu bằng SQLite.

**Không dùng browser/Vue kết nối TCP trực tiếp.** Browser không mở được raw TCP socket; nếu chọn web sẽ phải thêm WebSocket gateway và làm tăng độ phức tạp. Chỉ đổi sang web khi cả nhóm chủ động muốn làm Node gateway riêng.

Mục tiêu demo cuối cùng:

1. Ba client đăng nhập bằng ba tài khoản khác nhau.
2. Chủ phòng tạo phòng với chủ đề, độ khó, số câu và thời gian.
3. Hai thí sinh tham gia khi phòng ở trạng thái chờ.
4. Chủ phòng bắt đầu; mọi thí sinh nhận đề, đổi đáp án được và thấy đồng hồ do server quyết định.
5. Một thí sinh nộp sớm, một thí sinh để hết giờ.
6. Server chấm, lưu lịch sử, hiện kết quả và biểu đồ.
7. Thử gửi request trái quyền để chứng minh server từ chối.

## 2. Stack cố định

| Thành phần | Lựa chọn | Lý do |
|---|---|---|
| Server | C99, POSIX TCP socket, `pthread` | Đáp ứng đúng trọng tâm Lập trình mạng |
| Giao thức | NDJSON qua TCP | Dễ debug, giải quyết rõ xử lý truyền dòng |
| Lưu trữ | SQLite3 | Một file DB, gọn cho demo nhiều client |
| JSON phía C | cJSON được đặt trong `server/third_party/` | Không phụ thuộc runtime bên ngoài |
| Password | PBKDF2-HMAC-SHA256 qua OpenSSL | Không lưu mật khẩu dạng rõ |
| Client GUI | Python 3 + PySide6 + matplotlib | Desktop TCP client trực tiếp, đủ GUI và biểu đồ |
| Kiểm thử | `pytest` cho client, shell/Python integration tests | Lặp lại được khi demo/chấm |

Các gói Ubuntu cần ghi trong README:

```bash
sudo apt update
sudo apt install -y build-essential libsqlite3-dev libssl-dev python3 python3-venv
python3 -m venv client/.venv
client/.venv/bin/pip install -r client/requirements.txt
```

## 3. Quy ước làm việc bắt buộc

### 3.1 Nhánh Git

| Người | Nhánh chính | Chỉ sở hữu chính |
|---|---|---|
| Người 1 | `feature/server-core-auth` | `server/src/core`, `server/src/auth`, `server/src/protocol`, `server/src/log` |
| Người 2 | `feature/exam-room-flow` | `server/src/room`, `server/src/exam`, `server/src/practice` |
| Người 3 | `feature/gui-question-analytics` | toàn bộ `client/`, `server/src/question`, `server/src/history` |

- Không sửa file thuộc người khác nếu chưa thống nhất qua issue/nhóm chat.
- Mỗi Pull Request phải có: mô tả, cách chạy, ảnh hoặc log test, và danh sách request protocol đã thêm/sửa.
- Mọi request mới phải được bổ sung vào `docs/protocol.md` trước hoặc cùng PR.
- Không commit file database thật, password, token, `.venv`, file build hay binary.

### 3.2 Quy tắc server authoritative

- Client chỉ hiển thị; server quyết định thời gian, quyền, trạng thái phòng và điểm.
- Server tuyệt đối không gửi `correct_option_id` trước khi attempt đã kết thúc.
- Một request không hợp lệ luôn có response JSON lỗi, không làm server crash.
- Mọi thay đổi trạng thái quan trọng phải được ghi `activity_logs`.

### 3.3 Chuẩn truyền dòng TCP

Mỗi bản tin là **một JSON UTF-8, kết thúc bằng đúng một `\n`**.

```json
{"type":"LOGIN","request_id":"8f01","payload":{"username":"vuong","password":"Example123"}}
```

Không được giả định một lần `recv()` nhận đúng một bản tin. Server/client phải:

1. Nhận byte vào buffer của connection.
2. Tách từng đoạn kết thúc bởi `\n`.
3. Parse từng dòng hoàn chỉnh; giữ phần dở dang cho lần nhận sau.
4. Xử lý được nhiều dòng JSON trong cùng một `recv()`.
5. Từ chối dòng dài hơn 64 KB và JSON sai định dạng.
6. Dùng `send_all()` để gửi đủ toàn bộ response.

## 4. Cấu trúc thư mục đích

```text
online-exam/
├── server/
│   ├── include/
│   ├── src/
│   │   ├── main.c
│   │   ├── core/                 # Người 1
│   │   ├── protocol/             # Người 1
│   │   ├── auth/                 # Người 1
│   │   ├── log/                  # Người 1
│   │   ├── room/                 # Người 2
│   │   ├── exam/                 # Người 2
│   │   ├── practice/             # Người 2
│   │   ├── question/             # Người 3
│   │   └── history/              # Người 3
│   ├── migrations/
│   ├── seed/questions.json
│   ├── tests/
│   └── Makefile
├── client/
│   ├── app.py
│   ├── network/
│   ├── models/
│   ├── views/
│   ├── widgets/
│   ├── tests/
│   └── requirements.txt
├── docs/
│   ├── protocol.md
│   ├── database.md
│   ├── demo-script.md
│   └── test-plan.md
├── scripts/
│   ├── init_db.sh
│   └── run_three_clients.sh
├── README.md
└── .gitignore
```

## 5. Chia điểm công bằng: 12 điểm kỳ vọng mỗi người

Phần bắt buộc trong rubric có 28 điểm tối đa. Nhóm chủ động làm thêm gói nâng cao 8 điểm, đưa tổng mục tiêu lên **36 điểm**, chia đều **12 điểm/người**. Điểm nâng cao cuối cùng do giảng viên quyết định, nhưng mỗi gói bên dưới phải được demo rõ ràng để có bằng chứng xin điểm.

| Người | Hạng mục rubric bắt buộc | Điểm bắt buộc | Gói nâng cao đề xuất | Điểm nâng cao | Tổng mục tiêu |
|---|---|---:|---|---:|---:|
| 1 – Core & Security | Truyền dòng 1; socket server 2; đăng ký 2; đăng nhập/phiên 2; access control 1; log 1 | 9 | Reliability & security: rate limit, validate payload, reconnect bằng token, test đồng thời 10 client | 3 | **12** |
| 2 – Exam Flow | Luyện tập 1; tạo phòng 2; list phòng 1; vào phòng 2; bắt đầu 1; đổi đáp án 1; nộp/chấm 2; kết quả phòng 1 | 11 | Push sự kiện realtime phòng chờ/bắt đầu/kết thúc | 1 | **12** |
| 3 – Questions & GUI | Phân loại câu hỏi 3; lưu lịch sử + biểu đồ 2; GUI 3 | 8 | CRUD ngân hàng câu hỏi + import/export CSV (2); leaderboard, hồ sơ và thành tích (2) | 4 | **12** |

> Không tính điểm bằng số lượng file. Mỗi người phải demo được luồng chức năng của mình trên build tích hợp cuối.

## 6. Hợp đồng dữ liệu chung

### 6.1 Trạng thái

```text
Room: WAITING -> RUNNING -> ENDED
Attempt: JOINED -> IN_PROGRESS -> SUBMITTED | AUTO_SUBMITTED
```

- Chỉ owner của room được `START_ROOM` và `END_ROOM`.
- Chỉ room `WAITING` mới cho `JOIN_ROOM`.
- Khi `START_ROOM`, server chọn câu hỏi và tạo snapshot; sau đó ngân hàng câu hỏi thay đổi không ảnh hưởng đề đang thi.
- `ended_at` lấy từ server. Client chỉ tính countdown để hiển thị.
- Khi hết giờ, server chấm những đáp án đã lưu, kể cả thí sinh chưa bấm nộp.

### 6.2 Schema SQLite tối thiểu

| Bảng | Cột bắt buộc / mục đích |
|---|---|
| `users` | `id`, `username UNIQUE`, `password_hash`, `role`, `created_at` |
| `sessions` | `token_hash`, `user_id`, `expires_at`, `revoked_at` |
| `questions` | `id`, `content`, `topic`, `difficulty`, `correct_option_id`, `is_active` |
| `question_options` | `id`, `question_id`, `label`, `content`, `position` |
| `exam_rooms` | `id`, `owner_id`, `name`, `status`, `duration_seconds`, `started_at`, `ended_at` |
| `room_question_rules` | `room_id`, `topic`, `difficulty`, `quantity` |
| `room_questions` | snapshot `room_id`, `question_id`, `position`, `content_snapshot`, `correct_option_snapshot` |
| `room_participants` | `room_id`, `user_id`, `state`, `submitted_at`, `score`, `correct_count` |
| `attempt_answers` | `room_id`, `user_id`, `question_id`, `selected_option_id`, `updated_at` |
| `practice_attempts` | lịch sử luyện tập, điểm, thời gian, cấu hình |
| `activity_logs` | `id`, `actor_id`, `action`, `entity_type`, `entity_id`, `detail_json`, `created_at` |

Tạo indexes cho `users(username)`, `sessions(token_hash)`, `exam_rooms(status)`, `room_participants(room_id,user_id)` và `attempt_answers(room_id,user_id,question_id)`.

## 7. Giao thức tối thiểu

Mọi request có dạng:

```json
{
  "type": "REQUEST_NAME",
  "request_id": "uuid-or-counter",
  "token": "optional-session-token",
  "payload": {}
}
```

Response thành công:

```json
{"type":"OK","request_id":"...","data":{}}
```

Response lỗi:

```json
{"type":"ERROR","request_id":"...","error":{"code":"FORBIDDEN","message":"Only the room owner can start this room"}}
```

| Request | Owner | Điều kiện chính |
|---|---|---|
| `REGISTER`, `LOGIN`, `LOGOUT` | Người 1 | password policy, không trả hash/token log |
| `LIST_ROOMS`, `GET_MY_PROFILE` | Người 1 | token hợp lệ |
| `CREATE_ROOM`, `JOIN_ROOM`, `START_ROOM`, `END_ROOM` | Người 2 | role + room state + owner |
| `GET_EXAM`, `SAVE_ANSWER`, `SUBMIT_EXAM`, `GET_ROOM_RESULTS` | Người 2 | participant/owner đúng room |
| `START_PRACTICE`, `SAVE_PRACTICE_ANSWER`, `SUBMIT_PRACTICE` | Người 2 | user đã đăng nhập |
| `LIST_QUESTIONS`, `CREATE_QUESTION`, `UPDATE_QUESTION`, `IMPORT_QUESTIONS` | Người 3 | chỉ `ADMIN` hoặc quyền được quy định |
| `GET_MY_HISTORY`, `GET_MY_STATS`, `GET_LEADERBOARD` | Người 3 | chỉ dữ liệu người dùng có quyền xem |

Server event không có `request_id`:

```json
{"type":"EVENT_ROOM_STARTED","data":{"room_id":12,"ended_at":"2026-11-01T10:30:00Z"}}
```

Các event bắt buộc: `EVENT_PARTICIPANT_JOINED`, `EVENT_ROOM_STARTED`, `EVENT_ROOM_ENDED`, `EVENT_EXAM_AUTO_SUBMITTED`.

## 8. Kế hoạch theo phase

## Phase 0 – Chốt hợp đồng và khởi tạo (Ngày 1)

**Cả ba người cùng làm, không tính điểm riêng.**

- Tạo repository, `.gitignore`, README ban đầu, `docs/protocol.md`, `docs/database.md`.
- Chốt port mặc định `5050`, địa chỉ bind `0.0.0.0`, DB `server/data/exam.db`.
- Tạo Makefile có ít nhất `make`, `make run`, `make test`, `make clean`.
- Tạo migration `001_initial.sql` và seed ít nhất 30 câu: tối thiểu 3 topic, mỗi topic có easy/medium/hard.
- Định nghĩa response error chuẩn: `BAD_REQUEST`, `UNAUTHORIZED`, `FORBIDDEN`, `NOT_FOUND`, `CONFLICT`, `INTERNAL_ERROR`.

**Done khi:** clone mới trên Ubuntu chạy được `make && make run`; client skeleton mở được và ping server.

## Phase 1 – Nền tảng song song (Ngày 2–4)

### Người 1: Server core, protocol, auth

- Viết `server_socket.c`: `SO_REUSEADDR`, bind, listen, accept.
- Mỗi client có buffer nhận riêng; không dùng buffer toàn cục.
- Viết `connection_read_lines()` và `send_all()`.
- Viết dispatcher `handle_message(connection, json)` theo trường `type`.
- Đăng ký: validate username 3–32 ký tự, password tối thiểu 8 ký tự; username unique.
- Đăng nhập: PBKDF2 hash, sinh random token, chỉ lưu hash token trong DB.
- Session có hạn dùng; `LOGOUT` revoke session.
- Middleware `require_session()` và `require_room_owner()`.
- Log hoạt động vào DB và `server/logs/server.log`; cấm log password/token.

**Acceptance tests:**

```text
REGISTER thành công / username trùng bị CONFLICT
LOGIN sai password bị UNAUTHORIZED
LIST_ROOMS không token bị UNAUTHORIZED
1 JSON bị cắt thành 3 recv vẫn parse đúng
2 JSON dính cùng recv đều được xử lý
payload > 64 KB bị BAD_REQUEST, server tiếp tục phục vụ client khác
```

### Người 2: Engine luyện tập

- Implement chọn câu theo `topic`, `difficulty`, `question_count`.
- Nếu không đủ câu theo cấu hình: trả `CONFLICT` kèm số câu khả dụng, không tự giảm số lượng.
- `START_PRACTICE` tạo attempt riêng, trả câu hỏi và options nhưng không trả đáp án đúng.
- `SAVE_PRACTICE_ANSWER` là UPSERT; gọi lại cùng câu sẽ thay đáp án cũ.
- `SUBMIT_PRACTICE` chấm ở server, lưu `practice_attempts`, trả `correct_count`, `total`, `score`.

**Acceptance tests:** bắt đầu bài 10 câu, sửa một đáp án, nộp; điểm thay đổi đúng và lịch sử chỉ có một attempt.

### Người 3: Ngân hàng câu hỏi và khung GUI

- Viết repository/service CRUD questions và import seed JSON.
- Mỗi question bắt buộc có 4 options, chính xác một `correct_option_id`, topic, difficulty.
- Client tạo `TcpClient` chạy network I/O ở worker thread để GUI không bị treo.
- Tạo màn: Login/Register, Dashboard shell, thông báo lỗi/toast, widget loading.
- Tạo design tokens cố định: màu, spacing, font, button state; không để mỗi màn tự viết style rời rạc.

**Acceptance tests:** admin thêm/sửa/disable question; GUI đăng ký/đăng nhập và hiển thị dashboard không block khi server phản hồi chậm.

## Phase 2 – Phòng thi và giao diện thi (Ngày 5–8)

### Người 2: Room lifecycle và scoring

- `CREATE_ROOM`: tên, duration, rule topic/difficulty/quantity; trạng thái `WAITING`.
- `LIST_ROOMS`: trả `id`, `name`, `owner_name`, `status`, participant count, duration.
- `JOIN_ROOM`: transaction kiểm tra state còn `WAITING`, không tạo bản ghi trùng.
- `START_ROOM`: transaction kiểm tra owner + đủ câu; snapshot câu hỏi vào `room_questions`; set `started_at`, `ended_at`, `RUNNING`.
- `GET_EXAM`: chỉ participant room `RUNNING`; trả snapshots không có đáp án đúng.
- `SAVE_ANSWER`: chỉ room `RUNNING`, before `ended_at`, UPSERT đáp án.
- `SUBMIT_EXAM`: transaction lock attempt, chấm từ snapshot, set `SUBMITTED`; phải idempotent.
- Timer worker chạy mỗi giây hoặc mỗi 2 giây: tìm room quá `ended_at`, auto-submit tất cả chưa nộp, set `ENDED`.
- `GET_ROOM_RESULTS`: owner xem toàn bộ; student chỉ xem kết quả của chính mình sau `ENDED`.

**Acceptance tests:**

```text
Student không join không GET_EXAM được
Student cố START_ROOM nhận FORBIDDEN
Room RUNNING không JOIN_ROOM được
SAVE_ANSWER sau ended_at bị CONFLICT
SUBMIT_EXAM lần hai trả cùng kết quả, không chấm/lưu lần hai
Timer tự chấm người không nộp
```

### Người 3: Các màn thi và kết quả

- Room list có badge `Chưa bắt đầu / Đang diễn ra / Đã kết thúc`.
- Form tạo phòng có validation đúng rule câu hỏi.
- Waiting room hiển thị người đã vào; nút Start chỉ hiện cho owner.
- Exam view: một câu/màn hoặc danh sách; navigator số câu; đáp án đã chọn; timer; nút submit có confirm dialog.
- Autosave câu trả lời sau mỗi lần chọn; hiển thị trạng thái “Đã lưu”.
- Result screen: đúng/tổng, phần trăm, thời điểm nộp, các câu đúng/sai chỉ hiển thị sau khi room kết thúc.

**Done khi:** ba client thực hiện được đầy đủ demo ở phần Mục tiêu.

### Người 1: Reliability package

- Rate limit tối thiểu cho LOGIN, ví dụ 5 lần/phút/IP hoặc/username.
- Validate field type/length cho tất cả request trước khi service xử lý.
- Cho phép client reconnect bằng session token và lấy lại trạng thái qua `GET_MY_ACTIVE_EXAM`.
- Viết script stress test 10 client cùng `LOGIN`/`LIST_ROOMS`; server không chết, DB không corrupt.
- Ghi connection open/close, lỗi protocol và access denied vào log.

## Phase 3 – Lịch sử, biểu đồ và nâng cao (Ngày 9–11)

### Người 3: Analytics và advanced 4 điểm

- `GET_MY_HISTORY`: phân trang lịch sử practice/exam của user.
- `GET_MY_STATS`: số bài, điểm trung bình, tỷ lệ đúng theo topic và difficulty, chuỗi ngày học.
- Màn History và Stats dùng matplotlib: line chart điểm theo thời gian + bar chart đúng theo topic.
- CRUD question admin hoàn chỉnh: create, edit, activate/disable, filter topic/difficulty.
- Import/export CSV có validate hàng lỗi và báo lỗi cụ thể.
- Leaderboard theo điểm và thời gian nộp, chỉ công bố cho room `ENDED`.
- Profile: đổi display name/password, hiển thị thành tích đơn giản như “5 bài liên tiếp”.

### Người 1 và Người 2: hỗ trợ tích hợp

- Người 1 review permission cho toàn bộ request do Người 3 thêm.
- Người 2 bảo đảm lịch sử được ghi đúng lúc submit/auto-submit.
- Cả ba chạy migration mới từ database rỗng trước khi merge.

## Phase 4 – Kiểm thử, đóng gói và rehearsal (Ngày 12–14)

1. Chạy static checks/compiler warnings: `-Wall -Wextra -Werror -pedantic`.
2. Test protocol với JSON bị cắt/dính/sai/thiếu field.
3. Test quyền với host, student, user lạ và session hết hạn.
4. Test hai phòng cùng chạy, mỗi phòng nhiều thí sinh.
5. Test client đóng giữa chừng, reconnect, submit sau reconnect.
6. Chạy demo LAN bằng hai máy Ubuntu nếu có thể.
7. Quay video dự phòng 3–5 phút, nhưng demo trực tiếp vẫn là chính.
8. Mỗi người chuẩn bị phần trình bày và một test case lỗi để chứng minh feature có kiểm soát.

## 9. Definition of Done cho Codex agent

Codex phải coi một feature hoàn thành chỉ khi có đủ tất cả điều sau:

- Code biên dịch/running không warning mới.
- Đã cập nhật `docs/protocol.md` nếu thêm/sửa message.
- Đã có SQL migration hoặc seed tương ứng nếu đổi dữ liệu.
- Không lộ password, password hash, token hay correct answer trong log/response sai đối tượng.
- Có test unit/integration tối thiểu hoặc script tái hiện.
- Error response dùng đúng mã lỗi chuẩn, không `printf` rồi bỏ qua lỗi.
- UI không freeze khi đợi socket; network I/O không chạy ở main GUI thread.
- Đã tự chạy scenario happy path và ít nhất một scenario bị từ chối quyền.

## 10. Checklist demo chấm điểm

### Người 1

- [ ] Mở server, hiện log listening port.
- [ ] Demonstrate split JSON và multiple JSON messages bằng test script.
- [ ] Đăng ký, đăng nhập, logout, session hết hạn.
- [ ] Dùng token của student gọi `START_ROOM` và nhận `FORBIDDEN`.
- [ ] Hiện log `LOGIN_SUCCESS`, `ACCESS_DENIED`, `CONNECTION_CLOSED`.
- [ ] Chạy stress test 10 client.

### Người 2

- [ ] Tạo room 10 câu, 10 phút.
- [ ] Hai user join trước start; user thứ ba bị chặn sau start.
- [ ] Start room, cả hai client nhận cùng số câu.
- [ ] Đổi đáp án câu 1, submit sớm một client.
- [ ] Rút ngắn thời gian test để timer auto-submit client còn lại.
- [ ] Owner xem results; student chỉ xem own result.

### Người 3

- [ ] Lọc question theo Java/Network và easy/medium/hard.
- [ ] Hiển thị toàn bộ luồng GUI từ login tới result.
- [ ] Hiển thị History, line chart và bar chart.
- [ ] Import CSV có một row lỗi, báo row đó; export thành công.
- [ ] Hiện leaderboard sau room ENDED.

## 11. Rủi ro và cách tránh

| Rủi ro | Cách xử lý |
|---|---|
| Ba người code lệch protocol | `docs/protocol.md` là nguồn đúng duy nhất, review trước merge |
| SQLite locked khi nhiều thread ghi | DB wrapper dùng busy timeout, transaction ngắn, mutex cho thao tác write |
| Client freeze khi server chậm | worker thread + signal/slot PySide6 |
| Thời gian demo hết nhanh | Có seed account, seed question, script reset DB và demo room 60 giây |
| Feature đẹp nhưng không có socket thật | Mọi thao tác dữ liệu đi qua TCP C server, không mock local JSON |
| Không đủ câu theo filter | Server báo lỗi cụ thể ngay khi create/start room |
| Merge conflict UI/backend | Không dùng response tự do; bám schema protocol đã chốt |

## 12. Prompt làm việc ngắn cho Codex trong repository

```text
Bạn đang làm trong dự án Online Exam TCP.
Đọc README.md, docs/protocol.md, docs/database.md và tài liệu kế hoạch trước khi sửa code.

Ràng buộc không được phá vỡ:
- Server C99 chạy Ubuntu 24.04, TCP NDJSON, SQLite.
- TCP là byte stream: luôn buffer theo connection, tách theo newline, send_all.
- Server là nguồn quyết định quyền, thời gian, trạng thái và điểm.
- Không gửi đáp án đúng trước khi bài thi kết thúc.
- Không thay đổi schema request/response nếu chưa cập nhật docs/protocol.md.
- Không sửa code thuộc feature khác nếu không cần; ưu tiên thay đổi nhỏ, rõ ràng.
- Mọi feature phải có test/command tái hiện và phải build không warning mới.

Nhiệm vụ hiện tại: <DAN_TASK_CU_THE_O_DAY>
Trước khi code, hãy nêu file sẽ sửa, contract liên quan, edge cases và test sẽ chạy.
Sau khi code, chạy build/test, báo đúng các file đã thay đổi và kết quả.
```

## 13. Tiêu chí nộp cuối

- `make clean && make` thành công trên Ubuntu 24.04.
- `README.md` có setup, dependency, port, lệnh chạy server/client/test và tài khoản demo.
- Có database/migration/seed tái tạo được từ đầu.
- Có `scripts/reset_demo.sh` để reset dữ liệu demo.
- Không nộp binary, object file, database chứa dữ liệu riêng, `.venv`.
- Có sơ đồ kiến trúc và protocol trong `docs/`.
- Ít nhất một script tự động kiểm thử luồng login -> tạo/join/start -> answer -> submit -> result.
