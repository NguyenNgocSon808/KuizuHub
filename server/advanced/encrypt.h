/**
 * @file encrypt.h
 * @brief Module mã hoá / giải mã gói tin KuizuHub bằng XOR cipher.
 *
 * Thuật toán: XOR từng byte Payload với key stream sinh từ
 *   SHA-256(session_token + salt).
 * Đây là mã hoá nhẹ, đủ để minh hoạ tính năng trong bài tập.
 * (Trong sản phẩm thực tế nên dùng AES-128 hoặc ChaCha20.)
 *
 * Tích hợp với giao thức:
 *   - Khi gửi gói có FLAG_ENCRYPTED: gọi kz_encrypt_payload() trước kz_send().
 *   - Khi nhận gói có FLAG_ENCRYPTED: gọi kz_decrypt_payload() sau kz_decode().
 *   - Đối xứng: encrypt == decrypt (XOR là phép tự nghịch đảo).
 */

#ifndef KUIZU_ENCRYPT_H
#define KUIZU_ENCRYPT_H

#include <stdint.h>
#include <stddef.h>

/* ------------------------------------------------------------------ */
/*  Hằng số                                                            */
/* ------------------------------------------------------------------ */

/** Salt cố định (trong thực tế nên random mỗi session) */
#define ENC_SALT "KuizuHub-2026"

/* ------------------------------------------------------------------ */
/*  API                                                                 */
/* ------------------------------------------------------------------ */

/**
 * @brief Khởi tạo key stream từ session_token.
 *
 * Tính SHA-256(token + ENC_SALT) và lưu vào bộ đệm nội bộ.
 * Phải gọi một lần sau khi Client đăng nhập thành công.
 *
 * @param session_token Token UUID v4 của phiên làm việc.
 */
void kz_encrypt_init(const char *session_token);

/**
 * @brief Mã hoá mảng byte theo XOR với key stream.
 *
 * Có thể gọi để mã hoá Payload trước khi đóng gói.
 * Hàm thay đổi dữ liệu tại chỗ (in-place).
 *
 * @param data   Con trỏ dữ liệu cần mã hoá.
 * @param length Số byte cần mã hoá.
 */
void kz_encrypt_payload(uint8_t *data, size_t length);

/**
 * @brief Giải mã mảng byte (giống hệt kz_encrypt_payload vì XOR đối xứng).
 *
 * @param data   Con trỏ dữ liệu cần giải mã.
 * @param length Số byte cần giải mã.
 */
void kz_decrypt_payload(uint8_t *data, size_t length);

#endif /* KUIZU_ENCRYPT_H */
