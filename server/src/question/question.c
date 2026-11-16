#include "question.h"

#include "auth.h"
#include "db.h"
#include "log.h"
#include "protocol.h"

#include <ctype.h>
#include <stdarg.h>
#include <stdbool.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#define KZ_QUESTION_CONTENT_MAX 1200U
#define KZ_QUESTION_TOPIC_MAX 64U
#define KZ_QUESTION_OPTION_MAX 400U
#define KZ_QUESTION_EXPLANATION_MAX 1200U
#define KZ_QUESTION_UPDATE_JSON_MAX 8192U
#define KZ_QUESTION_LIST_RESPONSE_BYTES (60U * 1024U)
#define KZ_QUESTION_LIST_DEFAULT_LIMIT 20
#define KZ_QUESTION_LIST_MAX_LIMIT 20
#define KZ_IMPORT_MAX_QUESTIONS 100U

typedef struct {
    char content[KZ_QUESTION_CONTENT_MAX + 1U];
    char topic[KZ_QUESTION_TOPIC_MAX + 1U];
    char difficulty[8];
    char options[4][KZ_QUESTION_OPTION_MAX + 1U];
    int correct_option_index;
    char explanation[KZ_QUESTION_EXPLANATION_MAX + 1U];
} kz_question_input;

static const char *skip_whitespace_local(const char *value) {
    while (value != NULL && *value != '\0' && isspace((unsigned char)*value)) {
        value++;
    }
    return value;
}

static bool has_non_whitespace(const char *value) {
    const char *cursor = value;
    while (cursor != NULL && *cursor != '\0') {
        if (!isspace((unsigned char)*cursor)) {
            return true;
        }
        cursor++;
    }
    return false;
}

static bool is_valid_difficulty(const char *difficulty) {
    return difficulty != NULL &&
           (strcmp(difficulty, "easy") == 0 ||
            strcmp(difficulty, "medium") == 0 ||
            strcmp(difficulty, "hard") == 0);
}

static bool parse_question_input(const char *json, kz_question_input *out_input,
                                 const char **out_error) {
    size_t option_count = 0U;

    if (out_error != NULL) {
        *out_error = "Invalid question payload";
    }
    if (json == NULL || out_input == NULL) {
        return false;
    }
    memset(out_input, 0, sizeof(*out_input));

    if (!find_json_string_member(json, "content", out_input->content,
                                 sizeof(out_input->content)) ||
        !has_non_whitespace(out_input->content)) {
        if (out_error != NULL) *out_error = "content is required and must be at most 1200 bytes";
        return false;
    }
    if (!find_json_string_member(json, "topic", out_input->topic,
                                 sizeof(out_input->topic)) ||
        !has_non_whitespace(out_input->topic)) {
        if (out_error != NULL) *out_error = "topic is required and must be at most 64 bytes";
        return false;
    }
    if (!find_json_string_member(json, "difficulty", out_input->difficulty,
                                 sizeof(out_input->difficulty)) ||
        !is_valid_difficulty(out_input->difficulty)) {
        if (out_error != NULL) *out_error = "difficulty must be easy, medium, or hard";
        return false;
    }
    if (!find_json_string_array_member(json, "options", (char *)out_input->options,
                                       sizeof(out_input->options[0]), 4U, &option_count) ||
        option_count != 4U) {
        if (out_error != NULL) *out_error = "options must contain exactly four strings";
        return false;
    }
    for (size_t index = 0U; index < option_count; index++) {
        if (!has_non_whitespace(out_input->options[index])) {
            if (out_error != NULL) *out_error = "every option must be non-empty";
            return false;
        }
    }
    if (!find_json_int_member(json, "correct_option_index", &out_input->correct_option_index) ||
        out_input->correct_option_index < 0 || out_input->correct_option_index > 3) {
        if (out_error != NULL) *out_error = "correct_option_index must be an integer from 0 to 3";
        return false;
    }
    if (!find_json_string_member(json, "explanation", out_input->explanation,
                                 sizeof(out_input->explanation))) {
        out_input->explanation[0] = '\0';
    }
    return true;
}

