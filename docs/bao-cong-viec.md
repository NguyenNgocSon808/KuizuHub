# Công việc của Bảo - luồng luyện tập và phòng thi

> Cập nhật theo trạng thái repository ngày 22/11/2026. Tài liệu này biến bảng
> phân công của nhóm thành backlog kỹ thuật có thể làm và kiểm thử; không thay
> thế `docs/protocol.md` - đây vẫn là nguồn đúng duy nhất cho hợp đồng TCP.

> **Cập nhật tích hợp 23/11/2026:** backlog bên dưới là ảnh chụp trước khi
> hoàn thiện. `GET_ROOM_RESULTS`, `GET_ROOM_LOBBY`, GUI TCP thật cho
> room/practice/result, history/stats/leaderboard/profile và CSV admin đã được
> tích hợp. Trạng thái/kịch bản nghiệm thu hiện hành nằm ở `README.md`,
> `docs/protocol.md`, `docs/test-plan.md` và `docs/demo-script.md`.

## 1. Phạm vi Bảo chịu trách nhiệm

Theo bảng phân công, Bảo chịu trách nhiệm các tính năng 8-14, tổng **10 điểm**:

| Mục | Điểm | Kết quả cần có |
|---|---:|---|
| Chế độ luyện tập | 1 | Chọn số câu, thời gian, chủ đề/độ khó; làm bài và nhận kết quả. |
| ✅ Tạo phòng thi | 2 | Chủ phòng tạo phòng, đặt số câu, thời gian, chủ đề và độ khó. |
| Xem danh sách phòng | 1 | Hiện phòng với trạng thái chờ / đang diễn ra / đã kết thúc. |
| Tham gia phòng | 2 | Chỉ cho vào phòng `WAITING`; server kiểm tra và chống join trùng. |
| Bắt đầu bài thi | 1 | Chủ phòng khởi động; server chốt đề, gửi đề và mốc thời gian. |
| Thay đổi đáp án | 1 | Lưu đáp án ở server; được đổi khi bài còn hạn. |
| Nộp bài và chấm điểm | 2 | Nộp sớm; hết giờ server tự nộp và chấm theo đáp án đã lưu. |

Mục **Giao diện desktop** là việc chung của cả Bảo, Vương và Sơn. Kế hoạch
trong `PLAN.md` giao phần màn hình thi/kết quả chủ yếu cho Người 3 (Vương), nên
Bảo cần chịu trách nhiệm phần API/TCP và luồng nghiệp vụ phía server; chỉ nhận
phần UI đã thống nhất với Vương để tránh làm trùng.

## 2. Hiện trạng thực tế của repository

### Đã có, có thể dùng ngay

- Server C99 chạy TCP NDJSON, SQLite, tài khoản/session và middleware
  `require_session()` / `require_room_owner()`.
- Schema ban đầu đã có các bảng `exam_rooms`, `room_question_rules`,
  `room_questions`, `room_participants`, `attempt_answers` và
  `practice_attempts`.
- `LIST_ROOMS` đã trả owner, status và số participant bằng một truy vấn
  aggregate. `JOIN_ROOM` đã ghi participant trong transaction và chặn join
  trùng. `START_ROOM` đã chốt snapshot đề/lựa chọn trước khi chuyển `RUNNING`.
  `END_ROOM` hiện mới là bản guard tối thiểu; auto-end và chấm điểm room vẫn
  chưa hoàn thiện.
- Seed có ngân hàng câu hỏi và API quản trị câu hỏi của Vương đã chạy qua TCP.
- `PhaseOneApiService` đã có worker `QThread`, có thể mở rộng bằng các wrapper
  request mới mà không làm treo UI.
- `CREATE_ROOM` đã chạy qua TCP thật: xác thực role `HOST`/`ADMIN`, validate
  rule, kiểm tra số câu active, tạo phòng/rule trong transaction và ghi audit
  log. Build Ubuntu 22.04.5 không warning; 4 integration test riêng đã pass.

### Chưa có - đây là backlog trực tiếp của Bảo

- `server/src/room/room.c` hiện có `CREATE_ROOM`; `server/src/practice/practice.c`
  hiện có luồng luyện tập; `exam/` vẫn chỉ có `.gitkeep`.
