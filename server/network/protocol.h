/**
 * @file protocol.h
 * @brief Định nghĩa cấu trúc giao thức KuizuHub — Binary Frame + Opcode.
 *
 * Mọi gói tin giữa Client và Server đều tuân theo định dạng:
 *   [VER|OPC|FLAGS|RES|SEQ_NUM(2)|PAY_LEN(2)] + PAYLOAD(JSON UTF-8)
 *
 * Tham chiếu đầy đủ: docs/protocol.md
 */

#ifndef KUIZU_PROTOCOL_H
#define KUIZU_PROTOCOL_H

#include <stdint.h>
#include <stddef.h>

/* ------------------------------------------------------------------ */
/*  Hằng số giao thức                                                  */
/* ------------------------------------------------------------------ */

#define PROTO_VERSION       0x01
#define HEADER_SIZE         8           /**< Kích thước Header cố định (byte) */
#define MAX_PAYLOAD_SIZE    65535       /**< Payload tối đa ~64 KB            */
#define SOCKET_TIMEOUT_SEC  30          /**< Timeout kết nối không hoạt động  */

/* ------------------------------------------------------------------ */
/*  Opcodes — nhóm theo chức năng                                      */
/* ------------------------------------------------------------------ */

/* Hệ thống (0x00–0x0F) */
#define OPC_PING             0x00
#define OPC_PONG             0x01
#define OPC_DISCONNECT       0x02
#define OPC_RECONNECT_REQ    0x03
#define OPC_RECONNECT_ACK    0x04

/* Xác thực (0x10–0x1F) */
#define OPC_REGISTER_REQ     0x10
#define OPC_REGISTER_RES     0x11
#define OPC_LOGIN_REQ        0x12
#define OPC_LOGIN_RES        0x13
#define OPC_LOGOUT_REQ       0x14
#define OPC_LOGOUT_RES       0x15

/* Sảnh & Phòng thi (0x20–0x2F) */
#define OPC_ROOM_LIST_REQ    0x20
#define OPC_ROOM_LIST_RES    0x21
#define OPC_ROOM_CREATE_REQ  0x22
#define OPC_ROOM_CREATE_RES  0x23
#define OPC_ROOM_JOIN_REQ    0x24
#define OPC_ROOM_JOIN_RES    0x25
#define OPC_ROOM_LEAVE_REQ   0x26
#define OPC_ROOM_PLAYER_UPD  0x27
#define OPC_ROOM_STATE_UPD   0x28

/* Luồng thi (0x30–0x3F) */
#define OPC_EXAM_START       0x30
#define OPC_EXAM_SUBMIT_ANS  0x31
#define OPC_EXAM_ANS_ACK     0x32
#define OPC_EXAM_TIME_SYNC   0x33
#define OPC_EXAM_FORCE_SUB   0x34
#define OPC_EXAM_RESULT      0x35
#define OPC_EXAM_LEADERBOARD 0x36
#define OPC_HOST_START_REQ   0x37
#define OPC_PRACTICE_REQ     0x38
#define OPC_PRACTICE_RESULT  0x39

/* Hồ sơ & Thống kê (0x40–0x4F) */
#define OPC_PROFILE_REQ      0x40
#define OPC_PROFILE_RES      0x41
#define OPC_HISTORY_REQ      0x42
#define OPC_HISTORY_RES      0x43

/* Lỗi & Thông báo (0xF0–0xFF) */
#define OPC_ERROR            0xF0
#define OPC_NOTIFY           0xF1
#define OPC_ANTI_CHEAT       0xF2

/* ------------------------------------------------------------------ */
/*  FLAGS bits                                                         */
/* ------------------------------------------------------------------ */
#define FLAG_NONE            0x00
#define FLAG_ENCRYPTED       0x02   /**< bit1 = payload đã XOR mã hóa */

/* ------------------------------------------------------------------ */
/*  Mã lỗi ứng dụng (đặt vào JSON field "error_code")                 */
/* ------------------------------------------------------------------ */
#define ERR_BAD_CREDENTIALS  1001
#define ERR_USERNAME_TAKEN   1002
#define ERR_INVALID_SESSION  1003
#define ERR_FORBIDDEN        1004
#define ERR_ROOM_NOT_FOUND   2001
#define ERR_ROOM_FULL        2002
#define ERR_ROOM_ONGOING     2003
#define ERR_EXAM_ENDED       3001
#define ERR_QUESTION_INVALID 3002
#define ERR_INTERNAL         9999