static bool require_admin(kz_connection *conn, const char *request_id,
                          const char *token, kz_auth_user *out_user) {
    kz_auth_user user;
    const char *error_code = NULL;
    const char *error_message = NULL;
    char entity_id[32];

    if (!require_session(token, &user, &error_code, &error_message)) {
        send_error(conn->socket_fd, request_id, error_code, error_message);
        return false;
    }
    if (strcmp(user.role, "ADMIN") != 0) {
        (void)snprintf(entity_id, sizeof(entity_id), "%d", user.id);
        kz_log_event(user.id, "ACCESS_DENIED", "question_bank", entity_id,
                     "{\"reason\":\"admin_required\"}");
        send_error(conn->socket_fd, request_id, "FORBIDDEN",
                   "Only an ADMIN can manage the question bank");
        return false;
    }
    if (out_user != NULL) {
        *out_user = user;
    }
    return true;
}

static bool execute_sql(sqlite3 *db, const char *sql) {
    char *error_message = NULL;
    int rc = sqlite3_exec(db, sql, NULL, NULL, &error_message);
    if (rc == SQLITE_OK) {
        return true;
    }
    sqlite3_free(error_message);
    return false;
}

static bool insert_question(sqlite3 *db, const kz_question_input *input,
                            int *out_question_id) {
    static const char labels[] = "ABCD";
    sqlite3_stmt *statement = NULL;
    int option_ids[4] = {0, 0, 0, 0};
    int question_id;
    const char *insert_question_sql =
        "INSERT INTO questions(content, topic, difficulty, correct_option_id, is_active, explanation) "
        "VALUES (?, ?, ?, NULL, 1, ?);";
    const char *insert_option_sql =
        "INSERT INTO question_options(question_id, label, content, position) "
        "VALUES (?, ?, ?, ?);";
    const char *set_correct_option_sql =
        "UPDATE questions SET correct_option_id = ? WHERE id = ?;";

    if (sqlite3_prepare_v2(db, insert_question_sql, -1, &statement, NULL) != SQLITE_OK) {
        return false;
    }
    (void)sqlite3_bind_text(statement, 1, input->content, -1, SQLITE_STATIC);
    (void)sqlite3_bind_text(statement, 2, input->topic, -1, SQLITE_STATIC);
    (void)sqlite3_bind_text(statement, 3, input->difficulty, -1, SQLITE_STATIC);
    (void)sqlite3_bind_text(statement, 4, input->explanation, -1, SQLITE_STATIC);
    if (sqlite3_step(statement) != SQLITE_DONE) {
        sqlite3_finalize(statement);
        return false;
    }
    sqlite3_finalize(statement);
    question_id = (int)sqlite3_last_insert_rowid(db);

    for (int index = 0; index < 4; index++) {
        statement = NULL;
        if (sqlite3_prepare_v2(db, insert_option_sql, -1, &statement, NULL) != SQLITE_OK) {
            return false;
        }
        (void)sqlite3_bind_int(statement, 1, question_id);
        (void)sqlite3_bind_text(statement, 2, &labels[index], 1, SQLITE_STATIC);
        (void)sqlite3_bind_text(statement, 3, input->options[index], -1, SQLITE_STATIC);
        (void)sqlite3_bind_int(statement, 4, index + 1);
        if (sqlite3_step(statement) != SQLITE_DONE) {
            sqlite3_finalize(statement);
            return false;
        }
        sqlite3_finalize(statement);
        option_ids[index] = (int)sqlite3_last_insert_rowid(db);
    }

    if (sqlite3_prepare_v2(db, set_correct_option_sql, -1, &statement, NULL) != SQLITE_OK) {
        return false;
    }
    (void)sqlite3_bind_int(statement, 1, option_ids[input->correct_option_index]);
    (void)sqlite3_bind_int(statement, 2, question_id);
    if (sqlite3_step(statement) != SQLITE_DONE) {
        sqlite3_finalize(statement);
        return false;
    }
    sqlite3_finalize(statement);
    if (out_question_id != NULL) {
        *out_question_id = question_id;
    }
    return true;
}