- Dispatcher chưa nhận `GET_ROOM_RESULTS`.
- Chức năng còn thiếu chính của room exam là API kết quả sau khi room `ENDED`.
- Entry point GUI thực (`main.py` -> `PhaseOneMainWindow`) hiện chỉ có
  đăng ký/đăng nhập/dashboard/question bank. Các màn Rooms/Exam/Practice cũ
  dùng `MockApiService` và JSON cục bộ, nên **không được dùng làm bằng chứng
  hoàn thành tính năng TCP thật**.
- Đã có test tự động cho `CREATE_ROOM` và luyện tập; các flow phòng thi còn lại
  chưa có test. `docs/demo-script.md` và `docs/test-plan.md` vẫn đang rỗng.

Không nên phát triển tiếp `server/server.c` hay `server/network/`: Makefile
hiện tại chỉ build `server/src/main.c`, `src/core/`, `src/protocol/`,
`src/auth/`, `src/question/` và `src/log/`.

## 3. Việc cần chốt trước khi viết code

- [ ] Họp ngắn với Sơn và Vương, chốt các request bên dưới rồi cập nhật đầy đủ
  `docs/protocol.md`. Không tự đổi format response.
- [x] Chốt role tạo phòng là `HOST` và `ADMIN`; `STUDENT` bị server từ chối.
  `STUDENT` chỉ join/làm bài. Dù GUI có ẩn nút, server vẫn phải kiểm tra.
- [ ] Chốt quy ước `score`: khuyến nghị thang 10, `correct_count / total * 10`,
  làm tròn rõ ràng; dùng duy nhất một quy tắc ở practice và room exam.
- [ ] Chốt ID đáp án trong giao thức: dùng `option_id` (ID SQLite), không dùng
  A/B/C/D hoặc `correct_option_index` từ API admin.
- [ ] Không sửa migration `001_initial.sql` đã có người dùng. Mọi thay đổi
  schema phải là migration mới, ví dụ `003_exam_snapshots.sql`, và phải chạy
  được cả DB mới lẫn DB Phase 1 hiện có.

### Bổ sung dữ liệu cần thiết

Schema hiện tại là nền tảng tốt, nhưng chưa đủ để "chốt đề" an toàn:

- [ ] Thêm snapshot **bốn lựa chọn** của mỗi câu trong phòng (ví dụ bảng
  `room_question_options`). `room_questions` chỉ đang lưu nội dung câu và ID
  đáp án đúng; nếu admin sửa option sau khi start thì đề cũ có thể bị đổi.
- [x] Thiết kế phiên luyện tập có trạng thái/snapshot/đáp án. Bảng
  `practice_attempts` hiện chỉ lưu kết quả cuối và có các cột `score`,
  `correct_count`, `total` không được rỗng, nên không thể dùng trực tiếp làm
  attempt đang diễn ra. Có thể thêm `practice_sessions`,
  `practice_session_questions`, `practice_answers`; khi nộp thì ghi summary
  vào `practice_attempts` để Vương dùng cho lịch sử/biểu đồ.
- [x] Bổ sung index cho session luyện tập và practice answer; migration chạy
  được từ DB Phase 1 trong test tự động.
- [ ] Bổ sung index cần thiết cho các snapshot option của phòng thi; kiểm tra
  foreign key và rollback transaction.

## 4. Hợp đồng API Bảo cần đưa vào `docs/protocol.md`

Tất cả request dùng envelope NDJSON hiện có, cần token hợp lệ, và trả đáp án
đúng **chỉ sau khi bài/phòng đã kết thúc**. Tên request dưới đây bám theo
`PLAN.md`; payload/response chi tiết phải được chốt trước khi UI gọi.

