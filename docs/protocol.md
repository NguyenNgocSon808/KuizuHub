# KuizuHub — Hợp đồng TCP NDJSON

## Transport

Server mặc định bind tại `0.0.0.0:5050`. TCP là byte stream, vì vậy mỗi connection phải giữ buffer riêng. Một message là **một JSON object UTF-8 kết thúc bằng đúng một `\n`**. Giới hạn request là 64 KiB. Response có thể dài đến 8 MiB để chứa đề thi và phần xem lại. Không dùng binary header, opcode, hoặc giả định một lần `recv()` tương ứng một message.

Server phải tách được một JSON bị chia ở nhiều lần nhận và nhiều JSON đến trong cùng lần nhận. Server trả lỗi khi nhận request quá 64 KiB hoặc sai định dạng JSON object.

## Envelope

Mọi request dùng cấu trúc sau:

```json
{"type":"PING","request_id":"health-1","payload":{}}
```

- `type`: tên request, dạng string.
- `request_id`: string do client sinh; response tương ứng phải echo giá trị này.
- `token`: session token, bắt buộc ở các request cần xác thực.
- `payload`: object, có thể rỗng `{}`.

Response thành công:

```json
{"type":"OK","request_id":"health-1","data":{"message":"pong"}}
```

Response lỗi:

```json
{"type":"ERROR","request_id":"health-1","error":{"code":"BAD_REQUEST","message":"Message must be a JSON object"}}
```

Nếu không thể đọc `request_id`, response lỗi dùng `"request_id": null`.

## Mã lỗi chuẩn

| Code | Khi dùng |
|---|---|
| `BAD_REQUEST` | JSON, field hoặc payload không hợp lệ; dòng quá 64 KiB. |
| `UNAUTHORIZED` | Thiếu, hết hạn, đã logout hoặc sai session token / sai thông tin đăng nhập. |
| `FORBIDDEN` | Đã xác thực nhưng không có quyền (ví dụ: thí sinh gọi `START_ROOM` của chủ phòng). |
| `NOT_FOUND` | Không có resource hoặc request type không được hỗ trợ. |
| `CONFLICT` | Trạng thái hiện tại không cho phép thao tác (ví dụ: trùng `username`). |
| `INTERNAL_ERROR` | Lỗi nội bộ không thể phân loại khác. |

---

## Request ở Phase 0 & Phase 1 (Core & Auth — Người 1)

### 1. `PING`

Request không cần token, xác minh client/server đã thống nhất framing.

```json
{"type":"PING","request_id":"ping-001","payload":{}}
```

Response:

```json
{"type":"OK","request_id":"ping-001","data":{"message":"pong"}}
```

---

### 2. `REGISTER`

Đăng ký tài khoản mới.
- `username`: 3–32 ký tự, chỉ gồm chữ cái, chữ số, `_`, `-`, `.`; không được trùng lặp (`CONFLICT` nếu đã tồn tại).
- `password`: tối thiểu 8 ký tự (băm bằng `PBKDF2-HMAC-SHA256` trước khi lưu DB).
- `role` (tùy chọn): `"STUDENT"` (mặc định), `"HOST"`, hoặc `"ADMIN"`.

Request:

```json
{"type":"REGISTER","request_id":"reg-001","payload":{"username":"son","password":"Password123","role":"HOST"}}
```

Response thành công:

```json
{"type":"OK","request_id":"reg-001","data":{"user":{"id":1,"username":"son","role":"HOST"}}}
```

Response lỗi khi trùng username:

```json
{"type":"ERROR","request_id":"reg-002","error":{"code":"CONFLICT","message":"Username already exists"}}
```

---

### 3. `LOGIN`

Xác thực bằng `username` và `password`. Nếu hợp lệ, server sinh ngẫu nhiên `token` (64 ký tự hex), lưu `SHA-256(token)` vào `sessions.token_hash` kèm thời hạn 24 giờ.

Request:

```json
{"type":"LOGIN","request_id":"login-001","payload":{"username":"son","password":"Password123"}}
```

Response thành công:

```json
{"type":"OK","request_id":"login-001","data":{"token":"<64-hex-session-token>","expires_at":"2026-11-11 01:00:00","user":{"id":1,"username":"son","role":"HOST"}}}
```

Response lỗi khi sai mật khẩu hoặc không tồn tại tài khoản:

