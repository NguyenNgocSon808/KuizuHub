/**
 * @file server.c
 * @brief Server đa luồng KuizuHub — vòng lặp chính + quản lý Client.
 *
 * Kiến trúc: Thread-per-client (pthread).
 *   main()  →  server_init()  →  server_run()
 *                                   └── accept()
 *                                         └── pthread_create() → client_thread()
 *
 * Dữ liệu chia sẻ được bảo vệ bởi:
 *   - g_clients_mutex  : bảo vệ mảng g_clients[]
 *   - g_rooms_mutex    : bảo vệ mảng g_rooms[]
 */

#include "server.h"
#include "network/protocol.h"
#include "advanced/reconnect.h"
#include "advanced/encrypt.h"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>
#include <signal.h>
#include <errno.h>

#ifdef _WIN32
    #include <winsock2.h>
    #include <ws2tcpip.h>
    /* pragma comment chỉ hỗ trợ MSVC, dùng -lws2_32 trong Makefile khi dùng GCC */
    #define CLOSE_SOCK(s)  closesocket(s)
    #define SOCK_T         SOCKET
#else
    #include <sys/socket.h>
    #include <netinet/in.h>
    #include <arpa/inet.h>
    #include <unistd.h>
    #define CLOSE_SOCK(s)  close(s)
    #define SOCK_T         int
#endif

/* ------------------------------------------------------------------ */
/*  Dữ liệu chia sẻ toàn cục                                           */
/* ------------------------------------------------------------------ */

ClientCtx      g_clients[MAX_CLIENTS];
pthread_mutex_t g_clients_mutex = PTHREAD_MUTEX_INITIALIZER;

RoomCtx        g_rooms[MAX_ROOMS];
pthread_mutex_t g_rooms_mutex   = PTHREAD_MUTEX_INITIALIZER;

static volatile int g_running = 1;
static int          g_listen_fd = -1;

/* ------------------------------------------------------------------ */
/*  Xử lý tín hiệu tắt máy (Ctrl+C)                                   */
/* ------------------------------------------------------------------ */

static void handle_sigint(int sig) {
    (void)sig;
    printf("\n[Server] Shutting down gracefully...\n");
    g_running = 0;
    /* Đóng listen socket để accept() trả về ngay */
    if (g_listen_fd >= 0) CLOSE_SOCK(g_listen_fd);
}

/* ------------------------------------------------------------------ */
/*  Tiện ích tạo UUID v4 đơn giản (không cần thư viện ngoài)           */
/* ------------------------------------------------------------------ */

/**
 * @brief Tạo chuỗi UUID v4 giả (dùng rand() — đủ dùng cho bài tập).
 *
 * @param[out] out Buffer ít nhất TOKEN_LEN byte.
 */
/** @cond INTERNAL — dùng nội bộ, tắt cảnh báo unused */
static void gen_uuid(char *out) {
    static const char hex[] = "0123456789abcdef";
    /* Format: xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx */
    int i, j = 0;
    for (i = 0; i < 32; i++) {
        if (i == 8 || i == 12 || i == 16 || i == 20)
            out[j++] = '-';
        int r = rand() & 0xF;
        if (i == 12) r = 4;                  /* version 4 */
        if (i == 16) r = (r & 0x3) | 0x8;   /* variant   */
        out[j++] = hex[r];
    }
    out[j] = '\0';
}
/** @endcond */

/* ------------------------------------------------------------------ */
/*  client_alloc / client_free / client_find_by_token                  */
/* ------------------------------------------------------------------ */

int client_alloc(int sockfd, struct sockaddr_in *addr) {
    pthread_mutex_lock(&g_clients_mutex);
    for (int i = 0; i < MAX_CLIENTS; i++) {
        if (g_clients[i].state == CLIENT_STATE_DEAD ||
            g_clients[i].sockfd < 0) {
            memset(&g_clients[i], 0, sizeof(ClientCtx));
            g_clients[i].sockfd        = sockfd;
            g_clients[i].addr          = *addr;
            g_clients[i].state         = CLIENT_STATE_CONNECTED;
            g_clients[i].user_id       = -1;
            g_clients[i].role          = ROLE_USER;
            g_clients[i].last_activity = time(NULL);
            g_clients[i].seq_send      = 0;
            g_clients[i].slot          = i;
            pthread_mutex_unlock(&g_clients_mutex);
            return i;
        }
    }
    pthread_mutex_unlock(&g_clients_mutex);
    return -1;  /* Server đầy */
}

