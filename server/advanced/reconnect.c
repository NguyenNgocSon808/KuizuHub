/**
 * @file reconnect.c
 * @brief Triển khai module khôi phục phiên thi sau khi mất kết nối.
 */

#include "reconnect.h"
#include "../network/protocol.h"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>
#include <pthread.h>

/* ------------------------------------------------------------------ */
/*  Bảng lưu trạng thái (bộ nhớ trong, đủ dùng cho bài tập)           */
/* ------------------------------------------------------------------ */

static ReconnectEntry  g_reconnect_table[RECONNECT_MAX_SESSIONS];
static pthread_mutex_t g_reconnect_mutex = PTHREAD_MUTEX_INITIALIZER;

/* ------------------------------------------------------------------ */
/*  reconnect_init                                                      */
/* ------------------------------------------------------------------ */

void reconnect_init(void) {
    pthread_mutex_lock(&g_reconnect_mutex);
    memset(g_reconnect_table, 0, sizeof(g_reconnect_table));
    pthread_mutex_unlock(&g_reconnect_mutex);
    printf("[Reconnect] Module initialized (%d slots, TTL=%ds)\n",
           RECONNECT_MAX_SESSIONS, RECONNECT_TTL_SEC);
}

/* ------------------------------------------------------------------ */
/*  Tiện ích nội bộ                                                    */
/* ------------------------------------------------------------------ */

/** Tìm slot theo token (phải giữ mutex trước khi gọi) */
static int find_slot_by_token(const char *token) {
    for (int i = 0; i < RECONNECT_MAX_SESSIONS; i++) {
        if (g_reconnect_table[i].active &&
            strcmp(g_reconnect_table[i].session_token, token) == 0) {
            return i;
        }
    }
    return -1;
}

/** Tìm slot trống (phải giữ mutex trước khi gọi) */
static int find_free_slot(void) {
    time_t now = time(NULL);
    for (int i = 0; i < RECONNECT_MAX_SESSIONS; i++) {
        if (!g_reconnect_table[i].active) return i;
        /* Dọn slot đã hết TTL */
        if (difftime(now, g_reconnect_table[i].disconnected_at) > RECONNECT_TTL_SEC) {
            g_reconnect_table[i].active = 0;
            return i;
        }
    }
    return -1;
}

/* ------------------------------------------------------------------ */
/*  reconnect_save                                                      */
/* ------------------------------------------------------------------ */

void reconnect_save(ClientCtx *ctx, int rem_sec) {
    /* Chỉ lưu nếu client đang trong phòng thi */
    if (ctx->state != CLIENT_STATE_EXAM || !ctx->session_token[0]) return;

    pthread_mutex_lock(&g_reconnect_mutex);

    /* Kiểm tra đã có entry chưa (tránh duplicate) */
    int slot = find_slot_by_token(ctx->session_token);
    if (slot < 0) slot = find_free_slot();
    if (slot < 0) {
        fprintf(stderr, "[Reconnect] Table full, cannot save session.\n");
        pthread_mutex_unlock(&g_reconnect_mutex);
        return;
    }

    ReconnectEntry *e = &g_reconnect_table[slot];
    e->active           = 1;
    e->user_id          = ctx->user_id;
    e->role             = ctx->role;
    e->remaining_sec    = rem_sec;
    e->disconnected_at  = time(NULL);
    strncpy(e->session_token, ctx->session_token, TOKEN_LEN - 1);
    strncpy(e->room_id,       ctx->room_id,       ROOM_ID_MAX - 1);
    strncpy(e->display_name,  ctx->display_name,  DISPLAY_NAME_MAX - 1);

    printf("[Reconnect] Saved session for user_id=%d (slot=%d, rem=%ds)\n",
           ctx->user_id, slot, rem_sec);

    pthread_mutex_unlock(&g_reconnect_mutex);
}

/* ------------------------------------------------------------------ */
/*  reconnect_handle                                                    */
/* ------------------------------------------------------------------ */