static bool question_exists(sqlite3 *db, int question_id) {
    sqlite3_stmt *statement = NULL;
    bool exists = false;

    if (sqlite3_prepare_v2(db, "SELECT 1 FROM questions WHERE id = ? LIMIT 1;",
                           -1, &statement, NULL) != SQLITE_OK) {
        return false;
    }
    (void)sqlite3_bind_int(statement, 1, question_id);
    exists = sqlite3_step(statement) == SQLITE_ROW;
    sqlite3_finalize(statement);
    return exists;
}

static bool replace_question(sqlite3 *db, int question_id,
                             const kz_question_input *input) {
    sqlite3_stmt *statement = NULL;
    int correct_option_id = 0;
    const char *update_question_sql =
        "UPDATE questions SET content = ?, topic = ?, difficulty = ?, explanation = ? WHERE id = ?;";
    const char *update_option_sql =
        "UPDATE question_options SET content = ? WHERE question_id = ? AND position = ?;";

    if (sqlite3_prepare_v2(db, update_question_sql, -1, &statement, NULL) != SQLITE_OK) {
        return false;
    }
    (void)sqlite3_bind_text(statement, 1, input->content, -1, SQLITE_STATIC);
    (void)sqlite3_bind_text(statement, 2, input->topic, -1, SQLITE_STATIC);
    (void)sqlite3_bind_text(statement, 3, input->difficulty, -1, SQLITE_STATIC);
    (void)sqlite3_bind_text(statement, 4, input->explanation, -1, SQLITE_STATIC);
    (void)sqlite3_bind_int(statement, 5, question_id);
    if (sqlite3_step(statement) != SQLITE_DONE) {
        sqlite3_finalize(statement);
        return false;
    }
    sqlite3_finalize(statement);

    for (int index = 0; index < 4; index++) {
        statement = NULL;
        if (sqlite3_prepare_v2(db, update_option_sql, -1, &statement, NULL) != SQLITE_OK) {
            return false;
        }
        (void)sqlite3_bind_text(statement, 1, input->options[index], -1, SQLITE_STATIC);
        (void)sqlite3_bind_int(statement, 2, question_id);
        (void)sqlite3_bind_int(statement, 3, index + 1);
        if (sqlite3_step(statement) != SQLITE_DONE || sqlite3_changes(db) != 1) {
            sqlite3_finalize(statement);
            return false;
        }
        sqlite3_finalize(statement);
    }

    if (sqlite3_prepare_v2(db,
                           "SELECT id FROM question_options WHERE question_id = ? AND position = ?;",
                           -1, &statement, NULL) != SQLITE_OK) {
        return false;
    }
    (void)sqlite3_bind_int(statement, 1, question_id);
    (void)sqlite3_bind_int(statement, 2, input->correct_option_index + 1);
    if (sqlite3_step(statement) != SQLITE_ROW) {
        sqlite3_finalize(statement);
        return false;
    }
    correct_option_id = sqlite3_column_int(statement, 0);
    sqlite3_finalize(statement);

    if (sqlite3_prepare_v2(db,
                           "UPDATE questions SET correct_option_id = ? WHERE id = ?;",
                           -1, &statement, NULL) != SQLITE_OK) {
        return false;
    }
    (void)sqlite3_bind_int(statement, 1, correct_option_id);
    (void)sqlite3_bind_int(statement, 2, question_id);
    if (sqlite3_step(statement) != SQLITE_DONE) {
        sqlite3_finalize(statement);
        return false;
    }
    sqlite3_finalize(statement);
    return true;
}

