#include "auth.h"
#include "config.h"
#include "db.h"
#include "log.h"

#include <ctype.h>
#include <openssl/crypto.h>
#include <openssl/evp.h>
#include <openssl/rand.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#define KZ_SALT_BYTES 16U
#define KZ_DK_BYTES 32U
#define KZ_RAW_TOKEN_BYTES 32U

static void bytes_to_hex(const unsigned char *bytes, size_t len, char *out_hex) {
    static const char hex_chars[] = "0123456789abcdef";
    for (size_t i = 0; i < len; i++) {
        out_hex[i * 2U] = hex_chars[(bytes[i] >> 4U) & 0x0FU];
        out_hex[i * 2U + 1U] = hex_chars[bytes[i] & 0x0FU];
    }
    out_hex[len * 2U] = '\0';
}

static int hex_nibble(char c) {
    if (c >= '0' && c <= '9') return c - '0';
    if (c >= 'a' && c <= 'f') return c - 'a' + 10;
    if (c >= 'A' && c <= 'F') return c - 'A' + 10;
    return -1;
}

static bool hex_to_bytes(const char *hex, unsigned char *out_bytes, size_t expected_bytes) {
    if (strlen(hex) != expected_bytes * 2U) {
        return false;
    }
    for (size_t i = 0; i < expected_bytes; i++) {
        int hi = hex_nibble(hex[i * 2U]);
        int lo = hex_nibble(hex[i * 2U + 1U]);
        if (hi < 0 || lo < 0) {
            return false;
        }
        out_bytes[i] = (unsigned char)((hi << 4) | lo);
    }
    return true;
}

bool kz_sha256_hex(const char *input, char *out_hex, size_t out_size) {
    unsigned char digest[32];
    unsigned int digest_len = 0;

    if (input == NULL || out_hex == NULL || out_size < 65U) {
        return false;
    }
    if (EVP_Digest(input, strlen(input), digest, &digest_len, EVP_sha256(), NULL) != 1 ||
        digest_len != 32U) {
        return false;
    }
    bytes_to_hex(digest, 32U, out_hex);
    return true;
}

bool kz_hash_password(const char *password, char *out_encoded, size_t out_size) {
    unsigned char salt[KZ_SALT_BYTES];
    unsigned char dk[KZ_DK_BYTES];
    char salt_hex[KZ_SALT_BYTES * 2U + 1U];
    char dk_hex[KZ_DK_BYTES * 2U + 1U];
    int written;

    if (password == NULL || out_encoded == NULL || out_size < 128U) {
        return false;
    }
    if (RAND_bytes(salt, (int)sizeof(salt)) != 1) {
        return false;
    }
    if (PKCS5_PBKDF2_HMAC(password, (int)strlen(password),
                          salt, (int)sizeof(salt),
                          KZ_PBKDF2_ITERATIONS, EVP_sha256(),
                          (int)sizeof(dk), dk) != 1) {
        return false;
    }
    bytes_to_hex(salt, sizeof(salt), salt_hex);
    bytes_to_hex(dk, sizeof(dk), dk_hex);
    written = snprintf(out_encoded, out_size, "pbkdf2_sha256$%d$%s$%s",
                       KZ_PBKDF2_ITERATIONS, salt_hex, dk_hex);
    return written > 0 && (size_t)written < out_size;
}

