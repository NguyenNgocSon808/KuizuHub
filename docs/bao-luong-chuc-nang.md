# Luồng hoạt động các chức năng Bảo đã hoàn thành

> Phạm vi tài liệu: các API TCP NDJSON đã có code và test pass tại thời điểm
> cập nhật. Chức năng chưa hoàn thiện nổi bật là API xem kết quả sau khi room
> đã `ENDED`.

> **Ghi chú trạng thái 23/11/2026:** dòng trên là mô tả lịch sử. Luồng kết quả
> sau `ENDED` (`GET_ROOM_RESULTS`), sảnh chờ và các màn desktop TCP thật đã
> được tích hợp. Xem `docs/protocol.md` để lấy contract hiện hành và
> `docs/test-plan.md` để nghiệm thu.

## 1. Tổng quan kiến trúc

Client gửi mỗi request dưới dạng một JSON trên một dòng TCP (NDJSON):

```json
{"type":"<REQUEST_TYPE>","request_id":"<id>","token":"<token nếu cần>","payload":{}}
```

Server đọc request trong `server/src/core/server_socket.c`, kiểm tra kiểu
request rồi chuyển đến handler phù hợp. Các chức năng của Bảo dùng SQLite qua
`kz_db_lock()` để tránh các thao tác ghi đồng thời xung đột.

```text
Client PySide / netcat
        |
        | TCP NDJSON request
        v
server_socket.c (dispatcher)
        |
        +--> room.c     : CREATE_ROOM, JOIN_ROOM
        +--> auth.c     : LIST_ROOMS
        +--> practice.c : START_PRACTICE, SAVE_PRACTICE_ANSWER, SUBMIT_PRACTICE
        |
        v
SQLite: exam.db
```

Mọi API cần đăng nhập đều gọi `require_session()` trước. Token sai, thiếu,
đã logout hoặc hết hạn nhận response `UNAUTHORIZED`.

---

## 2. Chế độ luyện tập

### API liên quan

| API | Mục đích |
|---|---|
| `START_PRACTICE` | Tạo một phiên luyện tập và snapshot đề. |
| `SAVE_PRACTICE_ANSWER` | Lưu hoặc thay đổi một đáp án. |
| `SUBMIT_PRACTICE` | Chấm điểm và đóng phiên luyện tập. |

### 2.1. Bắt đầu luyện tập — `START_PRACTICE`

Request mẫu:

```json
{"type":"START_PRACTICE","request_id":"practice-start-001","token":"<session-token>","payload":{"topic":"TCP Socket","difficulty":"easy","question_count":3,"duration_seconds":600}}
```

Luồng server:

```text
1. Kiểm tra token/session.
2. Validate topic, difficulty, question_count (1-20), duration_seconds (60-7200).
3. Đếm số câu is_active = 1 đúng topic + difficulty.
4. Nếu không đủ câu: trả CONFLICT, không tạo phiên.
5. BEGIN IMMEDIATE.
6. Tạo practice_sessions ở state IN_PROGRESS.
7. Chọn ngẫu nhiên câu hỏi và snapshot câu hỏi, bốn lựa chọn, vị trí đáp án đúng.
8. COMMIT.
9. Trả attempt_id và đề cho client; response không chứa đáp án đúng.
```

Các bảng ghi dữ liệu:

| Bảng | Dữ liệu |
|---|---|
| `practice_sessions` | Chủ phiên, cấu hình, thời hạn và trạng thái. |
| `practice_session_questions` | Snapshot nội dung câu hỏi và đáp án đúng nội bộ server. |
| `practice_session_options` | Snapshot bốn lựa chọn của mỗi câu. |

Response thành công chứa `attempt_id` và `questions`. Client chỉ nhận `id`,
`position`, `content`, `options`; không nhận `correct_option_position`.

### 2.2. Lưu/thay đổi đáp án — `SAVE_PRACTICE_ANSWER`

Request mẫu:

```json
{"type":"SAVE_PRACTICE_ANSWER","request_id":"practice-save-001","token":"<session-token>","payload":{"attempt_id":1,"question_id":12,"selected_option_position":2}}
```

Luồng server:

```text
1. Kiểm tra session và xác minh attempt thuộc user hiện tại.
2. Kiểm tra attempt đang IN_PROGRESS và chưa quá ended_at.
3. Kiểm tra question_id và selected_option_position có trong snapshot.
4. UPSERT vào practice_answers.
5. Trả {"saved": true}.
```

Vì dùng UPSERT, user có thể chọn lại đáp án. Mỗi cặp
`(session_id, question_id)` chỉ có một đáp án cuối cùng.

### 2.3. Nộp và chấm bài — `SUBMIT_PRACTICE`

Request mẫu:

```json
{"type":"SUBMIT_PRACTICE","request_id":"practice-submit-001","token":"<session-token>","payload":{"attempt_id":1}}
```

Luồng server:

```text
1. Kiểm tra session và quyền sở hữu attempt.
2. Nếu attempt chưa nộp: BEGIN IMMEDIATE.
3. So sánh practice_answers với correct_option_position trong snapshot.
4. Tính correct_count, total và score = correct_count / total * 10.
5. Nếu đã hết giờ: state AUTO_SUBMITTED; nếu chưa: SUBMITTED.
6. Cập nhật practice_sessions và ghi một summary vào practice_attempts.
7. COMMIT, trả kết quả.
8. Nếu submit lần nữa: trả lại kết quả cũ, không ghi thêm history.
```

Response ví dụ:

```json
{"type":"OK","request_id":"practice-submit-001","data":{"attempt_id":1,"state":"SUBMITTED","correct_count":2,"total":3,"score":6.67}}
```

---

## 3. Tạo phòng thi — `CREATE_ROOM`

Chỉ role `HOST` hoặc `ADMIN` tạo được phòng. `STUDENT` nhận `FORBIDDEN`.

Request mẫu:

```json
{"type":"CREATE_ROOM","request_id":"create-room-001","token":"<host-token>","payload":{"name":"Phong TCP","duration_seconds":600,"rules":[{"topic":"TCP Socket","difficulty":"easy","quantity":2},{"topic":"TCP Socket","difficulty":"medium","quantity":1}]}}
```

Ý nghĩa một rule:

```json
{"topic":"TCP Socket","difficulty":"easy","quantity":2}
```

Phòng sẽ cần 2 câu active độ khó `easy` thuộc chủ đề `TCP Socket` khi đề phòng
được chốt sau này.

Luồng server:

```text
1. Kiểm tra session và role HOST/ADMIN.
2. Validate name, duration_seconds (60-7200) và 1-16 rule.
3. Validate difficulty, quantity (1-50), topic không rỗng, không lặp topic+difficulty.
4. BEGIN IMMEDIATE.
5. Với mỗi rule, đếm câu active đúng topic+difficulty.
6. Nếu thiếu câu: ROLLBACK và trả CONFLICT.
7. Insert exam_rooms với status WAITING.
8. Insert các room_question_rules.
9. COMMIT, ghi activity log ROOM_CREATED.
10. Trả room_id, name, status WAITING và duration_seconds.
```

Các bảng bị thay đổi:

| Bảng | Dữ liệu |
|---|---|
| `exam_rooms` | Phòng mới, owner, tên, status `WAITING`, thời lượng. |
| `room_question_rules` | Quy tắc lấy câu hỏi của phòng. |
| `activity_logs` | Audit event `ROOM_CREATED`. |

Owner tạo phòng chưa tự động trở thành participant.

---

## 4. Xem danh sách phòng — `LIST_ROOMS`

Mọi user đã đăng nhập đều gọi được API này.

Request mẫu:

```json
{"type":"LIST_ROOMS","request_id":"rooms-001","token":"<session-token>","payload":{}}
```

Luồng server:

```text
1. Kiểm tra session.
2. Chạy một SQL query duy nhất:
   exam_rooms JOIN users LEFT JOIN room_participants GROUP BY room.
3. Chỉ lấy status WAITING, RUNNING hoặc ENDED.
4. Trả danh sách theo room id giảm dần.
```

Mỗi room có các trường:

```json
{"id":1,"name":"Phong TCP","owner_id":1,"owner_name":"bao_host","status":"WAITING","duration_seconds":600,"participant_count":2}
```

`participant_count` được tính ngay trong câu SQL aggregate. Server không chạy
một query đếm riêng cho từng room, nên không có lỗi hiệu năng N+1 query.

---

## 5. Tham gia phòng — `JOIN_ROOM`

Mọi user có session hợp lệ có thể gửi request join. Một user chỉ join một lần
cho mỗi phòng.

Request mẫu:

```json
{"type":"JOIN_ROOM","request_id":"join-001","token":"<student-token>","payload":{"room_id":1}}
```

Luồng server:

```text
1. Kiểm tra session và room_id > 0.
2. Khóa DB, BEGIN IMMEDIATE.
3. Đọc status của room ngay trong transaction.
4. Nếu không có room: ROLLBACK, trả NOT_FOUND.
5. Nếu status khác WAITING: ROLLBACK, trả CONFLICT.
6. Insert (room_id, user_id, state = JOINED) vào room_participants.
7. Nếu vi phạm khóa chính (room_id, user_id): ROLLBACK, trả CONFLICT.
8. Đếm participant trong phòng, ghi log ROOM_JOINED.
9. COMMIT và trả kết quả.
```

Response thành công:

```json
{"type":"OK","request_id":"join-001","data":{"room_id":1,"status":"WAITING","participant_state":"JOINED","participant_count":2}}
```

Các lỗi nghiệp vụ chính:

| Điều kiện | Error code |
|---|---|
| Token không hợp lệ | `UNAUTHORIZED` |
| `room_id` thiếu/không dương | `BAD_REQUEST` |
| Phòng không tồn tại | `NOT_FOUND` |
| Phòng `RUNNING` hoặc `ENDED` | `CONFLICT` |
| User đã join phòng | `CONFLICT` |

---

## 6. Bắt đầu phòng và chốt đề — `START_ROOM`

Chỉ chủ phòng được gọi API này khi room đang `WAITING`.