static bool update_question_active_state(sqlite3 *db, int question_id, int is_active) {
    sqlite3_stmt *statement = NULL;
    bool ok = false;

    if (sqlite3_prepare_v2(db, "UPDATE questions SET is_active = ? WHERE id = ?;",
                           -1, &statement, NULL) != SQLITE_OK) {
        return false;
    }
    (void)sqlite3_bind_int(statement, 1, is_active);
    (void)sqlite3_bind_int(statement, 2, question_id);
    ok = sqlite3_step(statement) == SQLITE_DONE;
    sqlite3_finalize(statement);
    return ok;
}

static bool append_format(char *buffer, size_t capacity, size_t *used,
                          const char *format, ...) {
    va_list arguments;
    int written;

    if (buffer == NULL || used == NULL || *used >= capacity) {
        return false;
    }
    va_start(arguments, format);
    written = vsnprintf(buffer + *used, capacity - *used, format, arguments);
    va_end(arguments);
    if (written < 0 || (size_t)written >= capacity - *used) {
        return false;
    }
    *used += (size_t)written;
    return true;
}

static bool append_question_json(sqlite3 *db, sqlite3_stmt *question_row,
                                 char *buffer, size_t capacity, size_t *used,
                                 bool first) {
    sqlite3_stmt *option_statement = NULL;
    int question_id = sqlite3_column_int(question_row, 0);
    const char *content = (const char *)sqlite3_column_text(question_row, 1);
    const char *topic = (const char *)sqlite3_column_text(question_row, 2);
    const char *difficulty = (const char *)sqlite3_column_text(question_row, 3);
    int correct_option_id = sqlite3_column_int(question_row, 4);
    int is_active = sqlite3_column_int(question_row, 5);
    const char *explanation = (const char *)sqlite3_column_text(question_row, 6);
    char escaped_content[(KZ_QUESTION_CONTENT_MAX * 2U) + 1U];
    char escaped_topic[(KZ_QUESTION_TOPIC_MAX * 2U) + 1U];
    char escaped_difficulty[16];
    char escaped_explanation[(KZ_QUESTION_EXPLANATION_MAX * 2U) + 1U];
    int option_count = 0;
    int correct_index = -1;
    bool option_first = true;
    bool ok = false;

    json_escape(content ? content : "", escaped_content, sizeof(escaped_content));
    json_escape(topic ? topic : "", escaped_topic, sizeof(escaped_topic));
    json_escape(difficulty ? difficulty : "", escaped_difficulty, sizeof(escaped_difficulty));
    json_escape(explanation ? explanation : "", escaped_explanation, sizeof(escaped_explanation));

    if (!append_format(buffer, capacity, used,
                       "%s{\"id\":%d,\"content\":\"%s\",\"topic\":\"%s\","
                       "\"difficulty\":\"%s\",\"options\":[",
                       first ? "" : ",", question_id, escaped_content,
                       escaped_topic, escaped_difficulty)) {
        return false;
    }

    if (sqlite3_prepare_v2(db,
                           "SELECT id, label, content, position FROM question_options "
                           "WHERE question_id = ? ORDER BY position ASC;",
                           -1, &option_statement, NULL) != SQLITE_OK) {
        return false;
    }
    (void)sqlite3_bind_int(option_statement, 1, question_id);
    while (sqlite3_step(option_statement) == SQLITE_ROW) {
        int option_id = sqlite3_column_int(option_statement, 0);
        const char *label = (const char *)sqlite3_column_text(option_statement, 1);
        const char *option_content = (const char *)sqlite3_column_text(option_statement, 2);
        int position = sqlite3_column_int(option_statement, 3);
        char escaped_label[8];
        char escaped_option[(KZ_QUESTION_OPTION_MAX * 2U) + 1U];

        json_escape(label ? label : "", escaped_label, sizeof(escaped_label));
        json_escape(option_content ? option_content : "", escaped_option, sizeof(escaped_option));
        if (!append_format(buffer, capacity, used,
                           "%s{\"id\":%d,\"label\":\"%s\",\"content\":\"%s\",\"position\":%d}",
                           option_first ? "" : ",", option_id, escaped_label,
                           escaped_option, position)) {
            goto done;
        }
        if (option_id == correct_option_id) {
            correct_index = position - 1;
        }
        option_count++;
        option_first = false;
    }
    if (option_count != 4 || correct_index < 0 ||
        !append_format(buffer, capacity, used,
                       "],\"correct_option_id\":%d,\"correct_option_index\":%d,"
                       "\"is_active\":%d,\"explanation\":\"%s\"}",
                       correct_option_id, correct_index, is_active ? 1 : 0,
                       escaped_explanation)) {
        goto done;
    }
    ok = true;

done:
    sqlite3_finalize(option_statement);
    return ok;
}