/* ------------------------------------------------------------------ */
/*  Cấu trúc Header (8 byte, Big-Endian)                               */
/* ------------------------------------------------------------------ */

/**
 * @brief Header gói tin KuizuHub (8 byte, packed, Big-Endian).
 *
 * Thứ tự trên dây (wire order):
 *   [ver][opc][flags][res][seq_hi][seq_lo][len_hi][len_lo]
 */
#pragma pack(push, 1)
typedef struct {
    uint8_t  ver;       /**< Phiên bản giao thức, luôn = PROTO_VERSION */
    uint8_t  opc;       /**< Opcode                                     */
    uint8_t  flags;     /**< Cờ điều khiển (FLAG_*)                     */
    uint8_t  res;       /**< Dự phòng, luôn = 0x00                      */
    uint16_t seq;       /**< Số thứ tự (Big-Endian)                     */
    uint16_t pay_len;   /**< Độ dài Payload (Big-Endian)                */
} KzHeader;
#pragma pack(pop)

/* ------------------------------------------------------------------ */
/*  Gói tin hoàn chỉnh trong bộ nhớ                                    */
/* ------------------------------------------------------------------ */

/**
 * @brief Gói tin KuizuHub sau khi decode từ socket.
 */
typedef struct {
    KzHeader hdr;                   /**< Header đã được chuyển về host byte-order */
    uint8_t  payload[MAX_PAYLOAD_SIZE + 1]; /**< Payload (NULL-terminated để dùng như chuỗi) */
} KzFrame;

/* ------------------------------------------------------------------ */
/*  API encode / decode                                                 */
/* ------------------------------------------------------------------ */

/**
 * @brief Đóng gói Header + Payload thành byte stream để gửi qua socket.
 *
 * @param[out] out_buf  Buffer đầu ra (phải đủ HEADER_SIZE + pay_len bytes).
 * @param[in]  opc      Opcode của gói tin.
 * @param[in]  flags    Cờ điều khiển (FLAG_*).
 * @param[in]  seq      Số thứ tự gói tin.
 * @param[in]  payload  Con trỏ dữ liệu Payload (JSON UTF-8), NULL nếu không có.
 * @param[in]  pay_len  Độ dài Payload (byte).
 * @return Tổng số byte đã ghi vào out_buf (HEADER_SIZE + pay_len).
 */
int kz_encode(uint8_t *out_buf,
              uint8_t opc, uint8_t flags, uint16_t seq,
              const uint8_t *payload, uint16_t pay_len);

/**
 * @brief Đọc chính xác một gói tin đầy đủ từ socket TCP.
 *
 * Hàm block cho đến khi đọc đủ HEADER_SIZE byte Header, sau đó tiếp tục
 * đọc pay_len byte Payload. Trả về lỗi nếu kết nối bị đóng giữa chừng.
 *
 * @param[in]  sockfd  File descriptor của socket.
 * @param[out] frame   Gói tin sau khi decode (Header ở host byte-order).
 * @return  1 thành công, 0 kết nối đóng, -1 lỗi giao thức.
 */
int kz_decode(int sockfd, KzFrame *frame);

/**
 * @brief Gửi một gói tin JSON đơn giản qua socket.
 *
 * Hàm tiện ích: tự encode rồi gọi send() lặp cho đến khi hết dữ liệu.
 *
 * @param[in] sockfd   File descriptor của socket.
 * @param[in] opc      Opcode.
 * @param[in] seq      Số thứ tự.
 * @param[in] json_str Chuỗi JSON (NULL-terminated), NULL nếu không có payload.
 * @return Số byte đã gửi, hoặc -1 nếu lỗi.
 */
int kz_send(int sockfd, uint8_t opc, uint16_t seq, const char *json_str);

/**
 * @brief Gửi gói tin lỗi chuẩn tới client.
 *
 * @param[in] sockfd     File descriptor của socket.
 * @param[in] seq        Số thứ tự request bị lỗi.
 * @param[in] error_code Mã lỗi (ERR_*).
 * @param[in] msg        Thông báo lỗi ngắn.
 */
void kz_send_error(int sockfd, uint16_t seq, int error_code, const char *msg);

#endif /* KUIZU_PROTOCOL_H */
