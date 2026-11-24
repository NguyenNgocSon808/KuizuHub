# KuizuHub — Database Phase 1–3

Database SQLite runtime nằm tại `server/data/exam.db`; file này bị Git ignore. Nguồn tái tạo là:

- `server/migrations/001_initial.sql`: schema ban đầu.
- `server/migrations/002_question_explanation.sql`: thêm `questions.explanation` cho ngân hàng câu hỏi Phase 1.
- `server/migrations/003_practice_sessions.sql`: thêm phiên luyện tập, snapshot đề,
  đáp án đang làm và các index liên quan.
- `server/migrations/004_room_question_options.sql`: thêm snapshot bốn lựa chọn
  cho đề phòng thi.
- `server/migrations/005_profile_analytics.sql`: thêm `users.display_name`,
  snapshot topic/độ khó cho đề đã chốt, và index phục vụ history/analytics.
- `server/seed/questions.json`: dữ liệu câu hỏi nguồn.
- `scripts/init_db.sh`: xóa database demo cũ và tạo lại từ toàn bộ migration/seed.

Chạy từ repository root:

```bash
bash scripts/init_db.sh
```

Script kiểm tra ít nhất 30 câu hỏi, tối thiểu 3 topic, và mỗi topic có đủ `easy`, `medium`, `hard`. Mỗi câu phải có đúng 4 lựa chọn và đúng một đáp án.

## Bảng

| Bảng | Vai trò |
|---|---|
| `users`, `sessions` | Tài khoản (gồm `display_name`) và phiên đăng nhập. |
| `questions`, `question_options` | Ngân hàng câu hỏi và bốn lựa chọn. |
| `exam_rooms`, `room_question_rules`, `room_questions`, `room_question_options` | Phòng thi, rule, snapshot câu hỏi/lựa chọn, topic/độ khó snapshot cho analytics. |
| `room_participants`, `attempt_answers` | Trạng thái thí sinh và câu trả lời. |
| `practice_sessions`, `practice_session_questions`, `practice_session_options`, `practice_answers` | Phiên luyện tập đang diễn ra, snapshot đề/lựa chọn và đáp án autosave. |
| `practice_attempts` | Lịch sử/tóm tắt kết quả luyện tập sau khi nộp. |
| `activity_logs` | Audit log cho thay đổi trạng thái quan trọng. |

`questions.correct_option_id` được set sau khi bốn option của câu đã được tạo. `questions.explanation` là chuỗi rỗng nếu câu hỏi không có giải thích. `room_questions` và `practice_session_questions` lưu taxonomy snapshot cho bản ghi mới; số liệu cũ không có snapshot sẽ fallback sang metadata hiện hành. Các migration sau phải được thêm file mới, không sửa migration đã chạy trong môi trường chung.

Khi server khởi động, `schema_migrations` ghi nhận migration đã chạy. Database cũ có schema 001 sẽ được đánh dấu `001_initial` và tự chạy migration 002–005 một lần; database mới chạy toàn bộ migration. `scripts/seed_db.py` cũng áp dụng toàn bộ migration khi tạo DB demo.