static bool next_array_object(const char **cursor, char *output, size_t output_size,
                              bool *out_has_object) {
    const char *start;
    const char *scan;
    size_t len;
    unsigned int depth = 0U;
    bool in_string = false;
    bool escaped = false;

    if (cursor == NULL || *cursor == NULL || output == NULL || output_size == 0U ||
        out_has_object == NULL) {
        return false;
    }
    scan = skip_whitespace_local(*cursor);
    if (*scan == '[') {
        scan = skip_whitespace_local(scan + 1);
    }
    if (*scan == ']') {
        *cursor = scan + 1;
        *out_has_object = false;
        return true;
    }
    if (*scan != '{') {
        return false;
    }
    start = scan;
    for (; *scan != '\0'; scan++) {
        if (in_string) {
            if (escaped) {
                escaped = false;
            } else if (*scan == '\\') {
                escaped = true;
            } else if (*scan == '"') {
                in_string = false;
            }
            continue;
        }
        if (*scan == '"') {
            in_string = true;
        } else if (*scan == '{') {
            depth++;
        } else if (*scan == '}') {
            if (depth == 0U) {
                return false;
            }
            depth--;
            if (depth == 0U) {
                scan++;
                break;
            }
        }
    }
    if (depth != 0U) {
        return false;
    }
    len = (size_t)(scan - start);
    if (len + 1U > output_size) {
        return false;
    }
    memcpy(output, start, len);
    output[len] = '\0';

    scan = skip_whitespace_local(scan);
    if (*scan == ',') {
        scan++;
    } else if (*scan != ']') {
        return false;
    }
    *cursor = scan;
    *out_has_object = true;
    return true;
}