bool kz_verify_password(const char *password, const char *stored_hash) {
    char copy[256];
    char *scheme;
    char *iter_str;
    char *salt_hex;
    char *dk_hex;
    long iterations;
    char *end_ptr = NULL;
    unsigned char salt[KZ_SALT_BYTES];
    unsigned char expected_dk[KZ_DK_BYTES];
    unsigned char computed_dk[KZ_DK_BYTES];

    if (password == NULL || stored_hash == NULL) {
        return false;
    }
    if (strlen(stored_hash) >= sizeof(copy)) {
        return false;
    }
    strcpy(copy, stored_hash);

    scheme = strtok(copy, "$");
    iter_str = strtok(NULL, "$");
    salt_hex = strtok(NULL, "$");
    dk_hex = strtok(NULL, "$");

    if (scheme == NULL || iter_str == NULL || salt_hex == NULL || dk_hex == NULL) {
        return false;
    }
    if (strcmp(scheme, "pbkdf2_sha256") != 0) {
        return false;
    }
    iterations = strtol(iter_str, &end_ptr, 10);
    if (end_ptr == iter_str || *end_ptr != '\0' || iterations < 1000L || iterations > 10000000L) {
        return false;
    }
    if (!hex_to_bytes(salt_hex, salt, sizeof(salt)) ||
        !hex_to_bytes(dk_hex, expected_dk, sizeof(expected_dk))) {
        return false;
    }
    if (PKCS5_PBKDF2_HMAC(password, (int)strlen(password),
                          salt, (int)sizeof(salt),
                          (int)iterations, EVP_sha256(),
                          (int)sizeof(computed_dk), computed_dk) != 1) {
        return false;
    }
    return CRYPTO_memcmp(computed_dk, expected_dk, sizeof(computed_dk)) == 0;
}

static bool is_valid_username(const char *username) {
    size_t len;

    if (username == NULL) {
        return false;
    }
    len = strlen(username);
    if (len < 3U || len > 32U) {
        return false;
    }
    for (size_t i = 0; i < len; i++) {
        unsigned char ch = (unsigned char)username[i];
        if (!isalnum(ch) && ch != '_' && ch != '-' && ch != '.') {
            return false;
        }
    }
    return true;
}

static bool is_valid_password(const char *password) {
    size_t len;
    if (password == NULL) {
        return false;
    }
    len = strlen(password);
    return len >= 8U && len <= 128U;
}

static bool is_valid_role(const char *role) {
    if (role == NULL) {
        return false;
    }
    return strcmp(role, "STUDENT") == 0 ||
           strcmp(role, "HOST") == 0 ||
           strcmp(role, "ADMIN") == 0;
}