```text
1. Kiểm tra session, room_id và owner ngay trong BEGIN IMMEDIATE.
2. Kiểm tra room đang WAITING.
3. Đọc từng room_question_rule, chọn ngẫu nhiên đủ câu active.
4. Snapshot room_questions: nội dung câu và ID đáp án đúng.
5. Snapshot room_question_options: ID, nhãn và nội dung của bốn lựa chọn.
6. Nếu thiếu câu hoặc một câu thiếu option: ROLLBACK, room vẫn WAITING.
7. Khi snapshot hoàn chỉnh: set RUNNING, started_at và ended_at.
8. Chuyển participant JOINED sang IN_PROGRESS, ghi ROOM_STARTED, COMMIT.
```

Response thành công có `room_id`, `status: "RUNNING"`, `question_count` và
`participants_started`. Gọi start lại nhận `CONFLICT`.

## 7. Lấy đề phòng — `GET_EXAM`

```text
1. Kiểm tra session và room_id.
2. Kiểm tra room tồn tại và có status RUNNING.
3. Kiểm tra caller có record trong room_participants.
4. Đọc room_questions + room_question_options theo position.
5. Đọc attempt_answers của chính caller cho từng câu, nếu có.
6. Trả snapshot đề và selected_option_id; không gửi đáp án đúng.
```

Người chưa join nhận `FORBIDDEN`; room `WAITING`/`ENDED` nhận `CONFLICT`.

## 8. Lưu đáp án phòng — `SAVE_ANSWER`

```text
1. Kiểm tra session, room_id, question_id và option_id.
2. BEGIN IMMEDIATE.
3. Kiểm tra room RUNNING, participant IN_PROGRESS và ended_at theo thời gian server.
4. Kiểm tra question/option thuộc snapshot của room.
5. UPSERT attempt_answers theo (room_id, user_id, question_id).
6. Ghi audit ANSWER_SAVED, COMMIT và trả saved: true.
```

Lưu lại cùng câu thay thế đáp án cũ. Save sau hạn, khi room không chạy, hoặc
participant không còn làm bài bị từ chối.

## 9. Nộp và chấm bài phòng — `SUBMIT_EXAM`

```text
1. BEGIN IMMEDIATE.
2. Đọc room + participant trong cùng transaction.
3. Nếu participant đã SUBMITTED/AUTO_SUBMITTED: trả kết quả cũ.
4. Nếu đang IN_PROGRESS: chấm attempt_answers theo correct_option_snapshot.
5. Update participant thành SUBMITTED hoặc AUTO_SUBMITTED, lưu điểm/số đúng/thời điểm nộp.
6. Ghi audit một lần, COMMIT và trả kết quả.
```

Transaction là hàng rào để timer tương lai và request user không thể chấm cùng
một participant hai lần.

## 10. Worker hết giờ room

```text
1. Worker server thức dậy mỗi 1 giây.
2. Tìm một room RUNNING có ended_at đã qua, BEGIN IMMEDIATE.
3. Chấm snapshot cho mọi participant JOINED/IN_PROGRESS.
4. Đổi họ thành AUTO_SUBMITTED, ghi điểm và audit log.
5. Đổi room thành ENDED, COMMIT.
6. Lặp cho room quá hạn tiếp theo; server dừng thì worker được join.
```

## 11. Trạng thái đang dùng

### Room

```text
CREATE_ROOM --> WAITING --(START_ROOM, snapshot hoàn chỉnh)--> RUNNING --> ENDED
                     |
                     +-- JOIN_ROOM: chỉ được phép ở WAITING
```

### Audit log room

Mỗi thay đổi quan trọng đều ghi vào `activity_logs`: tạo (`ROOM_CREATED`),
join (`ROOM_JOINED`), start (`ROOM_STARTED`), lưu câu trả lời
(`ANSWER_SAVED`), nộp (`EXAM_SUBMITTED`), auto-submit
(`EXAM_AUTO_SUBMITTED`) và worker đóng room (`ROOM_ENDED`). Log chỉ ghi metadata
nhỏ phục vụ audit; không chứa token, mật khẩu, tên phòng tự do, đáp án hay nội
dung đề.

### Practice session

```text
START_PRACTICE --> IN_PROGRESS --(SUBMIT_PRACTICE)--> SUBMITTED
                         |
                         +-- submit sau ended_at --> AUTO_SUBMITTED
```

---

## 12. File mã nguồn và kiểm thử chính

| Mục | File |
|---|---|
| Room create/join | `server/src/room/room.c`, `server/include/room.h` |
| List rooms | `server/src/auth/auth.c` |
| Practice | `server/src/practice/practice.c`, `server/include/practice.h` |
| Route TCP | `server/src/core/server_socket.c` |
| Contract | `docs/protocol.md` |
| Test backend | `server/tests/test_phase2_create_room.py`, `server/tests/test_phase2_practice.py` |
| Wrapper PySide | `client/app/services/tcp_api_service.py` |

Đã kiểm thử backend trên Ubuntu 22.04 bằng:

```bash
make clean && make test
```

Kết quả mới nhất: **29 test pass** (Ubuntu 22.04.5, gồm regression audit log).