void handle_list_questions(kz_connection *conn, const char *request_id,
                           const char *token, const char *payload_json) {
    kz_auth_user user;
    char query[121] = {0};
    char topic[KZ_QUESTION_TOPIC_MAX + 1U] = {0};
    char difficulty[8] = {0};
    int include_inactive = 1;
    int limit = KZ_QUESTION_LIST_DEFAULT_LIMIT;
    int offset = 0;
    int parsed = 0;
    sqlite3 *db;
    sqlite3_stmt *statement = NULL;
    char *response = NULL;
    size_t used = 0U;
    int emitted = 0;
    int step_result;
    bool first = true;
    bool has_more = false;
    bool build_failed = false;
    const char *sql =
        "SELECT id, content, topic, difficulty, correct_option_id, is_active, explanation "
        "FROM questions "
        "WHERE (?1 = '' OR content LIKE '%' || ?1 || '%' COLLATE NOCASE) "
        "AND (?2 = '' OR topic = ?2) "
        "AND (?3 = '' OR difficulty = ?3) "
        "AND (?4 = 1 OR is_active = 1) "
        "ORDER BY id DESC LIMIT ?5 OFFSET ?6;";

    if (!require_admin(conn, request_id, token, &user)) {
        return;
    }
    (void)user;
    if (payload_json == NULL) {
        payload_json = "{}";
    }
    (void)find_json_string_member(payload_json, "query", query, sizeof(query));
    (void)find_json_string_member(payload_json, "topic", topic, sizeof(topic));
    if (find_json_string_member(payload_json, "difficulty", difficulty, sizeof(difficulty)) &&
        difficulty[0] != '\0' && !is_valid_difficulty(difficulty)) {
        send_error(conn->socket_fd, request_id, "BAD_REQUEST",
                   "difficulty must be easy, medium, or hard");
        return;
    }
    if (find_json_int_member(payload_json, "include_inactive", &parsed)) {
        if (parsed != 0 && parsed != 1) {
            send_error(conn->socket_fd, request_id, "BAD_REQUEST",
                       "include_inactive must be 0 or 1");
            return;
        }
        include_inactive = parsed;
    }
    if (find_json_int_member(payload_json, "limit", &parsed)) {
        if (parsed < 1 || parsed > KZ_QUESTION_LIST_MAX_LIMIT) {
            send_error(conn->socket_fd, request_id, "BAD_REQUEST", "limit must be between 1 and 20");
            return;
        }
        limit = parsed;
    }
    if (find_json_int_member(payload_json, "offset", &parsed)) {
        if (parsed < 0) {
            send_error(conn->socket_fd, request_id, "BAD_REQUEST", "offset must not be negative");
            return;
        }
        offset = parsed;
    }

    response = (char *)malloc(KZ_QUESTION_LIST_RESPONSE_BYTES);
    if (response == NULL ||
        !append_format(response, KZ_QUESTION_LIST_RESPONSE_BYTES, &used, "{\"questions\":[")) {
        free(response);
        send_error(conn->socket_fd, request_id, "INTERNAL_ERROR", "Out of memory");
        return;
    }

    db = kz_db_lock();
    if (db == NULL || sqlite3_prepare_v2(db, sql, -1, &statement, NULL) != SQLITE_OK) {
        kz_db_unlock();
        free(response);
        send_error(conn->socket_fd, request_id, "INTERNAL_ERROR", "Database error while listing questions");
        return;
    }
    (void)sqlite3_bind_text(statement, 1, query, -1, SQLITE_STATIC);
    (void)sqlite3_bind_text(statement, 2, topic, -1, SQLITE_STATIC);
    (void)sqlite3_bind_text(statement, 3, difficulty, -1, SQLITE_STATIC);
    (void)sqlite3_bind_int(statement, 4, include_inactive);
    (void)sqlite3_bind_int(statement, 5, limit + 1);
    (void)sqlite3_bind_int(statement, 6, offset);

    while ((step_result = sqlite3_step(statement)) == SQLITE_ROW) {
        if (emitted >= limit) {
            has_more = true;
            break;
        }
        if (!append_question_json(db, statement, response, KZ_QUESTION_LIST_RESPONSE_BYTES,
                                  &used, first)) {
            build_failed = true;
            break;
        }
        emitted++;
        first = false;
    }
    if (step_result != SQLITE_DONE && step_result != SQLITE_ROW) {
        build_failed = true;
    }
    sqlite3_finalize(statement);
    kz_db_unlock();

    if (build_failed ||
        !append_format(response, KZ_QUESTION_LIST_RESPONSE_BYTES, &used,
                       "],\"limit\":%d,\"offset\":%d,\"has_more\":%s}",
                       limit, offset, has_more ? "true" : "false")) {
        free(response);
        send_error(conn->socket_fd, request_id, "INTERNAL_ERROR",
                   "Question list is too large; reduce the requested limit");
        return;
    }
    (void)send_ok_data(conn->socket_fd, request_id, response);
    free(response);
}