| Request | Ai được gọi | Payload tối thiểu | Kết quả / điều kiện server |
|---|---|---|---|
| ✅ `START_PRACTICE` | user đăng nhập | `topic`, `difficulty`, `question_count`, `duration_seconds` | Validate cấu hình, chọn đủ câu active, tạo snapshot attempt và trả câu/options không có đáp án đúng. Không đủ câu: `CONFLICT`. |
| ✅ `SAVE_PRACTICE_ANSWER` | chủ attempt | `attempt_id`, `question_id`, `selected_option_position` | UPSERT đáp án của chính user; kiểm tra option thuộc snapshot và còn thời gian. |
| ✅ `SUBMIT_PRACTICE` | chủ attempt | `attempt_id` | Idempotent: chấm ở server, lưu summary/history và trả điểm. Gọi lần hai trả cùng kết quả. |
| ✅ `CREATE_ROOM` | `HOST`/`ADMIN` | `name`, `duration_seconds`, `rules:[{topic,difficulty,quantity}]` | Validate rule và số câu active, tạo phòng `WAITING`; owner không tự động là participant. |
| ✅ `LIST_ROOMS` | user đăng nhập | không có | Trả `id`, `name`, `owner_name`, `status`, `duration_seconds`, `participant_count`; không trả đề/đáp án. Một truy vấn `JOIN + GROUP BY`, không N+1. |
| ✅ `JOIN_ROOM` | user đăng nhập | `room_id` | Transaction: chỉ `WAITING`, không join trùng; trả trạng thái và số người. `RUNNING`/`ENDED`: `CONFLICT`. |
| ✅ `START_ROOM` | đúng owner | `room_id` | Transaction: kiểm tra `WAITING`, có đủ câu theo rule; snapshot câu + option, set `started_at`, `ended_at`, `RUNNING`, chuyển người tham gia sang `IN_PROGRESS`. |
| ✅ `GET_EXAM` | participant | `room_id` | Chỉ phòng `RUNNING`; trả snapshot theo thứ tự và đáp án đã lưu của caller, tuyệt đối không có đáp án đúng. |
| ✅ `SAVE_ANSWER` | participant | `room_id`, `question_id`, `option_id` | UPSERT; chỉ `RUNNING`, trước `ended_at`, option phải thuộc snapshot. Sau hạn: `CONFLICT`. |
| ✅ `SUBMIT_EXAM` | participant | `room_id` | Transaction chống race với timer; chấm snapshot, ghi `submitted_at`, điểm/số đúng, state `SUBMITTED`; idempotent. |
| `GET_ROOM_RESULTS` | owner hoặc participant | `room_id` | Owner xem toàn bộ sau `ENDED`; student chỉ xem chính mình sau `ENDED`. |

Nếu làm event realtime trong đợt này, hợp đồng event không có `request_id`:
`EVENT_PARTICIPANT_JOINED`, `EVENT_ROOM_STARTED`, `EVENT_ROOM_ENDED`,
`EVENT_EXAM_AUTO_SUBMITTED`. Nếu chưa đủ thời gian để push, GUI phải refresh
qua API có kiểm soát; không mô phỏng local event rồi coi là server realtime.

## 5. Thứ tự triển khai đề xuất

### A. Chuẩn bị module, migration và contract

- [x] Tạo `server/include/room.h` và `server/src/room/room.c` cho
  `CREATE_ROOM`.
- [x] Tạo `server/include/practice.h` và `server/src/practice/practice.c`.
- [ ] Tạo `server/include/exam.h` và implementation tương ứng.
- [x] Thêm `room.c` vào `server/Makefile`; thêm route `CREATE_ROOM` vào
  `server/src/core/server_socket.c`.
- [x] Thêm migration `003_practice_sessions.sql` và mở rộng `scripts/seed_db.py`.
- [x] Cập nhật `docs/protocol.md` và `docs/database.md` cho `CREATE_ROOM`/
  luyện tập.
- [ ] Cập nhật `docs/test-plan.md` và `docs/demo-script.md` cho các flow còn lại.

### B. Chế độ luyện tập (mục 8)

- [x] Viết truy vấn chọn ngẫu nhiên chỉ từ câu `is_active = 1`, lọc đúng
  topic/difficulty và đúng số lượng yêu cầu.
- [x] Tạo snapshot một lần khi bắt đầu. Không chọn lại câu ở lúc nộp và không
  đọc đáp án đúng từ client.
- [x] Lưu đáp án theo UPSERT, cho phép đổi đáp án khi chưa hết hạn.
- [x] Nộp/chấm hoàn toàn ở server, lưu `practice_attempts` để luồng history của
  Vương dùng được.
