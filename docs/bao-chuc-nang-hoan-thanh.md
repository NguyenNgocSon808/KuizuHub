# Chức năng Bảo đã hoàn thành

> Chỉ thêm một chức năng vào danh sách này khi nó đã hoàn thành đầy đủ: code đã
> được tích hợp vào server/client cần thiết, cập nhật protocol/migration liên
> quan, build không lỗi và test hoặc kịch bản tái hiện đã chạy thành công.

> Cập nhật tích hợp ngày **23/11/2026**: `mingw32-make test` chạy **32** test
> backend và `python -m pytest client/tests -q` chạy **7** test client đều đạt.

## Danh sách hoàn thành

## Gói tích hợp Phase 2–3: GUI thật, kết quả và analytics

- Phạm vi: entry point desktop chuyển sang `LiveMainWindow`, kết nối toàn bộ
  room/practice/exam/result/history/profile qua `PhaseOneApiService` chạy TCP
  trong `QThread`; không dùng `MockApiService` trong luồng demo.
- API: `GET_ROOM_LOBBY`, `GET_ROOM_RESULTS`, `GET_MY_HISTORY`, `GET_MY_STATS`,
  `GET_LEADERBOARD`, `UPDATE_MY_PROFILE`; thêm `ended_at`/đáp án đã lưu cho
  client khôi phục đúng trạng thái đề.
- Quyền riêng tư: kết quả và đáp án đúng chỉ trả sau `ENDED`; owner thấy bảng
  kết quả phòng, participant chỉ thấy kết quả/review của chính mình; leaderboard
  chỉ công bố sau khi phòng kết thúc.
- Dữ liệu: migration `005_profile_analytics.sql` thêm display name, taxonomy
  snapshot cho room/practice và index phục vụ history/stats. Sửa metadata câu
  hỏi gốc sau đó không làm sai analytics của bài đã chốt.
- Admin: Question Bank nhập JSON/CSV có báo số dòng lỗi và xuất CSV theo filter
  từ `LIST_QUESTIONS` TCP.
- File chính: `client/app/ui/live_main_window.py`,
  `client/app/services/tcp_api_service.py`, `server/src/history/history.c`,
  `server/src/room/room.c`, `server/src/auth/auth.c`,
  `server/migrations/005_profile_analytics.sql`.
- Kiểm thử: `server/tests/test_phase3_analytics.py` kiểm tra migration/profile,
  lịch sử/thống kê và quyền room result/leaderboard; smoke test offscreen xác
  nhận `LiveMainWindow` khởi tạo được.

## Audit log vòng đời room

- Phạm vi: ghi sự kiện cho `CREATE_ROOM`, `JOIN_ROOM`, `START_ROOM`,
  `SAVE_ANSWER`, `SUBMIT_EXAM`, auto-submit và room kết thúc bởi worker.
- Sự kiện: `ROOM_CREATED`, `ROOM_JOINED`, `ROOM_STARTED`, `ANSWER_SAVED`,
  `EXAM_SUBMITTED`, `EXAM_AUTO_SUBMITTED`, `ROOM_ENDED`. API `END_ROOM` thủ
  công giữ audit event `END_ROOM` sẵn có.
- An toàn dữ liệu: detail chỉ chứa metadata cần thiết như `rule_count`,
  `participant_count`, `question_count` hoặc `question_id`; tuyệt đối không
  ghi token, mật khẩu, tên phòng tự do, option đã chọn, đáp án đúng hay nội dung
  toàn bộ đề.
- File chính: `server/src/room/room.c`, `server/src/auth/auth.c`,
  `server/src/log/logger.c`, `server/tests/test_phase2_create_room.py`.
- Kiểm thử: Ubuntu 22.04.5 đã chạy `make test` thành công với 29 test pass.
  Test luồng submit kiểm tra năm event đồng thời quét detail để bảo đảm không
  có token, marker nhạy cảm do người dùng nhập hoặc đáp án đúng; test expiry
  worker kiểm tra auto-submit và `ROOM_ENDED` có actor hệ thống (`NULL`).

## Worker auto-submit và kết thúc room

- Phạm vi: server tự xử lý room `RUNNING` quá `ended_at`, không phụ thuộc GUI.
- Vòng đời: worker chạy mỗi giây, dùng transaction riêng cho từng room; chấm
  mọi participant `JOINED`/`IN_PROGRESS` thành `AUTO_SUBMITTED`, ghi điểm/audit
  và chuyển room sang `ENDED`.
- Kỹ thuật: worker được tạo khi `kz_server_run()` bắt đầu listen và được join
  khi server dừng; mỗi room dùng `BEGIN IMMEDIATE` nên không race với
  `SUBMIT_EXAM` của user.
- File chính: `server/src/core/server_socket.c`, `server/src/room/room.c`,
  `server/include/room.h` và `server/tests/test_phase2_create_room.py`.
