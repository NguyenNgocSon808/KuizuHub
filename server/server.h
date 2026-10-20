/**
 * @file server.h
 * @brief Cấu trúc quản lý Client và giao diện Server đa luồng KuizuHub.
 *
 * Server dùng mô hình **Thread-per-client**: mỗi Client được nhận
 * bởi accept(), sau đó một pthread mới được tạo để xử lý độc lập.
 * Dữ liệu chia sẻ (danh sách client, danh sách phòng) được bảo vệ
 * bằng mutex.
 */

#ifndef KUIZU_SERVER_H
#define KUIZU_SERVER_H

#include <stdint.h>
#include <pthread.h>
#include <time.h>

#ifdef _WIN32
    #include <winsock2.h>
#else
    #include <netinet/in.h>
#endif

#include "protocol.h"

/* ------------------------------------------------------------------ */
/*  Hằng số Server                                                     */
/* ------------------------------------------------------------------ */

#define MAX_CLIENTS     64      /**< Số client tối đa đồng thời        */
#define MAX_ROOMS       16      /**< Số phòng thi tối đa               */
#define MAX_ROOM_PLAYERS 20     /**< Số người chơi tối đa mỗi phòng   */
#define TOKEN_LEN       37      /**< UUID v4 + null terminator         */
#define USERNAME_MAX    64
#define DISPLAY_NAME_MAX 128
#define ROOM_ID_MAX     16
#define JOIN_CODE_MAX   8

/* ------------------------------------------------------------------ */
/*  Trạng thái Client                                                   */
/* ------------------------------------------------------------------ */

typedef enum {
    CLIENT_STATE_CONNECTED = 0, /**< Đã kết nối, chưa đăng nhập       */
    CLIENT_STATE_AUTH,          /**< Đã xác thực, ở sảnh              */
    CLIENT_STATE_IN_ROOM,       /**< Đang ở phòng chờ                  */
    CLIENT_STATE_EXAM,          /**< Đang làm bài thi                  */
    CLIENT_STATE_DEAD           /**< Đã ngắt kết nối (thread đang dọn) */
} ClientState;

/* ------------------------------------------------------------------ */
/*  Phân quyền                                                          */
/* ------------------------------------------------------------------ */

typedef enum {
    ROLE_USER  = 0,
    ROLE_HOST  = 1,
    ROLE_ADMIN = 2
} UserRole;

/* ------------------------------------------------------------------ */
/*  Cấu trúc đại diện một Client đang kết nối                          */
/* ------------------------------------------------------------------ */

typedef struct {
    int             sockfd;                     /**< Socket của client          */
    struct sockaddr_in addr;                    /**< Địa chỉ IP:Port            */
    pthread_t       thread;                     /**< Thread xử lý client này    */

    ClientState     state;                      /**< Trạng thái hiện tại        */
    int             user_id;                    /**< -1 nếu chưa đăng nhập      */
    char            username[USERNAME_MAX];
    char            display_name[DISPLAY_NAME_MAX];
    char            session_token[TOKEN_LEN];   /**< Token sau đăng nhập        */
    UserRole        role;

    char            room_id[ROOM_ID_MAX];       /**< Phòng đang tham gia        */
    time_t          last_activity;              /**< Timestamp hoạt động cuối   */

    uint16_t        seq_send;                   /**< Số thứ tự gói gửi đi       */

    int             slot;                       /**< Chỉ số trong mảng g_clients */
} ClientCtx;

/* ------------------------------------------------------------------ */
/*  Cấu trúc phòng thi                                                  */
/* ------------------------------------------------------------------ */

typedef enum {
    ROOM_WAITING  = 0,
    ROOM_ONGOING  = 1,
    ROOM_FINISHED = 2
} RoomStatus;

typedef struct {
    char        room_id[ROOM_ID_MAX];
    char        join_code[JOIN_CODE_MAX];
    char        room_name[128];
    int         host_slot;              /**< Slot của host trong g_clients      */
    int         question_count;
    int         duration_sec;
    char        difficulty[16];         /**< "easy"/"medium"/"hard"/"mixed"    */
    char        topic[64];

    RoomStatus  status;
    time_t      start_time;             /**< Thời điểm bắt đầu thi             */

    int         player_slots[MAX_ROOM_PLAYERS]; /**< Slot trong g_clients      */
    int         player_count;

    pthread_t   timer_thread;           /**< Thread đếm giờ và thu bài         */
    int         active;                 /**< 1 = đang dùng                     */
} RoomCtx;

/* ------------------------------------------------------------------ */
/*  Biến toàn cục (định nghĩa trong server.c)                          */
/* ------------------------------------------------------------------ */

extern ClientCtx    g_clients[MAX_CLIENTS];
extern pthread_mutex_t g_clients_mutex;

extern RoomCtx      g_rooms[MAX_ROOMS];
extern pthread_mutex_t g_rooms_mutex;

/* ------------------------------------------------------------------ */
/*  API Server                                                          */
/* ------------------------------------------------------------------ */

/**
 * @brief Khởi tạo Server: socket, bind, listen.
 * @param port Số cổng lắng nghe.
 * @return listen_fd, hoặc -1 nếu lỗi.
 */
int  server_init(int port);

/**
 * @brief Vòng lặp chính: accept() và tạo thread cho mỗi client.
 * @param listen_fd File descriptor đang lắng nghe.
 */
void server_run(int listen_fd);

/**
 * @brief Hàm chạy trong thread riêng, xử lý toàn bộ vòng đời một Client.
 * @param arg Con trỏ tới ClientCtx (do server_run truyền vào).
 */
void *client_thread(void *arg);

/**
 * @brief Tìm một slot trống trong g_clients và khởi tạo ClientCtx.
 * @return Slot index, hoặc -1 nếu đầy.
 */
int  client_alloc(int sockfd, struct sockaddr_in *addr);

/**
 * @brief Giải phóng slot client, đóng socket, xoá token.
 */
void client_free(int slot);

/**
 * @brief Tìm client theo session_token (dùng trong xác thực từng request).
 * @return Slot index, hoặc -1 nếu không tìm thấy / đã hết hạn.
 */
int  client_find_by_token(const char *token);

/**
 * @brief Broadcast một gói JSON tới tất cả client trong một phòng.
 * @param room_id  ID phòng.
 * @param opc      Opcode gói tin.
 * @param json_str Chuỗi JSON.
 */
void room_broadcast(const char *room_id, uint8_t opc, const char *json_str);

#endif /* KUIZU_SERVER_H */