bool require_session(const char *token, kz_auth_user *out_user,
                     const char **out_err_code, const char **out_err_msg) {
    char token_hash[65];
    sqlite3 *db;
    sqlite3_stmt *stmt = NULL;
    const char *sql =
        "SELECT u.id, u.username, u.role, u.created_at, "
        "       (s.revoked_at IS NOT NULL) AS is_revoked, "
        "       (s.expires_at <= datetime('now')) AS is_expired "
        "FROM sessions s "
        "JOIN users u ON u.id = s.user_id "
        "WHERE s.token_hash = ? LIMIT 1;";

    if (out_err_code != NULL) *out_err_code = "UNAUTHORIZED";
    if (out_err_msg != NULL) *out_err_msg = "Missing or invalid session token";

    if (token == NULL || token[0] == '\0') {
        kz_log_event(0, "ACCESS_DENIED", "session", "-", "{\"reason\":\"missing_token\"}");
        if (out_err_msg != NULL) *out_err_msg = "Missing session token";
        return false;
    }
    if (!kz_sha256_hex(token, token_hash, sizeof(token_hash))) {
        if (out_err_code != NULL) *out_err_code = "INTERNAL_ERROR";
        if (out_err_msg != NULL) *out_err_msg = "Failed to hash session token";
        return false;
    }

    db = kz_db_lock();
    if (db == NULL || sqlite3_prepare_v2(db, sql, -1, &stmt, NULL) != SQLITE_OK) {
        kz_db_unlock();
        if (out_err_code != NULL) *out_err_code = "INTERNAL_ERROR";
        if (out_err_msg != NULL) *out_err_msg = "Database error while checking session";
        return false;
    }

    (void)sqlite3_bind_text(stmt, 1, token_hash, -1, SQLITE_STATIC);
    if (sqlite3_step(stmt) != SQLITE_ROW) {
        sqlite3_finalize(stmt);
        kz_log_event_db(db, 0, "ACCESS_DENIED", "session", "-", "{\"reason\":\"unknown_token\"}");
        kz_db_unlock();
        if (out_err_msg != NULL) *out_err_msg = "Invalid session token";
        return false;
    }

    int user_id = sqlite3_column_int(stmt, 0);
    const char *username = (const char *)sqlite3_column_text(stmt, 1);
    const char *role = (const char *)sqlite3_column_text(stmt, 2);
    const char *created_at = (const char *)sqlite3_column_text(stmt, 3);
    int is_revoked = sqlite3_column_int(stmt, 4);
    int is_expired = sqlite3_column_int(stmt, 5);

    if (is_revoked || is_expired) {
        char entity_id[32];
        snprintf(entity_id, sizeof(entity_id), "%d", user_id);
        sqlite3_finalize(stmt);
        kz_log_event_db(db, user_id, "ACCESS_DENIED", "session", entity_id,
                        is_revoked ? "{\"reason\":\"session_revoked\"}" : "{\"reason\":\"session_expired\"}");
        kz_db_unlock();
        if (out_err_msg != NULL) {
            *out_err_msg = is_revoked ? "Session has been logged out" : "Session has expired";
        }
        return false;
    }

    if (out_user != NULL) {
        memset(out_user, 0, sizeof(*out_user));
        out_user->id = user_id;
        if (username != NULL) {
            strncpy(out_user->username, username, sizeof(out_user->username) - 1U);
        }
        if (role != NULL) {
            strncpy(out_user->role, role, sizeof(out_user->role) - 1U);
        }
        if (created_at != NULL) {
            strncpy(out_user->created_at, created_at, sizeof(out_user->created_at) - 1U);
        }
        memcpy(out_user->token_hash, token_hash, sizeof(out_user->token_hash));
    }

    sqlite3_finalize(stmt);
    kz_db_unlock();
    return true;
}

bool require_room_owner(const kz_auth_user *user, int room_id,
                        const char **out_err_code, const char **out_err_msg) {
    sqlite3 *db;
    sqlite3_stmt *stmt = NULL;
    const char *sql = "SELECT owner_id FROM exam_rooms WHERE id = ? LIMIT 1;";
    int owner_id = -1;
    char room_id_str[32];

    if (user == NULL || room_id <= 0) {
        if (out_err_code != NULL) *out_err_code = "BAD_REQUEST";
        if (out_err_msg != NULL) *out_err_msg = "Invalid room_id";
        return false;
    }
    snprintf(room_id_str, sizeof(room_id_str), "%d", room_id);

    db = kz_db_lock();
    if (db == NULL || sqlite3_prepare_v2(db, sql, -1, &stmt, NULL) != SQLITE_OK) {
        kz_db_unlock();
        if (out_err_code != NULL) *out_err_code = "INTERNAL_ERROR";
        if (out_err_msg != NULL) *out_err_msg = "Database error while checking room owner";
        return false;
    }

    (void)sqlite3_bind_int(stmt, 1, room_id);
    if (sqlite3_step(stmt) != SQLITE_ROW) {
        sqlite3_finalize(stmt);
        kz_db_unlock();
        if (out_err_code != NULL) *out_err_code = "NOT_FOUND";
        if (out_err_msg != NULL) *out_err_msg = "Room not found";
        return false;
    }

    owner_id = sqlite3_column_int(stmt, 0);
    sqlite3_finalize(stmt);

    if (owner_id != user->id) {
        kz_log_event_db(db, user->id, "ACCESS_DENIED", "exam_room", room_id_str,
                        "{\"reason\":\"not_room_owner\"}");
        kz_db_unlock();
        if (out_err_code != NULL) *out_err_code = "FORBIDDEN";
        if (out_err_msg != NULL) *out_err_msg = "Only the room owner can perform this action";
        return false;
    }

    kz_db_unlock();
    return true;
}

