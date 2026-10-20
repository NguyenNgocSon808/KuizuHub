# KuizuHub — Đặc Tả Giao Thức Client-Server

**Phiên bản:** 1.0  
**Ngày soạn:** 2026-10-20  

---

## 1. Tổng Quan

KuizuHub sử dụng giao tiếp **TCP Socket** giữa Client và Server. Mọi dữ liệu trao đổi được đóng gói theo định dạng nhị phân thống nhất (**Binary Frame**), với phần Payload là JSON UTF-8.

```
Client  ──────── TCP Socket ────────  Server
  │                                      │
  │──── Frame (Header + Payload) ───────>│
  │<─── Frame (Header + Payload) ────────│
```

---

## 2. Định Dạng Gói Tin (Message Frame)

Mỗi gói tin gồm **Header cố định 8 byte** + **Payload động**.

```
 0       1       2       3       4       5       6       7
 +-------+-------+-------+-------+-----------+-----------+
 |  VER  |  OPC  |  FLAGS|  RES  |  SEQ_NUM  |  PAY_LEN  |
 | 1 byte| 1 byte| 1 byte| 1 byte|  2 bytes  |  2 bytes  |
 +-------+-------+-------+-------+-----------+-----------+
 |                    PAYLOAD (JSON UTF-8)               |
 |                   (PAY_LEN bytes)                     |
 +-------------------------------------------------------+
```

### 2.1 Mô Tả Các Trường Header

| Trường     | Kích thước | Mô tả |
|------------|-----------|-------|
| `VER`      | 1 byte    | Phiên bản giao thức. Hiện tại = `0x01` |
| `OPC`      | 1 byte    | Opcode — định danh loại gói tin (xem Bảng Opcode) |
| `FLAGS`    | 1 byte    | Cờ điều khiển: `bit0` = có nén (gzip), `bit1` = có mã hóa, các bit còn lại dành cho tương lai |
| `RES`      | 1 byte    | Dự phòng, luôn = `0x00` |
| `SEQ_NUM`  | 2 bytes   | Số thứ tự gói tin (Big-Endian), dùng để debug và ghép mảnh sau này |
| `PAY_LEN`  | 2 bytes   | Độ dài Payload tính bằng byte (Big-Endian), tối đa 65535 bytes |

### 2.2 Giới Hạn

- Kích thước Payload tối đa: **65,535 bytes** (~64 KB).
- Nếu dữ liệu lớn hơn, cần **phân mảnh** (fragmentation) — sẽ đặc tả ở phiên bản 1.1.
- Thời gian chờ kết nối (timeout): **30 giây** không hoạt động → Server đóng socket.

---

## 3. Bảng Opcode

Opcode chia thành các nhóm theo chức năng:

```
0x00 – 0x0F  →  Hệ thống (System)
0x10 – 0x1F  →  Xác thực (Authentication)
0x20 – 0x2F  →  Sảnh & Phòng thi (Lobby / Room)
0x30 – 0x3F  →  Luồng thi (Exam Flow)
0x40 – 0x4F  →  Thống kê & Hồ sơ (Stats / Profile)
0xF0 – 0xFF  →  Lỗi & Thông báo hệ thống (Error / Notify)
```

### 3.1 Nhóm Hệ Thống (0x00 – 0x0F)

| Opcode  | Tên              | Hướng         | Mô tả |
|---------|------------------|---------------|-------|
| `0x00`  | `PING`           | Client→Server | Kiểm tra kết nối còn sống |
| `0x01`  | `PONG`           | Server→Client | Phản hồi PING |
| `0x02`  | `DISCONNECT`     | Hai chiều     | Thông báo ngắt kết nối có chủ ý |
| `0x03`  | `RECONNECT_REQ`  | Client→Server | Yêu cầu khôi phục phiên sau mất mạng |
| `0x04`  | `RECONNECT_ACK`  | Server→Client | Xác nhận khôi phục phiên thành công / thất bại |

### 3.2 Nhóm Xác Thực (0x10 – 0x1F)

| Opcode  | Tên              | Hướng         | Mô tả |
|---------|------------------|---------------|-------|
| `0x10`  | `REGISTER_REQ`   | Client→Server | Yêu cầu đăng ký tài khoản mới |
| `0x11`  | `REGISTER_RES`   | Server→Client | Kết quả đăng ký (thành công / lỗi) |
| `0x12`  | `LOGIN_REQ`      | Client→Server | Yêu cầu đăng nhập |
| `0x13`  | `LOGIN_RES`      | Server→Client | Kết quả đăng nhập + session_token |
| `0x14`  | `LOGOUT_REQ`     | Client→Server | Yêu cầu đăng xuất |
| `0x15`  | `LOGOUT_RES`     | Server→Client | Xác nhận đăng xuất |

