# Kịch bản demo 3–5 phút

## Chuẩn bị

```bash
bash scripts/reset_demo.sh
make run
```

Mở ba client bằng `python3 main.py` (hoặc ba máy cùng LAN, đặt
`KUIZUHUB_HOST` về IP máy server). Tạo trước một HOST và hai STUDENT; có thể tạo
ADMIN riêng để minh họa question bank.

## Luồng chính

1. HOST đăng nhập, tạo room `TCP demo`, 60 giây, rule đủ câu `TCP Socket/easy`.
2. Hai STUDENT đăng nhập, vào phòng. HOST và STUDENT mở Sảnh chờ để thấy cùng
   danh sách participant do server trả về.
3. HOST bấm Start. STUDENT mở đề, chọn một đáp án, đổi đáp án và thấy trạng thái
   “Đã lưu đáp án trên server”.
4. STUDENT A nộp sớm. STUDENT B để hết giờ để worker auto-submit. HOST mở kết
   quả: thấy cả hai điểm; STUDENT A chỉ thấy review của mình.
5. Từ room đã kết thúc, mở leaderboard. Dùng token STUDENT gọi kết quả room
   khác hoặc thử start room để minh họa `FORBIDDEN`.
6. STUDENT tạo một practice, nộp, vào Lịch sử & thống kê để hiện line/bar chart.
7. ADMIN import CSV hợp lệ, export CSV theo filter; thử CSV có dòng sai để hiện
   validation theo số dòng.

## Dấu hiệu bắt buộc khi demo

- Log server có `ROOM_CREATED`, `ROOM_JOINED`, `ROOM_STARTED`, `ANSWER_SAVED`,
  `EXAM_SUBMITTED`/`EXAM_AUTO_SUBMITTED`, `ROOM_ENDED`.
- Không có password, hash, token hoặc correct answer trong log.
- Trước khi room `ENDED`, không UI/API nào hiển thị đáp án đúng.