void handle_register(kz_connection *conn, const char *request_id, const char *payload_json) {
    char username[64];
    char password[160];
    char role[16] = "STUDENT";
    char password_hash[256];
    sqlite3 *db;
    sqlite3_stmt *stmt = NULL;
    const char *insert_sql =
        "INSERT INTO users(username, password_hash, role) VALUES (?, ?, ?);";
    int rc;
    int user_id;
    char escaped_username[128];
    char entity_id[32];
    char detail_json[256];
    char data_json[256];

    if (!find_json_string_member(payload_json, "username", username, sizeof(username))) {
        send_error(conn->socket_fd, request_id, "BAD_REQUEST", "username is required");
        return;
    }
    if (!find_json_string_member(payload_json, "password", password, sizeof(password))) {
        send_error(conn->socket_fd, request_id, "BAD_REQUEST", "password is required");
        return;
    }
    if (find_json_string_member(payload_json, "role", role, sizeof(role))) {
        if (!is_valid_role(role)) {
            send_error(conn->socket_fd, request_id, "BAD_REQUEST", "Invalid role");
            return;
        }
    }
    if (!is_valid_username(username)) {
        send_error(conn->socket_fd, request_id, "BAD_REQUEST",
                   "Username must be 3-32 characters (letters, digits, _, -, .)");
        return;
    }
    if (!is_valid_password(password)) {
        send_error(conn->socket_fd, request_id, "BAD_REQUEST",
                   "Password must be at least 8 characters");
        return;
    }
    if (!kz_hash_password(password, password_hash, sizeof(password_hash))) {
        send_error(conn->socket_fd, request_id, "INTERNAL_ERROR", "Failed to hash password");
        return;
    }

    db = kz_db_lock();
    if (db == NULL || sqlite3_prepare_v2(db, insert_sql, -1, &stmt, NULL) != SQLITE_OK) {
        kz_db_unlock();
        send_error(conn->socket_fd, request_id, "INTERNAL_ERROR", "Database error");
        return;
    }
    (void)sqlite3_bind_text(stmt, 1, username, -1, SQLITE_STATIC);
    (void)sqlite3_bind_text(stmt, 2, password_hash, -1, SQLITE_STATIC);
    (void)sqlite3_bind_text(stmt, 3, role, -1, SQLITE_STATIC);

    rc = sqlite3_step(stmt);
    if (rc != SQLITE_DONE) {
        int ext_err = sqlite3_extended_errcode(db);
        sqlite3_finalize(stmt);
        kz_db_unlock();
        if (rc == SQLITE_CONSTRAINT || (ext_err & 0xFF) == SQLITE_CONSTRAINT) {
            send_error(conn->socket_fd, request_id, "CONFLICT", "Username already exists");
        } else {
            send_error(conn->socket_fd, request_id, "INTERNAL_ERROR", "Could not create user");
        }
        return;
    }

    user_id = (int)sqlite3_last_insert_rowid(db);
    sqlite3_finalize(stmt);

    json_escape(username, escaped_username, sizeof(escaped_username));
    snprintf(entity_id, sizeof(entity_id), "%d", user_id);
    snprintf(detail_json, sizeof(detail_json),
             "{\"username\":\"%s\",\"role\":\"%s\"}", escaped_username, role);
    kz_log_event_db(db, user_id, "REGISTER_SUCCESS", "user", entity_id, detail_json);
    kz_db_unlock();

    snprintf(data_json, sizeof(data_json),
             "{\"user\":{\"id\":%d,\"username\":\"%s\",\"role\":\"%s\"}}",
             user_id, escaped_username, role);
    (void)send_ok_data(conn->socket_fd, request_id, data_json);
}