### 3.3 Nhóm Sảnh & Phòng Thi (0x20 – 0x2F)

| Opcode  | Tên                  | Hướng         | Mô tả |
|---------|----------------------|---------------|-------|
| `0x20`  | `ROOM_LIST_REQ`      | Client→Server | Yêu cầu danh sách phòng thi đang mở |
| `0x21`  | `ROOM_LIST_RES`      | Server→Client | Danh sách phòng hiện tại |
| `0x22`  | `ROOM_CREATE_REQ`    | Client→Server | Yêu cầu tạo phòng thi mới (Host) |
| `0x23`  | `ROOM_CREATE_RES`    | Server→Client | Kết quả tạo phòng + room_id |
| `0x24`  | `ROOM_JOIN_REQ`      | Client→Server | Yêu cầu tham gia phòng chờ |
| `0x25`  | `ROOM_JOIN_RES`      | Server→Client | Xác nhận vào phòng / từ chối |
| `0x26`  | `ROOM_LEAVE_REQ`     | Client→Server | Rời phòng chờ |
| `0x27`  | `ROOM_PLAYER_UPDATE` | Server→Client | Broadcast: danh sách người trong phòng thay đổi |
| `0x28`  | `ROOM_STATE_UPDATE`  | Server→Client | Broadcast: trạng thái phòng thay đổi (chờ/đang thi/kết thúc) |

### 3.4 Nhóm Luồng Thi (0x30 – 0x3F)

| Opcode  | Tên                  | Hướng         | Mô tả |
|---------|----------------------|---------------|-------|
| `0x30`  | `EXAM_START`         | Server→Client | Host bắt đầu → Server phát đề + thời gian |
| `0x31`  | `EXAM_SUBMIT_ANS`    | Client→Server | Người dùng gửi/cập nhật đáp án một câu |
| `0x32`  | `EXAM_ANS_ACK`       | Server→Client | Xác nhận đã nhận đáp án |
| `0x33`  | `EXAM_TIME_SYNC`     | Server→Client | Broadcast: đồng bộ thời gian còn lại (mỗi 5 giây) |
| `0x34`  | `EXAM_FORCE_SUBMIT`  | Server→Client | Thông báo hết giờ, thu bài bắt buộc |
| `0x35`  | `EXAM_RESULT`        | Server→Client | Kết quả bài thi cá nhân (điểm, đáp án đúng) |
| `0x36`  | `EXAM_LEADERBOARD`   | Server→Client | Broadcast: bảng xếp hạng phòng thi |
| `0x37`  | `HOST_START_REQ`     | Client→Server | Host gửi lệnh bắt đầu thi |
| `0x38`  | `PRACTICE_START_REQ` | Client→Server | Người dùng bắt đầu bài luyện tập riêng |
| `0x39`  | `PRACTICE_RESULT`    | Server→Client | Kết quả bài luyện tập (phản hồi ngay) |

### 3.5 Nhóm Thống Kê & Hồ Sơ (0x40 – 0x4F)

| Opcode  | Tên                  | Hướng         | Mô tả |
|---------|----------------------|---------------|-------|
| `0x40`  | `PROFILE_REQ`        | Client→Server | Yêu cầu thông tin hồ sơ cá nhân |
| `0x41`  | `PROFILE_RES`        | Server→Client | Dữ liệu hồ sơ + lịch sử thi |
| `0x42`  | `HISTORY_REQ`        | Client→Server | Yêu cầu chi tiết bài thi cũ |
| `0x43`  | `HISTORY_RES`        | Server→Client | Chi tiết đáp án bài thi đã làm |

### 3.6 Nhóm Lỗi & Thông Báo (0xF0 – 0xFF)

| Opcode  | Tên              | Hướng         | Mô tả |
|---------|------------------|---------------|-------|
| `0xF0`  | `ERROR`          | Server→Client | Thông báo lỗi tổng quát |
| `0xF1`  | `NOTIFY`         | Server→Client | Thông báo hệ thống (kick, bảo trì, ...) |
| `0xF2`  | `ANTI_CHEAT`     | Server→Client | Cảnh báo gian lận (tab-switch phát hiện) |

---

## 4. Định Dạng Payload (JSON)

Tất cả Payload đều là JSON UTF-8. Mọi gói tin đều có trường `status` ở phản hồi từ Server.