void client_free(int slot) {
    pthread_mutex_lock(&g_clients_mutex);
    if (g_clients[slot].sockfd >= 0) {
        CLOSE_SOCK(g_clients[slot].sockfd);
        g_clients[slot].sockfd = -1;
    }
    /* Xoá token khỏi bảng reconnect */
    if (g_clients[slot].session_token[0])
        reconnect_invalidate(g_clients[slot].session_token);

    g_clients[slot].state = CLIENT_STATE_DEAD;
    pthread_mutex_unlock(&g_clients_mutex);
}

int client_find_by_token(const char *token) {
    if (!token || !*token) return -1;
    pthread_mutex_lock(&g_clients_mutex);
    for (int i = 0; i < MAX_CLIENTS; i++) {
        if (g_clients[i].state != CLIENT_STATE_DEAD &&
            g_clients[i].sockfd >= 0 &&
            strcmp(g_clients[i].session_token, token) == 0) {
            pthread_mutex_unlock(&g_clients_mutex);
            return i;
        }
    }
    pthread_mutex_unlock(&g_clients_mutex);
    return -1;
}

/* ------------------------------------------------------------------ */
/*  room_broadcast                                                      */
/* ------------------------------------------------------------------ */

void room_broadcast(const char *room_id, uint8_t opc, const char *json_str) {
    pthread_mutex_lock(&g_rooms_mutex);
    RoomCtx *room = NULL;
    for (int i = 0; i < MAX_ROOMS; i++) {
        if (g_rooms[i].active &&
            strcmp(g_rooms[i].room_id, room_id) == 0) {
            room = &g_rooms[i];
            break;
        }
    }
    if (!room) {
        pthread_mutex_unlock(&g_rooms_mutex);
        return;
    }
    /* Lấy danh sách socket cần gửi */
    int fds[MAX_ROOM_PLAYERS];
    int cnt = 0;
    for (int i = 0; i < room->player_count; i++) {
        int slot = room->player_slots[i];
        if (slot >= 0 && g_clients[slot].sockfd >= 0)
            fds[cnt++] = g_clients[slot].sockfd;
    }
    pthread_mutex_unlock(&g_rooms_mutex);

    /* Gửi ngoài lock để tránh deadlock với client_thread */
    for (int i = 0; i < cnt; i++) {
        kz_send(fds[i], opc, 0, json_str);
    }
}

/* ------------------------------------------------------------------ */
/*  client_thread — vòng lặp xử lý một Client                         */
/* ------------------------------------------------------------------ */

/**
 * @brief Trích xuất giá trị string từ JSON đơn giản (không dùng thư viện).
 *
 * Tìm "key":"value" và sao chép value vào out (tối đa out_size-1 ký tự).
 * Chỉ hỗ trợ giá trị string không chứa dấu backslash.
 */
static int json_get_str(const char *json, const char *key,
                        char *out, size_t out_size) {
    char needle[128];
    snprintf(needle, sizeof(needle), "\"%s\":\"", key);
    const char *p = strstr(json, needle);
    if (!p) return 0;
    p += strlen(needle);
    const char *end = strchr(p, '"');
    if (!end) return 0;
    size_t len = (size_t)(end - p);
    if (len >= out_size) len = out_size - 1;
    memcpy(out, p, len);
    out[len] = '\0';
    return 1;
}

/**
 * @brief Dispatch một gói tin đã decode tới handler nghiệp vụ tương ứng.
 *
 * Hàm này được gọi tuần tự trong client_thread.
 * Các handler nghiệp vụ phức tạp (AUTH, ROOM, EXAM) sẽ được triển khai
 * ở Giai đoạn 2 và 3.
 */