void handle_login(kz_connection *conn, const char *request_id, const char *payload_json) {
    char username[64];
    char password[160];
    sqlite3 *db;
    sqlite3_stmt *stmt = NULL;
    const char *select_sql =
        "SELECT id, username, password_hash, role FROM users WHERE username = ? LIMIT 1;";
    int user_id = 0;
    char db_username[64] = {0};
    char db_hash[256] = {0};
    char db_role[16] = {0};
    unsigned char raw_token[KZ_RAW_TOKEN_BYTES];
    char token[KZ_RAW_TOKEN_BYTES * 2U + 1U];
    char token_hash[65];
    char expires_at[32] = {0};
    char escaped_username[128];
    char entity_id[32];
    char detail_json[256];
    char data_json[512];

    if (!find_json_string_member(payload_json, "username", username, sizeof(username)) ||
        username[0] == '\0') {
        send_error(conn->socket_fd, request_id, "BAD_REQUEST", "username is required");
        return;
    }
    if (!find_json_string_member(payload_json, "password", password, sizeof(password)) ||
        password[0] == '\0') {
        send_error(conn->socket_fd, request_id, "BAD_REQUEST", "password is required");
        return;
    }

    json_escape(username, escaped_username, sizeof(escaped_username));

    db = kz_db_lock();
    if (db == NULL || sqlite3_prepare_v2(db, select_sql, -1, &stmt, NULL) != SQLITE_OK) {
        kz_db_unlock();
        send_error(conn->socket_fd, request_id, "INTERNAL_ERROR", "Database error");
        return;
    }
    (void)sqlite3_bind_text(stmt, 1, username, -1, SQLITE_STATIC);
    if (sqlite3_step(stmt) != SQLITE_ROW) {
        sqlite3_finalize(stmt);
        snprintf(detail_json, sizeof(detail_json),
                 "{\"username\":\"%s\",\"reason\":\"user_not_found\"}", escaped_username);
        kz_log_event_db(db, 0, "LOGIN_FAILED", "user", escaped_username, detail_json);
        kz_db_unlock();
        send_error(conn->socket_fd, request_id, "UNAUTHORIZED", "Invalid username or password");
        return;
    }

    user_id = sqlite3_column_int(stmt, 0);
    strncpy(db_username, (const char *)sqlite3_column_text(stmt, 1), sizeof(db_username) - 1U);
    strncpy(db_hash, (const char *)sqlite3_column_text(stmt, 2), sizeof(db_hash) - 1U);
    strncpy(db_role, (const char *)sqlite3_column_text(stmt, 3), sizeof(db_role) - 1U);
    sqlite3_finalize(stmt);

    snprintf(entity_id, sizeof(entity_id), "%d", user_id);
    if (!kz_verify_password(password, db_hash)) {
        snprintf(detail_json, sizeof(detail_json),
                 "{\"username\":\"%s\",\"reason\":\"wrong_password\"}", escaped_username);
        kz_log_event_db(db, user_id, "LOGIN_FAILED", "user", entity_id, detail_json);
        kz_db_unlock();
        send_error(conn->socket_fd, request_id, "UNAUTHORIZED", "Invalid username or password");
        return;
    }

    if (RAND_bytes(raw_token, (int)sizeof(raw_token)) != 1) {
        kz_db_unlock();
        send_error(conn->socket_fd, request_id, "INTERNAL_ERROR", "Failed to generate token");
        return;
    }
    bytes_to_hex(raw_token, sizeof(raw_token), token);
    if (!kz_sha256_hex(token, token_hash, sizeof(token_hash))) {
        kz_db_unlock();
        send_error(conn->socket_fd, request_id, "INTERNAL_ERROR", "Failed to hash token");
        return;
    }

    const char *insert_session_sql =
        "INSERT INTO sessions(token_hash, user_id, expires_at) "
        "VALUES (?, ?, datetime('now', '+24 hours'));";
    if (sqlite3_prepare_v2(db, insert_session_sql, -1, &stmt, NULL) != SQLITE_OK) {
        kz_db_unlock();
        send_error(conn->socket_fd, request_id, "INTERNAL_ERROR", "Failed to create session");
        return;
    }
    (void)sqlite3_bind_text(stmt, 1, token_hash, -1, SQLITE_STATIC);
    (void)sqlite3_bind_int(stmt, 2, user_id);
    if (sqlite3_step(stmt) != SQLITE_DONE) {
        sqlite3_finalize(stmt);
        kz_db_unlock();
        send_error(conn->socket_fd, request_id, "INTERNAL_ERROR", "Failed to save session");
        return;
    }
    sqlite3_finalize(stmt);

    const char *exp_sql = "SELECT expires_at FROM sessions WHERE token_hash = ? LIMIT 1;";
    if (sqlite3_prepare_v2(db, exp_sql, -1, &stmt, NULL) == SQLITE_OK) {
        (void)sqlite3_bind_text(stmt, 1, token_hash, -1, SQLITE_STATIC);
        if (sqlite3_step(stmt) == SQLITE_ROW && sqlite3_column_text(stmt, 0) != NULL) {
            strncpy(expires_at, (const char *)sqlite3_column_text(stmt, 0), sizeof(expires_at) - 1U);
        }
        sqlite3_finalize(stmt);
    }

    snprintf(detail_json, sizeof(detail_json), "{\"username\":\"%s\"}", escaped_username);
    kz_log_event_db(db, user_id, "LOGIN_SUCCESS", "session", entity_id, detail_json);
    kz_db_unlock();

    snprintf(data_json, sizeof(data_json),
             "{\"token\":\"%s\",\"expires_at\":\"%s\","
             "\"user\":{\"id\":%d,\"username\":\"%s\",\"role\":\"%s\"}}",
             token, expires_at, user_id, escaped_username, db_role);
    (void)send_ok_data(conn->socket_fd, request_id, data_json);
}

