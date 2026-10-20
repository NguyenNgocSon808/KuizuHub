/**
 * @file protocol.c
 * @brief Triển khai encode / decode byte stream theo giao thức KuizuHub.
 *
 * Định dạng wire (Big-Endian):
 *   [VER 1B][OPC 1B][FLAGS 1B][RES 1B][SEQ 2B][PAY_LEN 2B][PAYLOAD ...]
 */

#include "protocol.h"

#include <stdio.h>
#include <string.h>
#include <errno.h>

#ifdef _WIN32
    #include <winsock2.h>
    /* MinGW (UCRT) đã định nghĩa ssize_t trong corecrt.h, không cần khai báo lại */
    #ifndef _SSIZE_T_DEFINED
        typedef int ssize_t;
        #define _SSIZE_T_DEFINED
    #endif
    #define send_fn(s,b,l,f) send((s),(const char*)(b),(int)(l),(f))
    #define recv_fn(s,b,l,f) recv((s),(char*)(b),(int)(l),(f))
#else
    #include <sys/socket.h>
    #include <unistd.h>
    #define send_fn(s,b,l,f) send((s),(b),(l),(f))
    #define recv_fn(s,b,l,f) recv((s),(b),(l),(f))
#endif

/* ------------------------------------------------------------------ */
/*  Tiện ích nội bộ: recv/send đủ số byte                              */
/* ------------------------------------------------------------------ */

/**
 * @brief Đọc đúng `n` byte từ socket, lặp lại nếu bị ngắt.
 *
 * @return  1 thành công, 0 nếu kết nối đóng, -1 nếu lỗi I/O.
 */
static int recv_all(int sockfd, uint8_t *buf, size_t n) {
    size_t received = 0;
    while (received < n) {
        ssize_t r = recv_fn(sockfd, buf + received, n - received, 0);
        if (r == 0) return 0;   /* kết nối đóng phía client */
        if (r < 0) {
#ifdef _WIN32
            if (WSAGetLastError() == WSAEINTR) continue;
#else
            if (errno == EINTR) continue;
#endif
            return -1;
        }
        received += (size_t)r;
    }
    return 1;
}

/**
 * @brief Gửi đúng `n` byte qua socket, lặp lại nếu bị ngắt.
 *
 * @return  1 thành công, -1 nếu lỗi I/O.
 */
static int send_all(int sockfd, const uint8_t *buf, size_t n) {
    size_t sent = 0;
    while (sent < n) {
        ssize_t s = send_fn(sockfd, buf + sent, n - sent, 0);
        if (s < 0) {
#ifdef _WIN32
            if (WSAGetLastError() == WSAEINTR) continue;
#else
            if (errno == EINTR) continue;
#endif
            return -1;
        }
        sent += (size_t)s;
    }
    return 1;
}

/* ------------------------------------------------------------------ */
/*  encode                                                              */
/* ------------------------------------------------------------------ */

int kz_encode(uint8_t *out_buf,
              uint8_t opc, uint8_t flags, uint16_t seq,
              const uint8_t *payload, uint16_t pay_len) {

    /* --- Ghi Header (Big-Endian thủ công để tránh phụ thuộc hton) --- */
    out_buf[0] = PROTO_VERSION;
    out_buf[1] = opc;
    out_buf[2] = flags;
    out_buf[3] = 0x00;                      /* RES */
    out_buf[4] = (uint8_t)(seq >> 8);       /* SEQ high byte  */
    out_buf[5] = (uint8_t)(seq & 0xFF);     /* SEQ low byte   */
    out_buf[6] = (uint8_t)(pay_len >> 8);   /* LEN high byte  */
    out_buf[7] = (uint8_t)(pay_len & 0xFF); /* LEN low byte   */

    /* --- Sao chép Payload (nếu có) --- */
    if (payload && pay_len > 0) {
        memcpy(out_buf + HEADER_SIZE, payload, pay_len);
    }

    return HEADER_SIZE + pay_len;
}

/* ------------------------------------------------------------------ */
/*  decode                                                              */
/* ------------------------------------------------------------------ */

int kz_decode(int sockfd, KzFrame *frame) {
    uint8_t raw_hdr[HEADER_SIZE];

    /* Bước 1: Đọc đúng 8 byte Header */
    int r = recv_all(sockfd, raw_hdr, HEADER_SIZE);
    if (r != 1) return r;   /* 0 = đóng kết nối, -1 = lỗi */

    /* Bước 2: Kiểm tra phiên bản giao thức */
    if (raw_hdr[0] != PROTO_VERSION) {
        fprintf(stderr, "[kz_decode] Unsupported protocol version: 0x%02X\n",
                raw_hdr[0]);
        return -1;
    }

    /* Bước 3: Parse Header vào struct (chuyển về host byte-order) */
    frame->hdr.ver     = raw_hdr[0];
    frame->hdr.opc     = raw_hdr[1];
    frame->hdr.flags   = raw_hdr[2];
    frame->hdr.res     = raw_hdr[3];
    frame->hdr.seq     = (uint16_t)((raw_hdr[4] << 8) | raw_hdr[5]);
    frame->hdr.pay_len = (uint16_t)((raw_hdr[6] << 8) | raw_hdr[7]);

    /* Bước 4: Kiểm tra độ dài Payload hợp lệ */
    if ((uint32_t)frame->hdr.pay_len > (uint32_t)MAX_PAYLOAD_SIZE) {
        fprintf(stderr, "[kz_decode] Payload too large: %u bytes\n",
                frame->hdr.pay_len);
        return -1;
    }

    /* Bước 5: Đọc Payload (nếu có) */
    if (frame->hdr.pay_len > 0) {
        r = recv_all(sockfd, frame->payload, frame->hdr.pay_len);
        if (r != 1) return r;
    }

    /* NULL-terminate để dùng payload như chuỗi C */
    frame->payload[frame->hdr.pay_len] = '\0';

    return 1;
}

/* ------------------------------------------------------------------ */
/*  kz_send — gửi một gói tin JSON                                     */
/* ------------------------------------------------------------------ */

int kz_send(int sockfd, uint8_t opc, uint16_t seq, const char *json_str) {
    uint16_t pay_len = 0;
    const uint8_t *payload = NULL;

    if (json_str) {
        size_t len = strlen(json_str);
        if (len > MAX_PAYLOAD_SIZE) {
            fprintf(stderr, "[kz_send] JSON too large (%zu bytes)\n", len);
            return -1;
        }
        pay_len = (uint16_t)len;
        payload = (const uint8_t *)json_str;
    }

    /* Cấp phát buffer = Header + Payload */
    uint8_t buf[HEADER_SIZE + MAX_PAYLOAD_SIZE];
    int total = kz_encode(buf, opc, FLAG_NONE, seq, payload, pay_len);

    if (send_all(sockfd, buf, (size_t)total) != 1) return -1;
    return total;
}

/* ------------------------------------------------------------------ */
/*  kz_send_error — gửi gói lỗi chuẩn                                 */
/* ------------------------------------------------------------------ */

void kz_send_error(int sockfd, uint16_t seq, int error_code, const char *msg) {
    char json[512];
    snprintf(json, sizeof(json),
             "{\"status\":\"error\",\"error_code\":%d,\"msg\":\"%s\"}",
             error_code, msg ? msg : "");
    kz_send(sockfd, OPC_ERROR, seq, json);
}