- Kiểm thử đã chạy: Ubuntu 22.04.5, `make test` thành công với 29 test pass.
  Test đặt `ended_at` về quá khứ, xác nhận participant auto-submit/được chấm
  và room đổi sang `ENDED` trong tối đa 3 giây.
- Kết quả: thời hạn room được quyết định ở server, kể cả khi client đóng hoặc
  không gửi request nộp bài.

## `SUBMIT_EXAM`

- Phạm vi: participant nộp bài; server chấm theo snapshot room và lưu kết quả.
- Request/API: `SUBMIT_EXAM` với `room_id`; result gồm state, số câu đúng, tổng
  câu và điểm thang 10.
- Kỹ thuật: `BEGIN IMMEDIATE` giữ state check, chấm `attempt_answers` so với
  `correct_option_snapshot`, update `room_participants` và audit log trong một
  transaction. Request lặp là idempotent.
- File chính: `server/src/room/room.c`, `server/include/room.h`,
  `server/src/core/server_socket.c`, `docs/protocol.md` và
  `server/tests/test_phase2_create_room.py`.
- Kiểm thử đã chạy: Ubuntu 22.04.5, `make test` thành công với 28 test pass.
  Test kiểm tra điểm `1/3`, submit lặp trả cùng data, participant chỉ chuyển
  state một lần và chỉ một audit log được ghi.
- Kết quả: transaction là hàng rào chống user/timer chấm hai lần; submit sau
  hạn nhận state `AUTO_SUBMITTED`.

## `SAVE_ANSWER`

- Phạm vi: participant đang làm bài lưu hoặc đổi đáp án của một câu trong room.
- Request/API: `SAVE_ANSWER` với `room_id`, `question_id`, `option_id`.
- Kỹ thuật: transaction kiểm tra status `RUNNING`, `ended_at` từ server,
  participant `IN_PROGRESS` và question/option thuộc snapshot trước khi UPSERT
  vào `attempt_answers`.
- File chính: `server/src/room/room.c`, `server/include/room.h`,
  `server/src/core/server_socket.c`, `docs/protocol.md` và
  `server/tests/test_phase2_create_room.py`.
- Kiểm thử đã chạy: Ubuntu 22.04.5, `make test` thành công với 27 test pass.
  Test kiểm tra đổi đáp án không tạo dòng trùng, option sai bị từ chối và save
  sau `ended_at` trả `CONFLICT`.
- Kết quả: đáp án được lưu ở server theo snapshot; thời hạn do server quyết
  định, không do thời gian client gửi lên.

## `GET_EXAM`

- Phạm vi: participant lấy đề room đang `RUNNING` và đáp án đã lưu của chính
  mình.
- Request/API: `GET_EXAM` với `room_id`; room phải `RUNNING` và user phải có
  record trong `room_participants`.
- Kỹ thuật: response được xây từ `room_questions` và
  `room_question_options`, không đọc lại question bank và không serialise
  `correct_option_snapshot`. Mỗi câu trả `selected_option_id` hoặc `null`.
- File chính: `server/src/room/room.c`, `server/include/room.h`,
  `server/src/core/server_socket.c`, `docs/protocol.md` và
  `server/tests/test_phase2_create_room.py`.
- Kiểm thử đã chạy: Ubuntu 22.04.5, `make test` thành công với 26 test pass.
  Test kiểm tra trạng thái `WAITING`, participant, outsider, đáp án đã lưu và
  đảm bảo JSON không có đáp án đúng.
- Kết quả: đề đang làm ổn định theo snapshot và chỉ thí sinh thuộc phòng mới
  xem được.

## `START_ROOM`

- Phạm vi: chủ phòng bắt đầu phòng `WAITING`, chốt đề và chuyển participant đã
  join sang `IN_PROGRESS`.
- Request/API: `START_ROOM` với `room_id`; chỉ `owner_id` được gọi.
- Kỹ thuật: một `BEGIN IMMEDIATE` tạo snapshot `room_questions` và
  `room_question_options` theo rule trước, sau đó mới set `RUNNING`,
  `started_at` và `ended_at`. Snapshot lỗi thì rollback, phòng giữ `WAITING`.
- File chính: `server/migrations/004_room_question_options.sql`,
  `server/src/room/room.c`, `server/src/core/server_socket.c` và
  `server/tests/test_phase2_create_room.py`.
- Kiểm thử đã chạy: Ubuntu 22.04.5, `make test` thành công với 25 test pass.
  Test xác nhận snapshot 3 câu/12 options, participant đổi state, start lặp bị
  từ chối, và snapshot thiếu option rollback hoàn toàn.
- Kết quả: server không thể đưa room sang `RUNNING` trước khi đề snapshot hoàn
  chỉnh đã được ghi vào database.

## `JOIN_ROOM`

