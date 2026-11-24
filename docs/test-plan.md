# Kế hoạch kiểm thử KuizuHub

Mọi scenario dưới đây phải dùng C TCP server và client TCP thật. Màn/mock local
không được dùng làm bằng chứng nghiệm thu.

## Chặng 1 — contract, migration và an toàn dữ liệu

1. Tạo database rỗng, khởi động server và xác nhận `schema_migrations` có
   `001_initial` đến `005_profile_analytics`.
2. Chạy `PING` với JSON bị cắt thành nhiều `recv`, nhiều JSON trong một send,
   JSON lỗi và payload quá 64 KiB.
3. Đăng ký/login/logout; thử token thiếu, token hết hạn và password sai.
4. Đổi display name/password, xác nhận password cũ không login được và không có
   password/hash/token trong response hoặc `activity_logs`.

## Chặng 2 — phòng thi và kết quả

1. HOST tạo room, hai STUDENT join, mỗi người mở `GET_ROOM_LOBBY`; xác nhận
   lobby hiển thị participant thật từ server.
2. Student cố `START_ROOM` nhận `FORBIDDEN`; owner start room, room snapshot có
   đủ bốn option mỗi câu và `GET_EXAM` không chứa đáp án đúng.
3. Student đổi đáp án, tắt/mở GUI hoặc gọi lại `GET_EXAM`, xác nhận selected
   answer được restore từ server; submit lặp lại phải idempotent.
4. Rút ngắn `ended_at`, xác nhận worker auto-submit và room chuyển `ENDED`.
5. Trước `ENDED`, `GET_ROOM_RESULTS`/`GET_LEADERBOARD` nhận `CONFLICT`.
   Sau `ENDED`, owner thấy toàn bộ result, student chỉ thấy result/review của
   chính mình, outsider bị từ chối result nhưng xem được leaderboard.

## Chặng 3 — luyện tập và analytics

1. Start practice với số câu đủ/thiếu; case thiếu phải `CONFLICT` và không tạo
   session dang dở.
2. Autosave practice, đổi đáp án, submit hai lần; score/history chỉ ghi một lần.
3. `GET_MY_HISTORY` phân trang không lộ dữ liệu user khác.
4. `GET_MY_STATS` đối chiếu attempts, điểm trung bình, tỷ lệ đúng và bucket
   topic/difficulty với SQLite snapshot.
5. Sửa topic/difficulty câu hỏi gốc sau khi start bài mới và xác nhận stats của
   bài đã chốt vẫn dùng snapshot.

## Chặng 4 — GUI desktop thật

1. Đăng nhập bằng `python main.py`; xác nhận mọi thao tác network ở QThread,
   cửa sổ không freeze khi server phản hồi chậm.
2. Tạo/join/start room từ GUI, mở sảnh chờ, làm bài, autosave, submit và mở kết
   quả/leaderboard. Không màn nào trong luồng này được import `MockApiService`.
3. Luyện tập từ GUI, xem History/Stats: line chart điểm theo thời gian và bar
   chart tỷ lệ đúng theo topic.
4. ADMIN import CSV có một dòng lỗi: GUI nêu chính xác số dòng; import hợp lệ và
   export CSV theo filter xác nhận dữ liệu lấy từ `LIST_QUESTIONS` TCP.

## Lệnh regression

```bash
make clean && make && make test
python3 -m pytest client/tests -q
```

Trên Windows dùng `mingw32-make` thay cho `make`.