static void dispatch(ClientCtx *ctx, KzFrame *frame) {
    const char *payload = (const char *)frame->payload;
    uint8_t opc  = frame->hdr.opc;
    uint16_t seq = frame->hdr.seq;

    /* --- Giải mã nếu payload được mã hoá --- */
    if (frame->hdr.flags & FLAG_ENCRYPTED) {
        kz_decrypt_payload(frame->payload, frame->hdr.pay_len);
    }

    ctx->last_activity = time(NULL);

    switch (opc) {

    /* ---- Hệ thống ---- */
    case OPC_PING:
        kz_send(ctx->sockfd, OPC_PONG, seq, "{\"status\":\"ok\"}");
        break;

    case OPC_DISCONNECT:
        printf("[Server] Client slot=%d requested disconnect.\n", ctx->slot);
        ctx->state = CLIENT_STATE_DEAD;    /* Kết thúc vòng lặp */
        break;

    case OPC_RECONNECT_REQ: {
        char token[TOKEN_LEN], room_id[ROOM_ID_MAX];
        json_get_str(payload, "session_token", token, sizeof(token));
        json_get_str(payload, "room_id", room_id, sizeof(room_id));
        reconnect_handle(ctx, token, room_id);
        break;
    }

    /* ---- Xác thực (stub — TV2 hoàn thiện ở Giai đoạn 2) ---- */
    case OPC_REGISTER_REQ:
    case OPC_LOGIN_REQ:
    case OPC_LOGOUT_REQ:
        /* TODO: Giai đoạn 2 — TV2 triển khai auth_handler() */
        kz_send_error(ctx->sockfd, seq, ERR_INTERNAL, "Auth handler not yet implemented");
        break;

    /* ---- Phòng thi (stub — TV3 phối hợp ở Giai đoạn 2) ---- */
    case OPC_ROOM_LIST_REQ:
    case OPC_ROOM_CREATE_REQ:
    case OPC_ROOM_JOIN_REQ:
    case OPC_ROOM_LEAVE_REQ:
        /* TODO: Giai đoạn 2 — TV3 triển khai room_handler() */
        kz_send_error(ctx->sockfd, seq, ERR_INTERNAL, "Room handler not yet implemented");
        break;

    /* ---- Luồng thi (stub — Giai đoạn 3) ---- */
    case OPC_HOST_START_REQ:
    case OPC_EXAM_SUBMIT_ANS:
    case OPC_PRACTICE_REQ:
        /* TODO: Giai đoạn 3 — exam_engine */
        kz_send_error(ctx->sockfd, seq, ERR_INTERNAL, "Exam handler not yet implemented");
        break;

    default:
        fprintf(stderr, "[Server] Unknown OPC 0x%02X from slot=%d\n",
                opc, ctx->slot);
        kz_send_error(ctx->sockfd, seq, ERR_INTERNAL, "Unknown opcode");
        break;
    }
}

void *client_thread(void *arg) {
    ClientCtx *ctx = (ClientCtx *)arg;

    char ip_str[INET_ADDRSTRLEN];
    inet_ntop(AF_INET, &ctx->addr.sin_addr, ip_str, sizeof(ip_str));
    printf("[Server] Client connected: %s:%d (slot=%d)\n",
           ip_str, ntohs(ctx->addr.sin_port), ctx->slot);
    fflush(stdout);

    KzFrame frame;

    while (g_running && ctx->state != CLIENT_STATE_DEAD) {

        /* Kiểm tra timeout không hoạt động */
        if (difftime(time(NULL), ctx->last_activity) > SOCKET_TIMEOUT_SEC) {
            printf("[Server] Client slot=%d timed out.\n", ctx->slot);
            break;
        }

        int r = kz_decode(ctx->sockfd, &frame);
        if (r == 0) {
            printf("[Server] Client slot=%d disconnected.\n", ctx->slot);
            break;
        }
        if (r < 0) {
            fprintf(stderr, "[Server] Protocol error from slot=%d.\n", ctx->slot);
            break;
        }

        dispatch(ctx, &frame);
    }

    printf("[Server] Cleaning up slot=%d (%s:%d)\n",
           ctx->slot, ip_str, ntohs(ctx->addr.sin_port));
    fflush(stdout);
    client_free(ctx->slot);
    return NULL;
}

/* ------------------------------------------------------------------ */
/*  server_init / server_run                                            */
/* ------------------------------------------------------------------ */