```json
{"type":"ERROR","request_id":"login-001","error":{"code":"UNAUTHORIZED","message":"Invalid username or password"}}
```

**Rate Limiting:** Server giới hạn tối đa **5 lần đăng nhập sai / 60 giây** trên mỗi `username` (và 20 lần/phút trên mỗi IP). Vượt ngưỡng sẽ trả về `UNAUTHORIZED` kèm thông báo `"Too many failed login attempts. Try again later"` và ghi log `LOGIN_RATE_LIMITED`.

---

### 4. `LOGOUT`

Thu hồi (revoke) phiên đăng nhập hiện tại (`sessions.revoked_at = CURRENT_TIMESTAMP`). Yêu cầu `token` hợp lệ.

Request:

```json
{"type":"LOGOUT","request_id":"logout-001","token":"<session-token>","payload":{}}
```

Response:

```json
{"type":"OK","request_id":"logout-001","data":{"logged_out":true}}
```

---

### 5. `GET_MY_PROFILE`

Trả về thông tin tài khoản của phiên hiện tại. Yêu cầu `token` hợp lệ.

Request:

```json
{"type":"GET_MY_PROFILE","request_id":"prof-001","token":"<session-token>","payload":{}}
```

Response:

```json
{"type":"OK","request_id":"prof-001","data":{"user":{"id":1,"username":"son","display_name":"Sơn","role":"HOST","created_at":"2026-11-10 00:00:00"}}}
```

---

### 6. `LIST_ROOMS`

Liệt kê danh sách phòng thi. Yêu cầu `token` hợp lệ (`UNAUTHORIZED` nếu thiếu hoặc sai token).

Request:

```json
{"type":"LIST_ROOMS","request_id":"rooms-001","token":"<session-token>","payload":{}}
```

Response:

```json
{"type":"OK","request_id":"rooms-001","data":{"rooms":[{"id":1,"name":"Midterm Network","owner_id":1,"owner_name":"son","status":"WAITING","duration_seconds":600,"participant_count":2}]}}
```

---

### 7. `JOIN_ROOM`

User đã đăng nhập tham gia một phòng ở trạng thái `WAITING`. Server kiểm tra
trạng thái và ghi participant trong cùng SQLite transaction; gọi lại với cùng
`room_id` nhận `CONFLICT` và không tạo bản ghi trùng.

```json
{"type":"JOIN_ROOM","request_id":"join-001","token":"<session-token>","payload":{"room_id":1}}
```

Response thành công:

```json
{"type":"OK","request_id":"join-001","data":{"room_id":1,"status":"WAITING","participant_state":"JOINED","participant_count":2}}
```

Phòng không tồn tại nhận `NOT_FOUND`; phòng `RUNNING` hoặc `ENDED`, hay user đã
join, nhận `CONFLICT`.

---

### 8. `START_ROOM` (Bắt đầu phòng và chốt đề)

Yêu cầu `token` hợp lệ và caller là `owner_id` của phòng. Server thực hiện toàn
bộ lifecycle trong một SQLite transaction: kiểm tra `WAITING`, lấy ngẫu nhiên
đủ câu theo từng rule, snapshot nội dung câu hỏi/bốn lựa chọn/đáp án đúng nội
bộ, rồi mới chuyển phòng sang `RUNNING`. Các participant `JOINED` được chuyển
sang `IN_PROGRESS`.

Request:

```json
{"type":"START_ROOM","request_id":"start-001","token":"<session-token>","payload":{"room_id":1}}
```

Response thành công:

```json
{"type":"OK","request_id":"start-001","data":{"room_id":1,"status":"RUNNING","question_count":3,"participants_started":2}}
```

Nếu snapshot không đầy đủ (thiếu câu active hoặc một câu thiếu lựa chọn), server
rollback toàn bộ và phòng vẫn là `WAITING`; response là `CONFLICT`. Gọi start
lần hai cũng nhận `CONFLICT`.

Response lỗi khi không phải chủ phòng:

```json
{"type":"ERROR","request_id":"start-001","error":{"code":"FORBIDDEN","message":"Only the room owner can perform this action"}}
```

`END_ROOM` cho phép chủ phòng kết thúc sớm với payload `{"room_id":1}`. Server
tự chấm các participant `JOINED`/`IN_PROGRESS`, gán `AUTO_SUBMITTED` và chuyển
phòng sang `ENDED` trong cùng transaction. Worker dùng cùng logic khi hết giờ.