void handle_logout(kz_connection *conn, const char *request_id, const char *token) {
    kz_auth_user user;
    const char *err_code = NULL;
    const char *err_msg = NULL;
    sqlite3 *db;
    sqlite3_stmt *stmt = NULL;
    const char *sql =
        "UPDATE sessions SET revoked_at = CURRENT_TIMESTAMP WHERE token_hash = ?;";
    char entity_id[32];

    if (!require_session(token, &user, &err_code, &err_msg)) {
        send_error(conn->socket_fd, request_id, err_code, err_msg);
        return;
    }

    db = kz_db_lock();
    if (db == NULL || sqlite3_prepare_v2(db, sql, -1, &stmt, NULL) != SQLITE_OK) {
        kz_db_unlock();
        send_error(conn->socket_fd, request_id, "INTERNAL_ERROR", "Failed to revoke session");
        return;
    }
    (void)sqlite3_bind_text(stmt, 1, user.token_hash, -1, SQLITE_STATIC);
    (void)sqlite3_step(stmt);
    sqlite3_finalize(stmt);

    snprintf(entity_id, sizeof(entity_id), "%d", user.id);
    kz_log_event_db(db, user.id, "LOGOUT", "session", entity_id, "{}");
    kz_db_unlock();

    (void)send_ok_data(conn->socket_fd, request_id, "{\"logged_out\":true}");
}

void handle_get_my_profile(kz_connection *conn, const char *request_id, const char *token) {
    kz_auth_user user;
    const char *err_code = NULL;
    const char *err_msg = NULL;
    char escaped_username[128];
    char escaped_created[64];
    char data_json[512];

    if (!require_session(token, &user, &err_code, &err_msg)) {
        send_error(conn->socket_fd, request_id, err_code, err_msg);
        return;
    }
    json_escape(user.username, escaped_username, sizeof(escaped_username));
    json_escape(user.created_at, escaped_created, sizeof(escaped_created));
    snprintf(data_json, sizeof(data_json),
             "{\"user\":{\"id\":%d,\"username\":\"%s\",\"role\":\"%s\",\"created_at\":\"%s\"}}",
             user.id, escaped_username, user.role, escaped_created);
    (void)send_ok_data(conn->socket_fd, request_id, data_json);
}