void reconnect_handle(ClientCtx *ctx, const char *token, const char *room_id) {
    pthread_mutex_lock(&g_reconnect_mutex);

    int slot = find_slot_by_token(token);

    /* Không tìm thấy */
    if (slot < 0) {
        pthread_mutex_unlock(&g_reconnect_mutex);
        kz_send_error(ctx->sockfd, 0, ERR_INVALID_SESSION,
                      "Session not found or already expired");
        return;
    }

    ReconnectEntry *e = &g_reconnect_table[slot];

    /* Kiểm tra TTL */
    double elapsed = difftime(time(NULL), e->disconnected_at);
    if (elapsed > RECONNECT_TTL_SEC) {
        e->active = 0;
        pthread_mutex_unlock(&g_reconnect_mutex);
        kz_send_error(ctx->sockfd, 0, ERR_INVALID_SESSION,
                      "Session expired (reconnect window closed)");
        return;
    }

    /* Kiểm tra room_id khớp */
    if (strcmp(e->room_id, room_id) != 0) {
        pthread_mutex_unlock(&g_reconnect_mutex);
        kz_send_error(ctx->sockfd, 0, ERR_ROOM_NOT_FOUND,
                      "Room ID mismatch");
        return;
    }

    /* Phục hồi thông tin vào ClientCtx mới */
    ctx->user_id = e->user_id;
    ctx->role    = e->role;
    ctx->state   = CLIENT_STATE_EXAM;
    strncpy(ctx->session_token, token,         TOKEN_LEN - 1);
    strncpy(ctx->room_id,       e->room_id,    ROOM_ID_MAX - 1);
    strncpy(ctx->display_name,  e->display_name, DISPLAY_NAME_MAX - 1);

    /* Tính thời gian còn lại sau khi trừ thời gian mất mạng */
    int remaining = e->remaining_sec - (int)elapsed;
    if (remaining < 0) remaining = 0;

    /* Xây dựng JSON đáp án đã lưu */
    char saved_json[4096] = "[";
    for (int i = 0; i < e->answer_count; i++) {
        char tmp[64];
        snprintf(tmp, sizeof(tmp),
                 "%s{\"q_id\":%d,\"selected\":\"%c\"}",
                 i > 0 ? "," : "",
                 e->answers[i].q_id,
                 e->answers[i].selected);
        strncat(saved_json, tmp, sizeof(saved_json) - strlen(saved_json) - 1);
    }
    strncat(saved_json, "]", sizeof(saved_json) - strlen(saved_json) - 1);

    /* Đánh dấu slot đã dùng (client đã reconnect thành công) */
    e->active = 0;
    pthread_mutex_unlock(&g_reconnect_mutex);

    /* Gửi RECONNECT_ACK */
    char ack_json[8192];
    snprintf(ack_json, sizeof(ack_json),
             "{\"status\":\"ok\","
             "\"room_id\":\"%s\","
             "\"remaining_seconds\":%d,"
             "\"saved_answers\":%s}",
             room_id, remaining, saved_json);

    kz_send(ctx->sockfd, OPC_RECONNECT_ACK, 0, ack_json);

    printf("[Reconnect] User_id=%d reconnected to room %s (rem=%ds)\n",
           ctx->user_id, room_id, remaining);
}

/* ------------------------------------------------------------------ */
/*  reconnect_invalidate                                                */
/* ------------------------------------------------------------------ */

void reconnect_invalidate(const char *token) {
    if (!token || !*token) return;
    pthread_mutex_lock(&g_reconnect_mutex);
    int slot = find_slot_by_token(token);
    if (slot >= 0) g_reconnect_table[slot].active = 0;
    pthread_mutex_unlock(&g_reconnect_mutex);
}

/* ------------------------------------------------------------------ */
/*  reconnect_update_answer                                             */
/* ------------------------------------------------------------------ */

void reconnect_update_answer(const char *token, int q_id, char selected) {
    pthread_mutex_lock(&g_reconnect_mutex);
    int slot = find_slot_by_token(token);
    if (slot < 0) {
        pthread_mutex_unlock(&g_reconnect_mutex);
        return;
    }
    ReconnectEntry *e = &g_reconnect_table[slot];

    /* Tìm câu hỏi đã có, nếu có thì cập nhật */
    for (int i = 0; i < e->answer_count; i++) {
        if (e->answers[i].q_id == q_id) {
            e->answers[i].selected = selected;
            pthread_mutex_unlock(&g_reconnect_mutex);
            return;
        }
    }
    /* Thêm mới */
    if (e->answer_count < MAX_SAVED_ANSWERS) {
        e->answers[e->answer_count].q_id     = q_id;
        e->answers[e->answer_count].selected = selected;
        e->answer_count++;
    }
    pthread_mutex_unlock(&g_reconnect_mutex);
}