---

### 9. `GET_EXAM`

Chỉ participant của room đang `RUNNING` được lấy đề. Server trả từ bảng
snapshot, không đọc lại câu hỏi/lựa chọn gốc và không trả đáp án đúng. Đáp án
đã lưu của chính caller (nếu có) được trả tại `selected_option_id`.
`remaining_seconds` là số giây còn lại tại thời điểm server tạo phản hồi.

```json
{"type":"GET_EXAM","request_id":"exam-001","token":"<student-token>","payload":{"room_id":1}}
```

```json
{"type":"OK","request_id":"exam-001","data":{"room_id":1,"status":"RUNNING","ended_at":"2026-11-22 10:30:00","questions":[{"id":12,"position":1,"content":"...","options":[{"id":45,"position":1,"label":"A","content":"..."}],"selected_option_id":45}]}}
```

Phòng không tồn tại trả `NOT_FOUND`; room không ở `RUNNING` trả `CONFLICT`; user
không phải participant trả `FORBIDDEN`.

---

### 10. `SAVE_ANSWER`

Participant đang `IN_PROGRESS` lưu hoặc thay đổi đáp án của một câu trong room
đang `RUNNING`. Server dùng thời gian SQLite (`ended_at <= datetime('now')`),
không tin timestamp phía client. `question_id` và `option_id` phải cùng thuộc
snapshot của room.

```json
{"type":"SAVE_ANSWER","request_id":"answer-001","token":"<student-token>","payload":{"room_id":1,"question_id":12,"option_id":45}}
```

Response thành công:

```json
{"type":"OK","request_id":"answer-001","data":{"saved":true}}
```

Lưu lại cùng question sẽ UPSERT (ghi đè đáp án cũ). Hết giờ hoặc room không còn
`RUNNING` nhận `CONFLICT`; option/câu không thuộc snapshot nhận `BAD_REQUEST`.

---

### 11. `SUBMIT_EXAM`

Participant `IN_PROGRESS` nộp bài. Server dùng `BEGIN IMMEDIATE` để chấm theo
snapshot, cập nhật participant và ghi audit trong một transaction. Gọi lại sau
khi đã nộp là idempotent: trả đúng kết quả cũ, không chấm hoặc ghi log lần hai.

```json
{"type":"SUBMIT_EXAM","request_id":"submit-001","token":"<student-token>","payload":{"room_id":1}}
```

```json
{"type":"OK","request_id":"submit-001","data":{"room_id":1,"state":"SUBMITTED","correct_count":2,"total":3,"score":6.67}}
```

Điểm theo thang 10: `correct_count / total * 10`. Nếu submit sau `ended_at`,
state là `AUTO_SUBMITTED`. Timer tự quét để auto-submit toàn bộ participant quá
hạn là lifecycle riêng, không thuộc request này.

---

## Request Phase 1 — Ngân hàng câu hỏi (Người 3)

Các request trong phần này đều yêu cầu `token` hợp lệ của tài khoản có `role: "ADMIN"`. Các vai trò khác nhận `FORBIDDEN`. Chỉ API quản trị này trả về đáp án đúng; không dùng nó cho luồng thí sinh làm bài.

Mẫu dữ liệu câu hỏi dùng cho create, update và import:

```json
{
  "content":"Hàm nào tạo TCP socket?",
  "topic":"TCP Socket",
  "difficulty":"easy",
  "options":["socket()","bind()","listen()","accept()"],
  "correct_option_index":0,
  "explanation":"socket() tạo endpoint trước khi bind/listen."
}
```

- `content`: không rỗng, tối đa 1200 bytes.
- `topic`: không rỗng, tối đa 64 bytes.
- `difficulty`: đúng một trong `easy`, `medium`, `hard`.
- `options`: chính xác bốn string không rỗng theo thứ tự A–D, tối đa 400 bytes mỗi option.
- `correct_option_index`: số nguyên từ `0` đến `3`.
- `explanation`: tùy chọn, tối đa 1200 bytes; thiếu thì lưu chuỗi rỗng.

### 8. `LIST_QUESTIONS`

Payload hỗ trợ `query`, `topic`, `difficulty`, `include_inactive` (`0` hoặc `1`, mặc định `1`), `limit` (1–20, mặc định 20) và `offset` (mặc định 0).