### 4.1 Quy Ước Chung

```json
// Gói phản hồi từ Server luôn có:
{
  "status": "ok" | "error",
  "msg": "Mô tả ngắn (khi error)",
  "error_code": 1001          // Chỉ có khi status = "error"
}
```

### Bảng Mã Lỗi (`error_code`)

| Mã    | Ý nghĩa |
|-------|---------|
| 1001  | Sai tên đăng nhập hoặc mật khẩu |
| 1002  | Tên đăng nhập đã tồn tại |
| 1003  | Session không hợp lệ hoặc đã hết hạn |
| 1004  | Không có quyền thực hiện hành động này |
| 2001  | Phòng không tồn tại |
| 2002  | Phòng đã đầy |
| 2003  | Phòng đang thi, không thể tham gia |
| 3001  | Bài thi đã kết thúc |
| 3002  | Câu hỏi không tồn tại trong bài thi này |
| 9999  | Lỗi Server nội bộ |

---

## 5. Chi Tiết Payload Từng Opcode

### 5.1 Đăng Ký — `REGISTER_REQ` (0x10)

```json
// Client → Server
{
  "username": "nguyenvana",
  "password": "MyP@ssw0rd",
  "display_name": "Nguyễn Văn A"
}
```

```json
// Server → Client  (REGISTER_RES 0x11)
{ "status": "ok", "user_id": 42 }
// hoặc
{ "status": "error", "msg": "Tên đăng nhập đã tồn tại", "error_code": 1002 }
```

---

### 5.2 Đăng Nhập — `LOGIN_REQ` (0x12)

```json
// Client → Server
{
  "username": "nguyenvana",
  "password": "MyP@ssw0rd"
}
```

```json
// Server → Client  (LOGIN_RES 0x13)
{
  "status": "ok",
  "user_id": 42,
  "display_name": "Nguyễn Văn A",
  "role": "user",           // "user" | "host" | "admin"
  "session_token": "a3f8c2d...e91b"   // Token gửi kèm mọi request tiếp theo
}
```

> **Lưu ý TV1 & TV2:** `session_token` được Server sinh ra (UUID v4), lưu vào bảng `Sessions`. Client gửi token này trong mọi gói tin tiếp theo bằng cách đặt vào Payload — KHÔNG đặt trong Header (để đơn giản hóa parsing).

---

### 5.3 Tạo Phòng Thi — `ROOM_CREATE_REQ` (0x22)

```json
// Client → Server  (chỉ Host mới được gửi)
{
  "session_token": "a3f8c2d...e91b",
  "room_name": "Thi thử Lập trình Mạng #1",
  "question_count": 20,
  "duration_seconds": 1200,
  "difficulty": "mixed",    // "easy" | "medium" | "hard" | "mixed"
  "topic": "networking"     // khớp với trường `topic` trong bảng Questions
}
```

```json
// Server → Client  (ROOM_CREATE_RES 0x23)
{
  "status": "ok",
  "room_id": "ROOM-7F3A",
  "join_code": "7F3A"
}
```

---

### 5.4 Tham Gia Phòng — `ROOM_JOIN_REQ` (0x24)

```json
// Client → Server
{
  "session_token": "...",
  "join_code": "7F3A"
}
```

```json
// Server → Client  (ROOM_JOIN_RES 0x25)
{
  "status": "ok",
  "room_id": "ROOM-7F3A",
  "room_name": "Thi thử Lập trình Mạng #1",
  "host_name": "Trần B",
  "question_count": 20,
  "duration_seconds": 1200,
  "current_players": [
    { "user_id": 5, "display_name": "Lê C" },
    { "user_id": 8, "display_name": "Phạm D" }
  ]
}
```

---

### 5.5 Bắt Đầu Thi — `HOST_START_REQ` (0x37) & `EXAM_START` (0x30)

```json
// Host → Server  (HOST_START_REQ 0x37)
{
  "session_token": "...",
  "room_id": "ROOM-7F3A"
}
```

```json
// Server → TẤT CẢ Client trong phòng  (EXAM_START 0x30)
{
  "room_id": "ROOM-7F3A",
  "start_time_utc": "2026-10-20T10:00:00Z",
  "duration_seconds": 1200,
  "questions": [
    {
      "q_id": 101,
      "order": 1,
      "content": "Giao thức nào hoạt động ở tầng Transport?",
      "options": {
        "A": "HTTP",
        "B": "TCP",
        "C": "IP",
        "D": "Ethernet"
      }
    }
    // ... thêm câu hỏi
  ]
}
```

