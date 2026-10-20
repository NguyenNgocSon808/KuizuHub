/**
 * @file reconnect.h
 * @brief Module khôi phục phiên thi sau khi mất kết nối mạng.
 *
 * Khi Client bị ngắt kết nối giữa chừng (mất wifi, ...), Server vẫn
 * giữ trạng thái phiên thi theo session_token trong tối đa
 * RECONNECT_TTL_SEC giây. Client có thể kết nối lại và gửi
 * RECONNECT_REQ để tiếp tục bài thi từ chỗ dừng.
 *
 * Luồng:
 *   Client mất mạng
 *     → Server phát hiện socket đóng → đánh dấu ClientCtx DEAD
 *       nhưng LƯU snapshot (saved_answers, room_id, remaining_sec)
 *         vào bảng g_reconnect_table[]
 *   Client kết nối lại
 *     → Gửi RECONNECT_REQ {session_token, room_id}
 *     → Server tra cứu bảng → nếu còn hạn → khôi phục ClientCtx mới
 *       → Gửi RECONNECT_ACK {remaining_seconds, questions, saved_answers}
 */

#ifndef KUIZU_RECONNECT_H
#define KUIZU_RECONNECT_H

#include <time.h>
#include <stdint.h>
#include "../server.h"

/* ------------------------------------------------------------------ */
/*  Hằng số                                                            */
/* ------------------------------------------------------------------ */

#define RECONNECT_MAX_SESSIONS  64
#define RECONNECT_TTL_SEC       120     /**< Giữ session tối đa 2 phút     */
#define MAX_SAVED_ANSWERS       50      /**< Số câu hỏi tối đa trong 1 bài */

/* ------------------------------------------------------------------ */
/*  Cấu trúc snapshot phiên thi được lưu lại                           */
/* ------------------------------------------------------------------ */

/** Đáp án đã lưu cho một câu hỏi */
typedef struct {
    int     q_id;
    char    selected;   /**< 'A', 'B', 'C', 'D', hoặc '\0' nếu chưa trả lời */
} SavedAnswer;

/**
 * @brief Bản ghi lưu trạng thái phiên thi của một Client bị mất kết nối.
 */
typedef struct {
    int         active;                         /**< 1 = slot đang dùng         */
    char        session_token[TOKEN_LEN];        /**< Token định danh phiên      */
    char        room_id[ROOM_ID_MAX];            /**< Phòng thi đang tham gia    */
    int         user_id;
    char        display_name[DISPLAY_NAME_MAX];
    UserRole    role;

    time_t      disconnected_at;                /**< Thời điểm mất kết nối      */
    int         remaining_sec;                  /**< Giây còn lại trong bài thi */

    SavedAnswer answers[MAX_SAVED_ANSWERS];     /**< Đáp án đã gửi trước đó     */
    int         answer_count;
} ReconnectEntry;

/* ------------------------------------------------------------------ */
/*  API                                                                 */
/* ------------------------------------------------------------------ */

/**
 * @brief Khởi tạo bảng reconnect (gọi một lần khi server khởi động).
 */
void reconnect_init(void);

/**
 * @brief Lưu snapshot phiên thi của một Client vừa bị mất kết nối.
 *
 * Được gọi ngay trước khi client_free() trong client_thread().
 *
 * @param ctx       Con trỏ tới ClientCtx vừa ngắt kết nối.
 * @param rem_sec   Số giây còn lại trong bài thi tại thời điểm ngắt.
 */
void reconnect_save(ClientCtx *ctx, int rem_sec);

/**
 * @brief Xử lý yêu cầu RECONNECT_REQ từ Client kết nối lại.
 *
 * Tra cứu bảng theo session_token. Nếu tìm thấy và còn trong TTL:
 *   - Phục hồi thông tin vào ctx mới.
 *   - Gửi RECONNECT_ACK với đề thi và đáp án đã lưu.
 * Nếu không tìm thấy hoặc đã hết TTL: gửi lỗi ERR_INVALID_SESSION.
 *
 * @param ctx       ClientCtx của kết nối MỚI (đã được alloc).
 * @param token     session_token gửi từ Client.
 * @param room_id   room_id gửi từ Client.
 */
void reconnect_handle(ClientCtx *ctx, const char *token, const char *room_id);

/**
 * @brief Xoá một bản ghi reconnect theo token (dùng khi đăng xuất bình thường).
 *
 * @param token session_token cần xoá.
 */
void reconnect_invalidate(const char *token);

/**
 * @brief Cập nhật đáp án trong bản ghi reconnect (gọi mỗi khi nhận EXAM_SUBMIT_ANS).
 *
 * @param token    session_token của client.
 * @param q_id     ID câu hỏi.
 * @param selected Phương án chọn ('A'–'D').
 */
void reconnect_update_answer(const char *token, int q_id, char selected);

#endif /* KUIZU_RECONNECT_H */
