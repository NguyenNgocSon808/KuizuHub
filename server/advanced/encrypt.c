/**
 * @file encrypt.c
 * @brief Triển khai mã hoá / giải mã Payload bằng XOR + SHA-256 key stream.
 *
 * Key stream = SHA-256(session_token + ENC_SALT) → 32 byte
 * Với payload dài hơn 32 byte: key stream được lặp vòng (repeating key).
 *
 * Tái sử dụng sha256.c đã có từ Tuần 5 của môn LTM.
 * Copy sha256.h / sha256.c vào thư mục server/ trước khi build.
 */

#include "encrypt.h"
#include "../../tuan5/sha256.h"   /* SHA-256 từ bài tập tuần 5 — sẽ copy khi build */

#include <stdio.h>
#include <string.h>
#include <stdint.h>

/* ------------------------------------------------------------------ */
/*  Trạng thái nội bộ: key stream 32 byte                              */
/* ------------------------------------------------------------------ */

static uint8_t g_key[SHA256_BLOCK_SIZE];   /**< 32 byte key stream   */
static int     g_key_ready = 0;            /**< 0 = chưa khởi tạo   */

/* ------------------------------------------------------------------ */
/*  kz_encrypt_init                                                    */
/* ------------------------------------------------------------------ */

void kz_encrypt_init(const char *session_token) {
    if (!session_token || !*session_token) return;

    /* Nối token + salt */
    char combined[256];
    snprintf(combined, sizeof(combined), "%s%s", session_token, ENC_SALT);

    /* Tính SHA-256 → 32 byte key */
    SHA256_CTX ctx;
    sha256_init(&ctx);
    sha256_update(&ctx, (const uint8_t *)combined, strlen(combined));
    sha256_final(&ctx, g_key);

    g_key_ready = 1;

    /* Log key (debug only — xoá trước khi nộp bài) */
    printf("[Encrypt] Key initialized from token (first 4 bytes: %02X %02X %02X %02X)\n",
           g_key[0], g_key[1], g_key[2], g_key[3]);
}

/* ------------------------------------------------------------------ */
/*  kz_encrypt_payload / kz_decrypt_payload                            */
/* ------------------------------------------------------------------ */

void kz_encrypt_payload(uint8_t *data, size_t length) {
    if (!g_key_ready) {
        fprintf(stderr, "[Encrypt] WARNING: key not initialized, skipping encryption.\n");
        return;
    }
    for (size_t i = 0; i < length; i++) {
        data[i] ^= g_key[i % SHA256_BLOCK_SIZE];
    }
}

/* XOR là phép tự đảo: decrypt == encrypt */
void kz_decrypt_payload(uint8_t *data, size_t length) {
    kz_encrypt_payload(data, length);
}