void handle_list_rooms(kz_connection *conn, const char *request_id, const char *token) {
    kz_auth_user user;
    const char *err_code = NULL;
    const char *err_msg = NULL;
    sqlite3 *db;
    sqlite3_stmt *stmt = NULL;
    const char *sql =
        "SELECT r.id, r.name, r.owner_id, u.username, r.status, r.duration_seconds, "
        "       (SELECT COUNT(*) FROM room_participants rp WHERE rp.room_id = r.id) AS participant_count "
        "FROM exam_rooms r "
        "JOIN users u ON u.id = r.owner_id "
        "ORDER BY r.id DESC;";
    char *buf;
    size_t buf_cap = 32768U;
    size_t used = 0U;
    bool first = true;

    if (!require_session(token, &user, &err_code, &err_msg)) {
        send_error(conn->socket_fd, request_id, err_code, err_msg);
        return;
    }

    buf = (char *)malloc(buf_cap);
    if (buf == NULL) {
        send_error(conn->socket_fd, request_id, "INTERNAL_ERROR", "Out of memory");
        return;
    }
    used += (size_t)snprintf(buf + used, buf_cap - used, "{\"rooms\":[");

    db = kz_db_lock();
    if (db == NULL || sqlite3_prepare_v2(db, sql, -1, &stmt, NULL) != SQLITE_OK) {
        kz_db_unlock();
        free(buf);
        send_error(conn->socket_fd, request_id, "INTERNAL_ERROR", "Database error");
        return;
    }

    while (sqlite3_step(stmt) == SQLITE_ROW) {
        int room_id = sqlite3_column_int(stmt, 0);
        const char *name = (const char *)sqlite3_column_text(stmt, 1);
        int owner_id = sqlite3_column_int(stmt, 2);
        const char *owner_name = (const char *)sqlite3_column_text(stmt, 3);
        const char *status = (const char *)sqlite3_column_text(stmt, 4);
        int duration_sec = sqlite3_column_int(stmt, 5);
        int participant_count = sqlite3_column_int(stmt, 6);
        char esc_name[256];
        char esc_owner[128];
        char esc_status[32];
        int n;

        json_escape(name ? name : "", esc_name, sizeof(esc_name));
        json_escape(owner_name ? owner_name : "", esc_owner, sizeof(esc_owner));
        json_escape(status ? status : "WAITING", esc_status, sizeof(esc_status));

        if (used + 512U >= buf_cap) {
            break;
        }
        n = snprintf(buf + used, buf_cap - used,
                     "%s{\"id\":%d,\"name\":\"%s\",\"owner_id\":%d,\"owner_name\":\"%s\","
                     "\"status\":\"%s\",\"duration_seconds\":%d,\"participant_count\":%d}",
                     first ? "" : ",",
                     room_id, esc_name, owner_id, esc_owner, esc_status,
                     duration_sec, participant_count);
        if (n > 0) {
            used += (size_t)n;
        }
        first = false;
    }
    sqlite3_finalize(stmt);
    kz_db_unlock();

    (void)snprintf(buf + used, buf_cap - used, "]}");
    (void)send_ok_data(conn->socket_fd, request_id, buf);
    free(buf);
}