```json
{"type":"LIST_QUESTIONS","request_id":"questions-001","token":"<admin-token>","payload":{"topic":"TCP Socket","include_inactive":1,"limit":20,"offset":0}}
```

Response chứa `questions`, `limit`, `offset`, `has_more`. Mỗi câu có `id`, `content`, `topic`, `difficulty`, `options` (gồm `id`, `label`, `content`, `position`), `correct_option_id`, `correct_option_index`, `is_active` và `explanation`.

### 9. `CREATE_QUESTION`

Payload chính là mẫu câu hỏi ở trên. Câu mới luôn ở trạng thái `is_active = 1`.

```json
{"type":"CREATE_QUESTION","request_id":"question-create-001","token":"<admin-token>","payload":{"content":"Hàm nào tạo TCP socket?","topic":"TCP Socket","difficulty":"easy","options":["socket()","bind()","listen()","accept()"],"correct_option_index":0,"explanation":"socket() tạo endpoint trước khi bind/listen."}}
```

Response:

```json
{"type":"OK","request_id":"question-create-001","data":{"question_id":31,"created":true}}
```

### 10. `UPDATE_QUESTION`

`id` là bắt buộc. Có thể gửi `is_active: 0` để disable mềm hoặc `is_active: 1` để enable lại. Khi sửa nội dung, đặt toàn bộ mẫu câu hỏi trong object `question`; bốn option hiện có được cập nhật tại chỗ để không làm đổi ID option đã được tham chiếu bởi dữ liệu thi sau này.

```json
{"type":"UPDATE_QUESTION","request_id":"question-update-001","token":"<admin-token>","payload":{"id":31,"is_active":0,"question":{"content":"Hàm nào gắn địa chỉ local vào socket?","topic":"TCP Socket","difficulty":"easy","options":["socket()","bind()","listen()","accept()"],"correct_option_index":1,"explanation":"bind() gắn địa chỉ local vào socket."}}}
```

Không có hard delete trong API này.

### 11. `IMPORT_QUESTIONS`

Nhận `payload.questions`, là mảng tối đa 100 object theo mẫu câu hỏi. Server validate toàn bộ trước khi ghi và import trong một transaction: nếu một item lỗi, không item nào được lưu.

```json
{"type":"IMPORT_QUESTIONS","request_id":"question-import-001","token":"<admin-token>","payload":{"questions":[{"content":"...","topic":"DNS","difficulty":"medium","options":["A","B","C","D"],"correct_option_index":2}]}}
```

Response thành công:

```json
{"type":"OK","request_id":"question-import-001","data":{"imported":1}}
```

## `CREATE_ROOM`

Tạo một phòng thi mới.

- Yêu cầu token hợp lệ.
- Chỉ role `HOST` hoặc `ADMIN` được tạo phòng.
- Phòng mới luôn có trạng thái `WAITING`.
- Chủ phòng không tự động là thí sinh. Nếu cần làm bài, chủ phòng gọi `JOIN_ROOM` như user bình thường.
- `name` không được rỗng và tối đa 100 ký tự.
- `duration_seconds` là số nguyên từ 60 đến 7200.
- `rules` có từ 1 đến 16 item. Mỗi item có `topic` không rỗng, `difficulty` là `easy`, `medium` hoặc `hard`, và `quantity` từ 1 đến 50; không lặp cùng cặp `topic` và `difficulty`.
- Server chỉ tạo phòng khi mỗi rule có đủ số câu hỏi active tương ứng.

Request:

```json
{
  "type": "CREATE_ROOM",
  "request_id": "create-room-001",
  "token": "<session-token>",
  "payload": {
    "name": "Kiểm tra TCP",
    "duration_seconds": 600,
    "rules": [
      {
        "topic": "TCP Socket",
        "difficulty": "easy",
        "quantity": 5
      },
      {
        "topic": "TCP Socket",
        "difficulty": "medium",
        "quantity": 5
      }
    ]
  }
}
```

Response thành công:

```json
{
  "type": "OK",
  "request_id": "create-room-001",
  "data": {
    "room_id": 1,
    "name": "Kiểm tra TCP",
    "status": "WAITING",
    "duration_seconds": 600
  }
}
```

