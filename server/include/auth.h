#ifndef KUIZUHUB_AUTH_H
#define KUIZUHUB_AUTH_H

#include "protocol.h"
#include <stdbool.h>

typedef struct {
    int id;
    char username[64];
    char role[16];
    char created_at[32];
    char token_hash[65];
} kz_auth_user;

/**
 * Hash a plaintext password using PBKDF2-HMAC-SHA256 with a random 16-byte salt.
 * Output format: pbkdf2_sha256$<iterations>$<salt_hex>$<hash_hex>
 */
bool kz_hash_password(const char *password, char *out_encoded, size_t out_size);

/**
 * Verify a plaintext password against a stored PBKDF2-HMAC-SHA256 hash.
 */
bool kz_verify_password(const char *password, const char *stored_hash);

/**
 * Compute SHA-256 hex digest (64 lowercase hex chars + NUL) of an input string.
 */
bool kz_sha256_hex(const char *input, char *out_hex, size_t out_size);

/**
 * Middleware: validate session token, check expiration and revocation.
 * On failure, logs ACCESS_DENIED and sets *out_err_code and *out_err_msg.
 */
bool require_session(const char *token, kz_auth_user *out_user,
                     const char **out_err_code, const char **out_err_msg);

/**
 * Middleware: verify that the authenticated user is the owner of `room_id`.
 * On failure, logs ACCESS_DENIED and sets *out_err_code and *out_err_msg.
 */
bool require_room_owner(const kz_auth_user *user, int room_id,
                        const char **out_err_code, const char **out_err_msg);

/* Request handlers owned by Person 1 */
void handle_register(kz_connection *conn, const char *request_id, const char *payload_json);
void handle_login(kz_connection *conn, const char *request_id, const char *payload_json);
void handle_logout(kz_connection *conn, const char *request_id, const char *token);
void handle_get_my_profile(kz_connection *conn, const char *request_id, const char *token);
void handle_list_rooms(kz_connection *conn, const char *request_id, const char *token);
void handle_start_room_guard(kz_connection *conn, const char *request_id,
                             const char *token, const char *payload_json);
void handle_end_room_guard(kz_connection *conn, const char *request_id,
                           const char *token, const char *payload_json);

#endif
