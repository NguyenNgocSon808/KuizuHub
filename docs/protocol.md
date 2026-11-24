# KuizuHub — Hợp đồng TCP NDJSON

## Transport

Server mặc định bind tại `0.0.0.0:5050`. TCP là byte stream, vì vậy mỗi connection phải giữ buffer riêng. Một message là **một JSON object UTF-8 kết thúc bằng đúng một `\n`**; giới hạn mỗi dòng là 64 KiB. Không dùng binary header, opcode, hoặc giả định một lần `recv()` tương ứng một message.

Server phải tách được một JSON bị chia ở nhiều lần nhận và nhiều JSON đến trong cùng lần nhận. Một dòng quá 64 KiB hoặc không phải JSON object nhận response lỗi mà không làm crash server.

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
{"type":"OK","request_id":"prof-001","data":{"user":{"id":1,"username":"son","role":"HOST","created_at":"2026-11-10 00:00:00"}}}
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

### 7. `START_ROOM` & `END_ROOM` (Kiểm soát quyền chủ phòng)

Yêu cầu `token` hợp lệ và người gọi phải là `owner_id` của phòng (`require_room_owner`). Nếu thí sinh hoặc người không phải chủ phòng gọi sẽ nhận `FORBIDDEN`.

Request:

```json
{"type":"START_ROOM","request_id":"start-001","token":"<session-token>","payload":{"room_id":1}}
```

Response lỗi khi không phải chủ phòng:

```json
{"type":"ERROR","request_id":"start-001","error":{"code":"FORBIDDEN","message":"Only the room owner can perform this action"}}
```

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

---

## Request Phase 2 — Reliability & Reconnect (Người 1)

### 12. `GET_MY_ACTIVE_EXAM`

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