Lỗi ví dụ:
```json
{
  "type": "ERROR",
  "request_id": "create-room-001",
  "error": {
    "code": "CONFLICT",
    "message": "Not enough active questions for topic TCP Socket, difficulty medium: need 5, available 3"
  }
}
```

## `START_PRACTICE`

Tạo một phiên luyện tập riêng của user đang đăng nhập. Server chọn ngẫu nhiên
đúng số câu active theo topic/difficulty, snapshot câu hỏi và lựa chọn, nhưng
không trả đáp án đúng.

Payload cần có `topic`, `difficulty` (`easy`, `medium`, `hard`),
`question_count` (1-20) và `duration_seconds` (60-7200). Nếu không đủ câu,
server trả `CONFLICT` và không tạo phiên.

```json
{"type":"START_PRACTICE","request_id":"practice-start-001","token":"<session-token>","payload":{"topic":"TCP Socket","difficulty":"easy","question_count":3,"duration_seconds":600}}
```

Response trả `attempt_id`, `ended_at`, `remaining_seconds` và `questions`. Mỗi question có `id`, `position`,
`content` và bốn option gồm `position`, `label`, `content`.

## `SAVE_PRACTICE_ANSWER`

Lưu hoặc thay đáp án của chủ attempt. Chỉ được gọi khi attempt còn
`IN_PROGRESS` và chưa hết hạn.

```json
{"type":"SAVE_PRACTICE_ANSWER","request_id":"practice-save-001","token":"<session-token>","payload":{"attempt_id":1,"question_id":12,"selected_option_position":2}}
```

Response thành công là `{"saved":true}`. Option không thuộc snapshot hoặc
attempt đã hết hạn nhận `BAD_REQUEST` hoặc `CONFLICT` tương ứng.

## `SUBMIT_PRACTICE`

Chấm attempt ở server theo snapshot. Worker tự chấm attempt hết hạn với state
`AUTO_SUBMITTED`, kể cả khi client đã ngắt kết nối. Gọi lại API trả kết quả đã
chấm và không ghi thêm history.

```json
{"type":"SUBMIT_PRACTICE","request_id":"practice-submit-001","token":"<session-token>","payload":{"attempt_id":1}}
```

Response gồm `attempt_id`, `state`, `correct_count`, `total` và `score` theo
thang 10.

---

## Request Phase 2–3 — phòng thi, kết quả và analytics (Người 3)

### `GET_ROOM_LOBBY`

Chủ phòng hoặc thí sinh **đã tham gia** xem sảnh chờ và danh sách người tham
gia. Request này không trả đề thi, đáp án hay token. UI dùng refresh có chủ
đích; không giả lập realtime bằng dữ liệu local.

```json
{"type":"GET_ROOM_LOBBY","request_id":"lobby-001","token":"<session-token>","payload":{"room_id":1}}
```

Response gồm `room` (`id`, `name`, `owner_id`, `status`, `duration_seconds`,
`started_at`, `ended_at`), `is_owner` và `participants` có `user_id`,
`display_name`, `state`. User không phải owner/participant nhận `FORBIDDEN`.

### `GET_ROOM_RESULTS`

Kết quả chỉ công bố khi room ở `ENDED`.

```json
{"type":"GET_ROOM_RESULTS","request_id":"result-001","token":"<session-token>","payload":{"room_id":1}}
```

- Owner nhận `results` của toàn bộ participant: username, state, thời điểm nộp,
  số đúng, tổng câu và điểm.
- Participant chỉ nhận result của chính mình. Nếu caller là participant, response
  còn có `review` từ snapshot gồm lựa chọn đã chọn, đáp án đúng và trạng thái
  đúng/sai. Dữ liệu này tuyệt đối không xuất hiện trước `ENDED`.
- User ngoài room nhận `FORBIDDEN`; room chưa kết thúc nhận `CONFLICT`.

Response có cờ `results_truncated`/`review_truncated` khi response sẽ vượt giới
hạn NDJSON 64 KiB; client phải báo rõ cho người dùng thay vì coi dữ liệu local là
đầy đủ.

### `GET_LEADERBOARD`

Mọi user đã đăng nhập có thể xem leaderboard của room đã `ENDED`. Sắp xếp theo
điểm giảm dần, sau đó thời điểm nộp tăng dần. Payload có `room_id`, `limit`
(1–50, mặc định 20) và `offset` (mặc định 0).