- [x] Trả kết quả: `correct_count`, `total`, `score`, `state`; chỉ trả
  review đáp án/giải thích theo quy tắc đã chốt.

### C. Vòng đời phòng thi (mục 9-12)

- [x] `CREATE_ROOM`: validate tên, duration, mỗi rule hợp lệ, quantity dương
  và có đủ câu active; tạo phòng/rule trong cùng transaction.
- [x] `LIST_ROOMS`: truy vấn owner và số participant, không N+1 query, có status
  đúng enum `WAITING`, `RUNNING`, `ENDED`.
- [x] `JOIN_ROOM`: transaction ngắn; kiểm tra trạng thái trong transaction;
  unique `(room_id,user_id)` là hàng rào cuối cùng chống join trùng.
- [x] Hoàn thiện `START_ROOM`: thay bản guard đang có bằng lifecycle đầy đủ;
  không được set `RUNNING` nếu snapshot chưa tạo xong.
- [x] `GET_EXAM`: xác minh participant và status trước khi trả snapshot.

### D. Lưu đáp án, nộp và hết giờ (mục 13-14)

- [x] `SAVE_ANSWER` kiểm tra timestamp của server, participant, question/option
  của room snapshot; ghi UPSERT trong `attempt_answers`.
- [x] `SUBMIT_EXAM` dùng transaction `BEGIN IMMEDIATE` (hoặc cơ chế SQLite
  tương đương đã kiểm thử) để timer và user không chấm hai lần.
- [x] Viết worker/timer theo chu kỳ 1-2 giây: tìm room quá `ended_at`, chấm mọi
  `JOINED`/`IN_PROGRESS` chưa nộp, gán `AUTO_SUBMITTED`, rồi chuyển room
  `ENDED`. Start/stop worker gắn với vòng đời server, không tạo timer trên GUI.
- [x] Ghi `activity_logs` cho create/join/start/save/submit/auto-submit/end.
  Log chỉ chứa metadata tối thiểu (ID, số lượng, trạng thái); không ghi token,
  mật khẩu, tên phòng tự do, đáp án đã chọn/đáp án đúng hay toàn bộ đề.

### E. Tích hợp GUI chung

- [ ] Bảo thêm wrapper bất đồng bộ cho toàn bộ request của mình trong
  `client/app/services/tcp_api_service.py`; giữ network I/O trong `QThread`.
  Hiện đã có wrapper cho `CREATE_ROOM`, `LIST_ROOMS`, `JOIN_ROOM`, `START_ROOM`, `GET_EXAM`, `SAVE_ANSWER`, `SUBMIT_EXAM` và các
  request luyện tập.
- [ ] Cùng Vương nối các màn Room list/Create/Waiting/Exam/Result/Practice vào
  API thật. Màn phải hiển thị loading, lỗi protocol và trạng thái lưu đáp án.
- [ ] Không import `MockApiService` vào entry point dùng để demo. Các mock page
  chỉ nên giữ làm prototype hoặc loại khỏi luồng demo.
- [ ] Exam UI cần timer chỉ để hiển thị; server là nguồn quyết định hết giờ.
  Sau mỗi chọn đáp án gọi autosave và báo "Đã lưu" chỉ khi nhận `OK`.

## 6. Quy tắc nghiệp vụ bắt buộc

- `Room`: `WAITING -> RUNNING -> ENDED`; không join sau khi chạy, không start
  lại, không end/start đảo trạng thái.
- `Attempt`: `JOINED -> IN_PROGRESS -> SUBMITTED | AUTO_SUBMITTED`.
- Chỉ owner được start/end và xem toàn bộ kết quả. Người không join không được
  `GET_EXAM`; student không được đề/kết quả của người khác.
- Khi start, đề là snapshot; sửa/disable ngân hàng câu hỏi sau đó không làm đổi
  bài đang chạy.
- Client không gửi score/correct answer và server không tin giá trị đó.
- Tất cả lỗi dùng code chuẩn: `BAD_REQUEST`, `UNAUTHORIZED`, `FORBIDDEN`,
  `NOT_FOUND`, `CONFLICT`, `INTERNAL_ERROR`.
- DB có mutex/busy timeout sẵn ở core, nhưng Bảo vẫn phải để transaction ngắn
  và rollback đầy đủ khi một bước tạo phòng/snapshot thất bại.