void handle_start_room_guard(kz_connection *conn, const char *request_id,
                             const char *token, const char *payload_json) {
    kz_auth_user user;
    const char *err_code = NULL;
    const char *err_msg = NULL;
    int room_id = 0;

    if (!require_session(token, &user, &err_code, &err_msg)) {
        send_error(conn->socket_fd, request_id, err_code, err_msg);
        return;
    }
    if (!find_json_int_member(payload_json, "room_id", &room_id) || room_id <= 0) {
        send_error(conn->socket_fd, request_id, "BAD_REQUEST", "room_id must be a positive integer");
        return;
    }
    if (!require_room_owner(&user, room_id, &err_code, &err_msg)) {
        send_error(conn->socket_fd, request_id, err_code, err_msg);
        return;
    }
    /* Owner verified; Person 2's room start logic will transition WAITING -> RUNNING */
    {
        sqlite3 *db = kz_db_lock();
        sqlite3_stmt *stmt = NULL;
        const char *sql =
            "UPDATE exam_rooms "
            "SET status = 'RUNNING', "
            "    started_at = datetime('now'), "
            "    ended_at = datetime('now', '+' || duration_seconds || ' seconds') "
            "WHERE id = ? AND status = 'WAITING';";
        if (db != NULL && sqlite3_prepare_v2(db, sql, -1, &stmt, NULL) == SQLITE_OK) {
            (void)sqlite3_bind_int(stmt, 1, room_id);
            (void)sqlite3_step(stmt);
            int changes = sqlite3_changes(db);
            sqlite3_finalize(stmt);
            if (changes == 0) {
                kz_db_unlock();
                send_error(conn->socket_fd, request_id, "CONFLICT", "Room is not in WAITING state");
                return;
            }
            char entity_id[32];
            snprintf(entity_id, sizeof(entity_id), "%d", room_id);
            kz_log_event_db(db, user.id, "START_ROOM", "exam_room", entity_id, "{}");
        }
        kz_db_unlock();
    }
    {
        char data_json[128];
        snprintf(data_json, sizeof(data_json), "{\"room_id\":%d,\"status\":\"RUNNING\"}", room_id);
        (void)send_ok_data(conn->socket_fd, request_id, data_json);
    }
}

void handle_end_room_guard(kz_connection *conn, const char *request_id,
                           const char *token, const char *payload_json) {
    kz_auth_user user;
    const char *err_code = NULL;
    const char *err_msg = NULL;
    int room_id = 0;

    if (!require_session(token, &user, &err_code, &err_msg)) {
        send_error(conn->socket_fd, request_id, err_code, err_msg);
        return;
    }
    if (!find_json_int_member(payload_json, "room_id", &room_id) || room_id <= 0) {
        send_error(conn->socket_fd, request_id, "BAD_REQUEST", "room_id must be a positive integer");
        return;
    }
    if (!require_room_owner(&user, room_id, &err_code, &err_msg)) {
        send_error(conn->socket_fd, request_id, err_code, err_msg);
        return;
    }
    {
        sqlite3 *db = kz_db_lock();
        sqlite3_stmt *stmt = NULL;
        const char *sql =
            "UPDATE exam_rooms SET status = 'ENDED', ended_at = datetime('now') "
            "WHERE id = ? AND status = 'RUNNING';";
        if (db != NULL && sqlite3_prepare_v2(db, sql, -1, &stmt, NULL) == SQLITE_OK) {
            (void)sqlite3_bind_int(stmt, 1, room_id);
            (void)sqlite3_step(stmt);
            int changes = sqlite3_changes(db);
            sqlite3_finalize(stmt);
            if (changes == 0) {
                kz_db_unlock();
                send_error(conn->socket_fd, request_id, "CONFLICT", "Room is not in RUNNING state");
                return;
            }
            char entity_id[32];
            snprintf(entity_id, sizeof(entity_id), "%d", room_id);
            kz_log_event_db(db, user.id, "END_ROOM", "exam_room", entity_id, "{}");
        }
        kz_db_unlock();
    }
    {
        char data_json[128];
        snprintf(data_json, sizeof(data_json), "{\"room_id\":%d,\"status\":\"ENDED\"}", room_id);
        (void)send_ok_data(conn->socket_fd, request_id, data_json);
    }
}