void handle_create_question(kz_connection *conn, const char *request_id,
                            const char *token, const char *payload_json) {
    kz_auth_user user;
    kz_question_input input;
    const char *validation_error = NULL;
    sqlite3 *db;
    int question_id = 0;
    char entity_id[32];
    char data_json[96];

    if (!require_admin(conn, request_id, token, &user)) {
        return;
    }
    if (!parse_question_input(payload_json, &input, &validation_error)) {
        send_error(conn->socket_fd, request_id, "BAD_REQUEST", validation_error);
        return;
    }
    db = kz_db_lock();
    if (db == NULL) {
        kz_db_unlock();
        send_error(conn->socket_fd, request_id, "INTERNAL_ERROR", "Database error");
        return;
    }
    if (!execute_sql(db, "BEGIN IMMEDIATE;") ||
        !insert_question(db, &input, &question_id) || !execute_sql(db, "COMMIT;")) {
        (void)execute_sql(db, "ROLLBACK;");
        kz_db_unlock();
        send_error(conn->socket_fd, request_id, "INTERNAL_ERROR", "Could not create question");
        return;
    }
    (void)snprintf(entity_id, sizeof(entity_id), "%d", question_id);
    kz_log_event_db(db, user.id, "QUESTION_CREATED", "question", entity_id, "{}");
    kz_db_unlock();

    (void)snprintf(data_json, sizeof(data_json), "{\"question_id\":%d,\"created\":true}", question_id);
    (void)send_ok_data(conn->socket_fd, request_id, data_json);
}

void handle_update_question(kz_connection *conn, const char *request_id,
                            const char *token, const char *payload_json) {
    kz_auth_user user;
    kz_question_input input;
    const char *validation_error = NULL;
    char question_json[KZ_QUESTION_UPDATE_JSON_MAX];
    bool has_question;
    int question_id = 0;
    int is_active = 0;
    bool has_is_active;
    sqlite3 *db;
    char entity_id[32];
    char data_json[96];

    if (!require_admin(conn, request_id, token, &user)) {
        return;
    }
    if (!find_json_int_member(payload_json, "id", &question_id) || question_id <= 0) {
        send_error(conn->socket_fd, request_id, "BAD_REQUEST", "id must be a positive integer");
        return;
    }
    has_question = find_json_object_member(payload_json, "question", question_json,
                                           sizeof(question_json));
    has_is_active = find_json_int_member(payload_json, "is_active", &is_active);
    if (has_is_active && is_active != 0 && is_active != 1) {
        send_error(conn->socket_fd, request_id, "BAD_REQUEST", "is_active must be 0 or 1");
        return;
    }
    if (!has_question && !has_is_active) {
        send_error(conn->socket_fd, request_id, "BAD_REQUEST",
                   "provide a replacement question and/or is_active");
        return;
    }
    if (has_question && !parse_question_input(question_json, &input, &validation_error)) {
        send_error(conn->socket_fd, request_id, "BAD_REQUEST", validation_error);
        return;
    }

    db = kz_db_lock();
    if (db == NULL) {
        kz_db_unlock();
        send_error(conn->socket_fd, request_id, "INTERNAL_ERROR", "Database error");
        return;
    }
    if (!question_exists(db, question_id)) {
        kz_db_unlock();
        send_error(conn->socket_fd, request_id, "NOT_FOUND", "Question not found");
        return;
    }
    if (!execute_sql(db, "BEGIN IMMEDIATE;") ||
        (has_question && !replace_question(db, question_id, &input)) ||
        (has_is_active && !update_question_active_state(db, question_id, is_active)) ||
        !execute_sql(db, "COMMIT;")) {
        (void)execute_sql(db, "ROLLBACK;");
        kz_db_unlock();
        send_error(conn->socket_fd, request_id, "INTERNAL_ERROR", "Could not update question");
        return;
    }
    (void)snprintf(entity_id, sizeof(entity_id), "%d", question_id);
    kz_log_event_db(db, user.id, "QUESTION_UPDATED", "question", entity_id, "{}");
    kz_db_unlock();

    (void)snprintf(data_json, sizeof(data_json), "{\"question_id\":%d,\"updated\":true}", question_id);
    (void)send_ok_data(conn->socket_fd, request_id, data_json);
}

