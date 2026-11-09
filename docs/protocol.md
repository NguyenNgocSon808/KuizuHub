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
- `token`: session token, chỉ có ở request đã xác thực (chưa dùng ở Phase 0).
- `payload`: object, có thể rỗng.

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
| `UNAUTHORIZED` | Thiếu, hết hạn hoặc sai session token. |
| `FORBIDDEN` | Đã xác thực nhưng không có quyền. |
| `NOT_FOUND` | Không có resource hoặc request type được hỗ trợ. |
| `CONFLICT` | Trạng thái hiện tại không cho phép thao tác. |
| `INTERNAL_ERROR` | Lỗi nội bộ không thể phân loại khác. |

## Request hiện có ở Phase 0

### `PING`

Request này không cần token và xác minh client/server đã thống nhất framing.

```json
{"type":"PING","request_id":"ping-001","payload":{}}
```

```json
{"type":"OK","request_id":"ping-001","data":{"message":"pong"}}
```

Các request nghiệp vụ (`REGISTER`, `LOGIN`, room, exam…) sẽ được bổ sung trước hoặc cùng pull request triển khai chúng. Không được tự tạo response schema khác envelope này.