## 7. Kiểm thử Bảo phải tự thêm và chạy

Tạo file integration riêng, ví dụ `server/tests/test_phase2_exam_flow.py`, khởi
động server với SQLite tạm và thao tác bằng TCP thật. Ít nhất phải có các case:

- [x] Practice: cấu hình đủ câu -> đổi đáp án -> nộp -> điểm đúng và chỉ có một
  history summary; cấu hình thiếu câu trả `CONFLICT` kèm số có thể dùng.
- [x] Create: host tạo phòng/rule thành công; student bị `FORBIDDEN`; payload
  sai bị `BAD_REQUEST`; thiếu câu trả `CONFLICT` và transaction rollback.
- [ ] List/join: list thấy số người/trạng thái; student join được một lần;
  join lặp không tạo row trùng; join sau start bị `CONFLICT`.
- [ ] Permission: student hoặc user lạ không start; người chưa join không lấy
  đề/lưu/nộp; owner không phải room owner nhận `FORBIDDEN`.
- [ ] Snapshot: sửa câu hoặc option gốc sau `START_ROOM` nhưng đề đang chạy và
  cách chấm không đổi.
- [ ] Answer: option không thuộc câu/room bị từ chối; save cùng question thay
  đáp án cũ; save sau `ended_at` bị `CONFLICT`.
- [ ] Submit: nộp hai lần trả cùng kết quả, không nhân đôi log/history/chấm.
- [ ] Timer: rút thời gian phòng xuống 1-2 giây, người chưa nộp được
  `AUTO_SUBMITTED`, room thành `ENDED` và kết quả đúng.
- [ ] Visibility: trước `ENDED` không lộ đúng/sai/đáp án; sau `ENDED` owner
  thấy đủ, student chỉ thấy mình.
- [x] Regression server: chạy `make clean && make && make test` trên Ubuntu
  22.04.5 - 29 test pass, gồm regression audit log.
- [ ] Regression client: chạy `python -m pytest client/tests -q` sau khi cài
  dependency PySide6.

## 8. Checklist bàn giao và demo

- [x] `make clean && make` không có warning mới với `-Wall -Wextra -Werror
  -pedantic` trên Ubuntu 22.04.5.
- [ ] Clone/DB mới chạy migration và seed được từ đầu; DB cũ Phase 1 migrate
  được, không mất dữ liệu.
- [x] `docs/protocol.md` có request/response/error `CREATE_ROOM` mới.
- [ ] Demo tối thiểu ba client: host tạo phòng 10 câu/10 phút, hai student join,
  host start, mỗi student đổi đáp án; một người nộp sớm, người còn lại auto
  submit; owner và student xem đúng phần kết quả được phép.
- [ ] Demo thêm một bài practice và một lỗi có chủ ý (thiếu câu, join sau start
  hoặc student start room) để chứng minh server có kiểm soát.
- [ ] Trong phần trình bày, Bảo giải thích được snapshot đề, quyền owner/
  participant, UPSERT đáp án, transaction/idempotency và server-side timer.

## 9. Phối hợp bàn giao

| Với ai | Bảo cần nhận | Bảo cần bàn giao |
|---|---|---|
| Sơn | session/user helper, DB wrapper, log convention, review quyền và lifecycle worker | endpoint mới, migration, test quyền/race để Sơn review trước merge |
| Vương | bank câu hỏi active có topic/difficulty/options; thiết kế màn thi/kết quả | snapshot/response không lộ đáp án, wrapper TCP, dữ liệu result/history summary cho GUI và analytics |
| Cả nhóm | format protocol đã chốt | một scenario demo end-to-end chạy từ DB reset, không dùng mock cục bộ |

## 10. Ưu tiên khi thiếu thời gian

1. Hoàn thành backend TCP thật cho mục 8-14 và test quyền/timer/snapshot.
2. Nối UI tối thiểu vào API thật để demo được ba client.
3. Sau khi luồng cốt lõi ổn định mới thêm event realtime, filter/phân trang đẹp
   hoặc polish UI. Không đổi ưu tiên sang màn mock/biểu đồ khi server chưa tự
   chấm được.
