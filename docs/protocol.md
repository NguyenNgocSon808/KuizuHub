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