int server_init(int port) {
#ifdef _WIN32
    WSADATA wsa;
    if (WSAStartup(MAKEWORD(2, 2), &wsa) != 0) {
        fprintf(stderr, "[Server] WSAStartup failed.\n");
        return -1;
    }
#endif

    /* Khởi tạo mảng clients */
    memset(g_clients, 0, sizeof(g_clients));
    for (int i = 0; i < MAX_CLIENTS; i++) {
        g_clients[i].sockfd = -1;
        g_clients[i].state  = CLIENT_STATE_DEAD;
        g_clients[i].slot   = i;
    }

    /* Khởi tạo mảng phòng */
    memset(g_rooms, 0, sizeof(g_rooms));

    /* Khởi tạo module reconnect */
    reconnect_init();

    /* Tạo TCP socket */
    int fd = socket(AF_INET, SOCK_STREAM, 0);
    if (fd < 0) { perror("socket"); return -1; }

    /* Cho phép dùng lại cổng sau khi restart */
    int opt = 1;
    setsockopt(fd, SOL_SOCKET, SO_REUSEADDR, (const char *)&opt, sizeof(opt));

    struct sockaddr_in addr;
    memset(&addr, 0, sizeof(addr));
    addr.sin_family      = AF_INET;
    addr.sin_addr.s_addr = htonl(INADDR_ANY);
    addr.sin_port        = htons((uint16_t)port);

    if (bind(fd, (struct sockaddr *)&addr, sizeof(addr)) < 0) {
        perror("bind"); CLOSE_SOCK(fd); return -1;
    }
    if (listen(fd, 32) < 0) {
        perror("listen"); CLOSE_SOCK(fd); return -1;
    }

    printf("[Server] KuizuHub Server listening on port %d (max %d clients)\n",
           port, MAX_CLIENTS);
    fflush(stdout);
    return fd;
}

void server_run(int listen_fd) {
    g_listen_fd = listen_fd;
    signal(SIGINT, handle_sigint);
#ifndef _WIN32
    signal(SIGPIPE, SIG_IGN);   /* Tránh crash khi client đóng giữa chừng */
#endif

    srand((unsigned)time(NULL));

    while (g_running) {
        struct sockaddr_in cli_addr;
#ifdef _WIN32
        int cli_len = sizeof(cli_addr);
#else
        socklen_t cli_len = sizeof(cli_addr);
#endif
        int cli_fd = accept(listen_fd,
                            (struct sockaddr *)&cli_addr, &cli_len);
        if (cli_fd < 0) {
            if (!g_running) break;
#ifdef _WIN32
            if (WSAGetLastError() == WSAEINTR) continue;
#else
            if (errno == EINTR) continue;
#endif
            perror("accept");
            continue;
        }

        /* Phân slot */
        int slot = client_alloc(cli_fd, &cli_addr);
        if (slot < 0) {
            fprintf(stderr, "[Server] Max clients reached, rejecting.\n");
            kz_send_error(cli_fd, 0, ERR_INTERNAL, "Server full");
            CLOSE_SOCK(cli_fd);
            continue;
        }

        /* Tạo thread xử lý client */
        pthread_attr_t attr;
        pthread_attr_init(&attr);
        pthread_attr_setdetachstate(&attr, PTHREAD_CREATE_DETACHED);

        if (pthread_create(&g_clients[slot].thread, &attr,
                           client_thread, &g_clients[slot]) != 0) {
            perror("pthread_create");
            client_free(slot);
        }
        pthread_attr_destroy(&attr);
    }

    printf("[Server] Server stopped.\n");
}

/* ------------------------------------------------------------------ */
/*  main                                                                */
/* ------------------------------------------------------------------ */

int main(int argc, char *argv[]) {
    if (argc != 2) {
        fprintf(stderr, "Usage: %s <port>\n", argv[0]);
        return 1;
    }

    int port = atoi(argv[1]);
    if (port <= 0 || port > 65535) {
        fprintf(stderr, "Error: Invalid port number.\n");
        return 1;
    }

    int listen_fd = server_init(port);
    if (listen_fd < 0) return 1;

    server_run(listen_fd);

#ifdef _WIN32
    WSACleanup();
#endif
    return 0;
}