> **Lưu ý TV1:** Đáp án ĐÚNG (`correct_answer`) **KHÔNG** được gửi trong `EXAM_START`. Chỉ gửi sau khi thu bài.

---

### 5.6 Gửi / Cập Nhật Đáp Án — `EXAM_SUBMIT_ANS` (0x31)

```json
// Client → Server  (có thể gửi nhiều lần để thay đổi đáp án)
{
  "session_token": "...",
  "room_id": "ROOM-7F3A",
  "q_id": 101,
  "selected": "B",
  "client_timestamp_utc": "2026-10-20T10:05:30Z"
}
```

```json
// Server → Client  (EXAM_ANS_ACK 0x32)
{ "status": "ok", "q_id": 101 }
```

---

### 5.7 Đồng Bộ Thời Gian — `EXAM_TIME_SYNC` (0x33)

```json
// Server → TẤT CẢ Client  (broadcast mỗi 5 giây)
{
  "room_id": "ROOM-7F3A",
  "remaining_seconds": 900
}
```

---

### 5.8 Thu Bài & Trả Kết Quả — `EXAM_FORCE_SUBMIT` (0x34) & `EXAM_RESULT` (0x35)

```json
// Server → TẤT CẢ Client  (EXAM_FORCE_SUBMIT 0x34)
{ "room_id": "ROOM-7F3A", "reason": "time_up" }
```

```json
// Server → từng Client  (EXAM_RESULT 0x35)
{
  "room_id": "ROOM-7F3A",
  "score": 18,
  "total": 20,
  "rank": 2,
  "details": [
    { "q_id": 101, "your_answer": "B", "correct_answer": "B", "is_correct": true },
    { "q_id": 102, "your_answer": "A", "correct_answer": "C", "is_correct": false }
  ]
}
```

---

### 5.9 Khôi Phục Phiên (Tính Năng Nâng Cao) — `RECONNECT_REQ` (0x03)

```json
// Client → Server  (sau khi mất kết nối và kết nối lại)
{
  "session_token": "a3f8c2d...e91b",
  "room_id": "ROOM-7F3A"
}
```

```json
// Server → Client  (RECONNECT_ACK 0x04)
{
  "status": "ok",
  "remaining_seconds": 840,
  "questions": [ /* đề thi như cũ */ ],
  "saved_answers": [
    { "q_id": 101, "selected": "B" }
  ]
}
```

---

### 5.10 Luyện Tập Cá Nhân — `PRACTICE_START_REQ` (0x38)

```json
// Client → Server
{
  "session_token": "...",
  "question_count": 10,
  "difficulty": "easy",
  "topic": "networking"
}
```

```json
// Server → Client  (PRACTICE_RESULT 0x39) — phản hồi ngay sau khi nộp
{
  "status": "ok",
  "score": 8,
  "total": 10,
  "details": [
    { "q_id": 55, "your_answer": "A", "correct_answer": "A", "is_correct": true }
  ]
}
```

---

## 6. Quy Trình Xử Lý Phía Server

```
[Nhận bytes từ socket]
        │
        ▼
[Đọc đúng 8 bytes Header]
        │
        ▼
[Kiểm tra VER == 0x01]──→ sai → Gửi ERROR (9999), đóng kết nối
        │ đúng
        ▼
[Đọc PAY_LEN bytes Payload]
        │
        ▼
[Parse JSON Payload]──→ lỗi JSON → Gửi ERROR (9999)
        │ ok
        ▼
[Xác thực session_token]──→ không hợp lệ → Gửi ERROR (1003)
        │ hợp lệ
        ▼
[Kiểm tra phân quyền theo OPC]──→ không đủ quyền → Gửi ERROR (1004)
        │ ok
        ▼
[Xử lý nghiệp vụ theo OPC]
        │
        ▼
[Gửi gói phản hồi]
```

---

## 7. Quy Ước Lập Trình

- **Byte Order:** Big-Endian cho tất cả trường số trong Header.
- **String Encoding:** UTF-8 cho toàn bộ Payload JSON.
- **Thời gian:** ISO 8601 UTC (`YYYY-MM-DDTHH:MM:SSZ`) cho mọi timestamp trong Payload.
- **Token:** UUID v4, 36 ký tự (có dấu gạch ngang), ví dụ: `a3f8c2d1-e91b-4c0f-b3d2-7f8e1a2b3c4d`.
- **Giải phóng tài nguyên:** Khi Client `DISCONNECT` hoặc timeout, Server phải xóa socket khỏi danh sách quản lý và giải phóng slot phòng nếu cần.