```json
{"type":"GET_LEADERBOARD","request_id":"leaderboard-001","token":"<session-token>","payload":{"room_id":1,"limit":20,"offset":0}}
```

Response có `entries`, `limit`, `offset`, `has_more`. Mỗi entry có `rank`,
`user_id`, `username`, `state`, `score`, `correct_count`, `total`,
`submitted_at`. Room chưa `ENDED` nhận `CONFLICT`.

### `GET_MY_HISTORY`

Trả lịch sử bài practice và room exam đã `SUBMITTED`/`AUTO_SUBMITTED` của chính
caller, theo trang. Payload dùng `limit` 1–50 và `offset` không âm.

```json
{"type":"GET_MY_HISTORY","request_id":"history-001","token":"<session-token>","payload":{"limit":20,"offset":0}}
```

Mỗi item có `kind` (`PRACTICE` hoặc `EXAM`), `attempt_id`, `room_id` (hoặc
`null`), `title`, `topic`, `difficulty`, `score`, `correct_count`, `total`,
`duration_seconds`, `completed_at`, `state`. Response có `has_more` để GUI
phân trang an toàn.

### `GET_MY_STATS`

Trả thống kê chỉ của caller:

```json
{"type":"GET_MY_STATS","request_id":"stats-001","token":"<session-token>","payload":{}}
```

Response gồm `attempts`, `average_score`, `correct_count`, `total_questions`,
`accuracy_percent`, `streak_days` và `by_topic`. Mỗi bucket `by_topic` có
`topic`, `difficulty`, `correct_count`, `total`, `accuracy_percent`. Topic và
độ khó được lưu snapshot cho bài mới để việc admin sửa ngân hàng câu hỏi sau này
không làm sai số liệu lịch sử.

### `UPDATE_MY_PROFILE`

Cho phép đổi `display_name`, hoặc đổi password bằng cả `current_password` và
`new_password` (8–128 ký tự). Không response/log password, password hash hay
session token.

```json
{"type":"UPDATE_MY_PROFILE","request_id":"profile-update-001","token":"<session-token>","payload":{"display_name":"Nguyễn A","current_password":"OldPass123","new_password":"NewPass123"}}
```

Ít nhất một thay đổi là bắt buộc. Sai password hiện tại nhận `UNAUTHORIZED`;
field sai kiểu hay thiếu cặp password nhận `BAD_REQUEST`.

### CSV question bank trên GUI

`IMPORT_QUESTIONS` vẫn là transaction server-side atomic tối đa 100 câu. GUI
CSV đọc các cột `content`, `topic`, `difficulty`, `option_a`…`option_d`,
`correct_option_index`, `explanation`, validate và báo đúng dòng lỗi trước khi
gửi request JSON này. Xuất CSV lấy toàn bộ trang `LIST_QUESTIONS` theo filter
đang chọn; dữ liệu vẫn có nguồn từ TCP server chứ không từ mock/local JSON.

---

## Request Phase 2 — Reliability & Reconnect (Người 1)

### `GET_MY_ACTIVE_EXAM`

Cho phép client sau khi bị mất kết nối mạng (rớt TCP socket) kết nối lại bằng `token` còn hạn để khôi phục bài thi đang làm trong phòng `RUNNING`. Yêu cầu `token` hợp lệ (`UNAUTHORIZED` nếu thiếu/sai/hết hạn). **Tuyệt đối không trả về đáp án đúng.**

Request:

```json
{"type":"GET_MY_ACTIVE_EXAM","request_id":"reconnect-001","token":"<session-token>","payload":{}}
```

Response khi đang có bài thi chưa nộp:

```json
{
  "type":"OK",
  "request_id":"reconnect-001",
  "data":{
    "active_exam":{
      "room_id":1,
      "room_name":"Midterm Network",
      "started_at":"2026-11-23 02:00:00",
      "ended_at":"2026-11-23 02:10:00",
      "duration_seconds":600,
      "state":"IN_PROGRESS",
      "questions":[
        {
          "question_id":1,
          "position":1,
          "content":"Hàm nào tạo một TCP socket trên POSIX?",
          "options":[{"id":1,"label":"A","content":"socket()","position":1}]
        }
      ],
      "saved_answers":[{"question_id":1,"selected_option_id":1}]
    }
  }
}
```

Response khi không có phòng nào đang thi:

```json
{"type":"OK","request_id":"reconnect-001","data":{"active_exam":null}}
```