- Phạm vi: user đã đăng nhập tham gia phòng đang `WAITING`.
- Request/API: `JOIN_ROOM` với `room_id`; thành công trả trạng thái
  `JOINED` và số participant hiện tại.
- Kỹ thuật: `BEGIN IMMEDIATE` bao gồm kiểm tra phòng, kiểm tra trạng thái,
  insert vào `room_participants` và đếm participant. Khóa chính
  `(room_id, user_id)` là hàng rào cuối cùng chống join trùng.
- File chính: `server/src/room/room.c`, `server/include/room.h`,
  `server/src/core/server_socket.c`, `docs/protocol.md` và
  `server/tests/test_phase2_create_room.py`.
- Kiểm thử đã chạy: Ubuntu 22.04.5, `make clean && make test` thành công với
  23 test pass. Test kiểm tra join thành công, join trùng trả `CONFLICT` và
  phòng `RUNNING` từ chối join.
- Kết quả: một user chỉ có thể có một participant record trong mỗi phòng;
  không có record mới nếu phòng không còn `WAITING`.

## `LIST_ROOMS`

- Phạm vi: user đã đăng nhập xem danh sách phòng mà không nhận đề thi hay đáp
  án.
- Request/API: `LIST_ROOMS` qua TCP NDJSON; response có `id`, `name`,
  `owner_id`, `owner_name`, `status`, `duration_seconds` và
  `participant_count`.
- Kỹ thuật: một câu SQL `JOIN users` + `LEFT JOIN room_participants` +
  `GROUP BY`, nên lấy owner và số participant trong một lượt truy vấn; status
  được giới hạn ở `WAITING`, `RUNNING`, `ENDED`.
- File chính: `server/src/auth/auth.c`,
  `server/tests/test_phase2_create_room.py` và
  `client/app/services/tcp_api_service.py`.
- Kiểm thử đã chạy: Ubuntu 22.04.5, `make clean && make test` thành công với
  22 test pass. Test mới kiểm tra 3 trạng thái và số participant 2/1/0.
- Kết quả: user có session hợp lệ nhận danh sách phòng có owner và số người
  tham gia chính xác; client có wrapper `list_rooms()` bất đồng bộ.

## `CREATE_ROOM`

- Phạm vi: Host hoặc admin tạo phòng thi ở trạng thái `WAITING`, với tên,
  thời lượng và một hoặc nhiều rule chọn câu hỏi.
- Request/API: `CREATE_ROOM` qua TCP NDJSON. Server xác thực session, từ chối
  role không có quyền, validate payload/rule, kiểm tra đủ câu active và tạo dữ
  liệu trong một SQLite transaction.
- File chính: `server/src/room/room.c`, `server/include/room.h`,
  `server/src/protocol/ndjson.c`, `docs/protocol.md` và
  `server/tests/test_phase2_create_room.py`.
- Kiểm thử đã chạy: trên Ubuntu 22.04.5, chạy
  `make clean && make && make test` thành công. Tổng cộng 18 test pass, gồm 4
  test `CREATE_ROOM`: tạo thành công, chặn student, chặn payload/rule không hợp
  lệ và rollback khi không đủ câu hỏi.
- Kết quả: server trả `room_id`, `name`, `status: "WAITING"` và
  `duration_seconds`; ghi audit log `ROOM_CREATED`; mọi lỗi tạo phòng không để
  lại bản ghi dở dang trong database.

## Chế độ luyện tập

- Phạm vi: user tạo bài theo topic/difficulty, nhận snapshot đề không lộ đáp
  án, có thể đổi đáp án và nộp để server chấm theo thang 10.
- Request/API: `START_PRACTICE`, `SAVE_PRACTICE_ANSWER` và `SUBMIT_PRACTICE`.
  Submit idempotent; nộp sau khi hết hạn được lưu `AUTO_SUBMITTED`.
- File chính: `server/migrations/003_practice_sessions.sql`,
  `server/src/practice/practice.c`, `server/include/practice.h`,
  `server/tests/test_phase2_practice.py`, `scripts/seed_db.py` và
  `docs/protocol.md`.
- Kiểm thử đã chạy: trên Ubuntu 22.04.5, `make clean && make && make test`
  thành công với 21 test pass. Ba test luyện tập kiểm tra migration/snapshot,
  đổi đáp án + submit idempotent, và lỗi thiếu câu.
- Kết quả: session/đề/lựa chọn được snapshot trong SQLite, đáp án là UPSERT,
  history chỉ ghi một lần sau submit và response không trả đáp án đúng khi bắt
  đầu bài.


<!--
Mẫu để thêm sau khi hoàn thành:

## <Tên chức năng>

- Phạm vi: ...
- Request/API: ...
- File chính: ...
- Kiểm thử đã chạy: ...
- Kết quả: ...
-->
