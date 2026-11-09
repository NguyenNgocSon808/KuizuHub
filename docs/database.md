# KuizuHub — Database Phase 0

Database SQLite runtime nằm tại `server/data/exam.db`; file này bị Git ignore. Nguồn tái tạo là:

- `server/migrations/001_initial.sql`: schema ban đầu.
- `server/seed/questions.json`: dữ liệu câu hỏi nguồn.
- `scripts/init_db.sh`: xóa database demo cũ và tạo lại từ hai file trên.

Chạy từ repository root:

```bash
bash scripts/init_db.sh
```

Script kiểm tra ít nhất 30 câu hỏi, tối thiểu 3 topic, và mỗi topic có đủ `easy`, `medium`, `hard`. Mỗi câu phải có đúng 4 lựa chọn và đúng một đáp án.

## Bảng

| Bảng | Vai trò |
|---|---|
| `users`, `sessions` | Tài khoản và phiên đăng nhập. |
| `questions`, `question_options` | Ngân hàng câu hỏi và bốn lựa chọn. |
| `exam_rooms`, `room_question_rules`, `room_questions` | Phòng thi, rule và snapshot đề. |
| `room_participants`, `attempt_answers` | Trạng thái thí sinh và câu trả lời. |
| `practice_attempts` | Lịch sử luyện tập. |
| `activity_logs` | Audit log cho thay đổi trạng thái quan trọng. |

`questions.correct_option_id` được set sau khi bốn option của câu đã được tạo. Các migration sau phải được thêm file mới, không sửa migration đã chạy trong môi trường chung.