void handle_import_questions(kz_connection *conn, const char *request_id,
                             const char *token, const char *payload_json) {
    kz_auth_user user;
    char *array_json = NULL;
    char *object_json = NULL;
    const char *cursor;
    kz_question_input *inputs = NULL;
    size_t count = 0U;
    bool has_object = false;
    const char *validation_error = NULL;
    sqlite3 *db;
    char detail_json[96];
    char data_json[96];

    if (!require_admin(conn, request_id, token, &user)) {
        return;
    }
    array_json = (char *)malloc(KZ_MAX_NDJSON_LINE_BYTES);
    object_json = (char *)malloc(KZ_MAX_NDJSON_LINE_BYTES);
    inputs = (kz_question_input *)calloc(KZ_IMPORT_MAX_QUESTIONS, sizeof(*inputs));
    if (array_json == NULL || object_json == NULL || inputs == NULL) {
        free(array_json);
        free(object_json);
        free(inputs);
        send_error(conn->socket_fd, request_id, "INTERNAL_ERROR", "Out of memory");
        return;
    }
    if (!find_json_array_member(payload_json, "questions", array_json,
                                KZ_MAX_NDJSON_LINE_BYTES)) {
        free(array_json);
        free(object_json);
        free(inputs);
        send_error(conn->socket_fd, request_id, "BAD_REQUEST", "questions must be a JSON array");
        return;
    }

    cursor = array_json;
    while (true) {
        if (!next_array_object(&cursor, object_json, KZ_MAX_NDJSON_LINE_BYTES, &has_object)) {
            free(array_json);
            free(object_json);
            free(inputs);
            send_error(conn->socket_fd, request_id, "BAD_REQUEST",
                       "questions must contain only JSON objects");
            return;
        }
        if (!has_object) {
            break;
        }
        if (count >= KZ_IMPORT_MAX_QUESTIONS) {
            free(array_json);
            free(object_json);
            free(inputs);
            send_error(conn->socket_fd, request_id, "BAD_REQUEST",
                       "questions may contain at most 100 items per request");
            return;
        }
        if (!parse_question_input(object_json, &inputs[count], &validation_error)) {
            char message[512];
            (void)snprintf(message, sizeof(message), "Question %u: %s",
                           (unsigned int)(count + 1U), validation_error);
            free(array_json);
            free(object_json);
            free(inputs);
            send_error(conn->socket_fd, request_id, "BAD_REQUEST", message);
            return;
        }
        count++;
    }
    free(array_json);
    free(object_json);
    if (count == 0U) {
        free(inputs);
        send_error(conn->socket_fd, request_id, "BAD_REQUEST", "questions must not be empty");
        return;
    }

    db = kz_db_lock();
    if (db == NULL) {
        kz_db_unlock();
        free(inputs);
        send_error(conn->socket_fd, request_id, "INTERNAL_ERROR", "Database error");
        return;
    }
    if (!execute_sql(db, "BEGIN IMMEDIATE;")) {
        kz_db_unlock();
        free(inputs);
        send_error(conn->socket_fd, request_id, "INTERNAL_ERROR", "Could not begin import");
        return;
    }
    for (size_t index = 0U; index < count; index++) {
        if (!insert_question(db, &inputs[index], NULL)) {
            (void)execute_sql(db, "ROLLBACK;");
            kz_db_unlock();
            free(inputs);
            send_error(conn->socket_fd, request_id, "INTERNAL_ERROR",
                       "Could not import questions; no changes were saved");
            return;
        }
    }
    if (!execute_sql(db, "COMMIT;")) {
        (void)execute_sql(db, "ROLLBACK;");
        kz_db_unlock();
        free(inputs);
        send_error(conn->socket_fd, request_id, "INTERNAL_ERROR",
                   "Could not finish import; no changes were saved");
        return;
    }
    (void)snprintf(detail_json, sizeof(detail_json), "{\"count\":%u}", (unsigned int)count);
    kz_log_event_db(db, user.id, "QUESTIONS_IMPORTED", "question_bank", "batch", detail_json);
    kz_db_unlock();
    free(inputs);

    (void)snprintf(data_json, sizeof(data_json), "{\"imported\":%u}", (unsigned int)count);
    (void)send_ok_data(conn->socket_fd, request_id, data_json);
}
