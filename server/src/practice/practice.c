#include "practice.h"
#include "auth.h"
#include "db.h"
#include "log.h"

#include <stdarg.h>
#include <stdbool.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#define KZ_PRACTICE_TOPIC_BYTES 65
#define KZ_PRACTICE_DIFFICULTY_BYTES 16
#define KZ_PRACTICE_MAX_QUESTIONS 20
#define KZ_PRACTICE_MIN_DURATION 60
#define KZ_PRACTICE_MAX_DURATION 7200

static bool valid_difficulty(const char *value) {
    return value != NULL && (strcmp(value, "easy") == 0 ||
        strcmp(value, "medium") == 0 || strcmp(value, "hard") == 0);
}

static bool append_format(char *buffer, size_t capacity, size_t *used,
                          const char *format, ...) {
    va_list arguments;
    int written;
    if (buffer == NULL || used == NULL || *used >= capacity) return false;
    va_start(arguments, format);
    written = vsnprintf(buffer + *used, capacity - *used, format, arguments);
    va_end(arguments);
    if (written < 0 || (size_t)written >= capacity - *used) return false;
    *used += (size_t)written;
    return true;
}

static bool execute_sql(sqlite3 *db, const char *sql) {
    char *error = NULL;
    int rc = sqlite3_exec(db, sql, NULL, NULL, &error);
    sqlite3_free(error);
    return rc == SQLITE_OK;
}

static bool load_practice_owner(sqlite3 *db, int attempt_id, int user_id,
                                char *state, size_t state_size, bool *expired) {
    sqlite3_stmt *statement = NULL;
    const char *sql = "SELECT state, ended_at <= datetime('now') FROM practice_sessions "
                      "WHERE id = ? AND user_id = ?;";
    bool found = false;
    if (sqlite3_prepare_v2(db, sql, -1, &statement, NULL) != SQLITE_OK) return false;
    (void)sqlite3_bind_int(statement, 1, attempt_id);
    (void)sqlite3_bind_int(statement, 2, user_id);
    if (sqlite3_step(statement) == SQLITE_ROW) {
        const char *stored = (const char *)sqlite3_column_text(statement, 0);
        if (stored != NULL && strlen(stored) + 1U <= state_size) {
            strcpy(state, stored);
            *expired = sqlite3_column_int(statement, 1) != 0;
            found = true;
        }
    }
    sqlite3_finalize(statement);
    return found;
}

static bool snapshot_questions(sqlite3 *db, int attempt_id, const char *topic,
                               const char *difficulty, int question_count) {
    sqlite3_stmt *questions = NULL;
    sqlite3_stmt *insert_question = NULL;
    sqlite3_stmt *options = NULL;
    sqlite3_stmt *insert_option = NULL;
    const char *question_sql =
        "SELECT q.id, q.content, correct.position, q.topic, q.difficulty FROM questions q "
        "JOIN question_options correct ON correct.id = q.correct_option_id "
        "WHERE q.is_active = 1 AND q.topic = ? AND q.difficulty = ? "
        "ORDER BY RANDOM() LIMIT ?;";
    bool ok = false;

    if (sqlite3_prepare_v2(db, question_sql, -1, &questions, NULL) != SQLITE_OK ||
        sqlite3_prepare_v2(db, "INSERT INTO practice_session_questions "
        "(session_id, question_id, position, content_snapshot, correct_option_position, "
        " topic_snapshot, difficulty_snapshot) "
        "VALUES (?, ?, ?, ?, ?, ?, ?);", -1, &insert_question, NULL) != SQLITE_OK ||
        sqlite3_prepare_v2(db, "SELECT position, label, content FROM question_options "
        "WHERE question_id = ? ORDER BY position;", -1, &options, NULL) != SQLITE_OK ||
        sqlite3_prepare_v2(db, "INSERT INTO practice_session_options "
        "(session_id, question_id, position, label, content_snapshot) VALUES (?, ?, ?, ?, ?);",
        -1, &insert_option, NULL) != SQLITE_OK) {
        goto done;
    }
    (void)sqlite3_bind_text(questions, 1, topic, -1, SQLITE_STATIC);
    (void)sqlite3_bind_text(questions, 2, difficulty, -1, SQLITE_STATIC);
    (void)sqlite3_bind_int(questions, 3, question_count);
    for (int position = 1; sqlite3_step(questions) == SQLITE_ROW; position++) {
        int question_id = sqlite3_column_int(questions, 0);
        const char *content = (const char *)sqlite3_column_text(questions, 1);
        int correct_position = sqlite3_column_int(questions, 2);
            const char *question_topic = (const char *)sqlite3_column_text(questions, 3);
            const char *question_difficulty = (const char *)sqlite3_column_text(questions, 4);
        int option_count = 0;
        (void)sqlite3_bind_int(insert_question, 1, attempt_id);
        (void)sqlite3_bind_int(insert_question, 2, question_id);
        (void)sqlite3_bind_int(insert_question, 3, position);
        (void)sqlite3_bind_text(insert_question, 4, content ? content : "", -1, SQLITE_STATIC);
        (void)sqlite3_bind_int(insert_question, 5, correct_position);
            (void)sqlite3_bind_text(insert_question, 6,
                                    question_topic ? question_topic : "", -1, SQLITE_STATIC);
            (void)sqlite3_bind_text(insert_question, 7,
                                    question_difficulty ? question_difficulty : "", -1, SQLITE_STATIC);
        if (sqlite3_step(insert_question) != SQLITE_DONE) goto done;
        (void)sqlite3_reset(insert_question); (void)sqlite3_clear_bindings(insert_question);
        (void)sqlite3_bind_int(options, 1, question_id);
        while (sqlite3_step(options) == SQLITE_ROW) {
            (void)sqlite3_bind_int(insert_option, 1, attempt_id);
            (void)sqlite3_bind_int(insert_option, 2, question_id);
            (void)sqlite3_bind_int(insert_option, 3, sqlite3_column_int(options, 0));
            (void)sqlite3_bind_text(insert_option, 4, (const char *)sqlite3_column_text(options, 1), -1, SQLITE_STATIC);
            (void)sqlite3_bind_text(insert_option, 5, (const char *)sqlite3_column_text(options, 2), -1, SQLITE_STATIC);
            if (sqlite3_step(insert_option) != SQLITE_DONE) goto done;
            (void)sqlite3_reset(insert_option); (void)sqlite3_clear_bindings(insert_option);
            option_count++;
        }
        (void)sqlite3_reset(options); (void)sqlite3_clear_bindings(options);
        if (option_count != 4) goto done;
    }
    ok = sqlite3_changes(db) >= 0;
done:
    sqlite3_finalize(questions); sqlite3_finalize(insert_question);
    sqlite3_finalize(options); sqlite3_finalize(insert_option);
    return ok;
}

static char *build_practice_json(sqlite3 *db, int attempt_id) {
    sqlite3_stmt *session = NULL;
    sqlite3_stmt *questions = NULL;
    sqlite3_stmt *options = NULL;
    sqlite3_stmt *answers = NULL;
    char *result = (char *)malloc(KZ_MAX_NDJSON_LINE_BYTES);
    size_t used = 0U;
    bool first_question = true;
    bool failed = result == NULL;
    char ended_at[32] = {0};
    char escaped_ended_at[64];
    if (!failed && sqlite3_prepare_v2(db,
        "SELECT ended_at FROM practice_sessions WHERE id = ?;", -1, &session, NULL) != SQLITE_OK) failed = true;
    if (!failed) {
        (void)sqlite3_bind_int(session, 1, attempt_id);
        if (sqlite3_step(session) != SQLITE_ROW || sqlite3_column_text(session, 0) == NULL) {
            failed = true;
        } else {
            (void)snprintf(ended_at, sizeof(ended_at), "%s",
                           (const char *)sqlite3_column_text(session, 0));
        }
    }
    sqlite3_finalize(session);
    session = NULL;
    json_escape(ended_at, escaped_ended_at, sizeof(escaped_ended_at));
    if (!failed && !append_format(result, KZ_MAX_NDJSON_LINE_BYTES, &used,
        "{\"attempt_id\":%d,\"ended_at\":\"%s\",\"questions\":[",
        attempt_id, escaped_ended_at)) failed = true;
    if (!failed && sqlite3_prepare_v2(db, "SELECT question_id, position, content_snapshot FROM "
        "practice_session_questions WHERE session_id = ? ORDER BY position;", -1, &questions, NULL) != SQLITE_OK) failed = true;
    if (!failed && sqlite3_prepare_v2(db, "SELECT position, label, content_snapshot FROM "
        "practice_session_options WHERE session_id = ? AND question_id = ? ORDER BY position;",
        -1, &options, NULL) != SQLITE_OK) failed = true;
    if (!failed && sqlite3_prepare_v2(db,
        "SELECT selected_option_position FROM practice_answers "
        "WHERE session_id = ? AND question_id = ?;", -1, &answers, NULL) != SQLITE_OK) failed = true;
    if (!failed) {
        (void)sqlite3_bind_int(questions, 1, attempt_id);
        while (sqlite3_step(questions) == SQLITE_ROW && !failed) {
            int question_id = sqlite3_column_int(questions, 0);
            const char *content = (const char *)sqlite3_column_text(questions, 2);
            int selected_option_position = 0;
            char escaped[2401]; bool first_option = true;
            json_escape(content ? content : "", escaped, sizeof(escaped));
            if (!append_format(result, KZ_MAX_NDJSON_LINE_BYTES, &used,
                "%s{\"id\":%d,\"position\":%d,\"content\":\"%s\",\"options\":[",
                first_question ? "" : ",", question_id, sqlite3_column_int(questions, 1), escaped)) { failed = true; break; }
            (void)sqlite3_bind_int(options, 1, attempt_id); (void)sqlite3_bind_int(options, 2, question_id);
            while (sqlite3_step(options) == SQLITE_ROW) {
                char label[32], option[801];
                json_escape((const char *)sqlite3_column_text(options, 1), label, sizeof(label));
                json_escape((const char *)sqlite3_column_text(options, 2), option, sizeof(option));
                if (!append_format(result, KZ_MAX_NDJSON_LINE_BYTES, &used,
                    "%s{\"position\":%d,\"label\":\"%s\",\"content\":\"%s\"}",
                    first_option ? "" : ",", sqlite3_column_int(options, 0), label, option)) { failed = true; break; }
                first_option = false;
            }
            (void)sqlite3_reset(options); (void)sqlite3_clear_bindings(options);
            (void)sqlite3_bind_int(answers, 1, attempt_id);
            (void)sqlite3_bind_int(answers, 2, question_id);
            if (sqlite3_step(answers) == SQLITE_ROW) {
                selected_option_position = sqlite3_column_int(answers, 0);
            }
            (void)sqlite3_reset(answers); (void)sqlite3_clear_bindings(answers);
            if (!failed && selected_option_position > 0 &&
                !append_format(result, KZ_MAX_NDJSON_LINE_BYTES, &used,
                               "],\"selected_option_position\":%d}", selected_option_position)) failed = true;
            if (!failed && selected_option_position == 0 &&
                !append_format(result, KZ_MAX_NDJSON_LINE_BYTES, &used,
                               "],\"selected_option_position\":null}")) failed = true;
            first_question = false;
        }
    }
    sqlite3_finalize(session); sqlite3_finalize(questions); sqlite3_finalize(options); sqlite3_finalize(answers);
    if (failed || !append_format(result, KZ_MAX_NDJSON_LINE_BYTES, &used, "]}")) { free(result); return NULL; }
    return result;
}

void handle_start_practice(kz_connection *conn, const char *request_id,
                           const char *token, const char *payload_json) {
    kz_auth_user user; const char *code = NULL; const char *message = NULL;
    char topic[KZ_PRACTICE_TOPIC_BYTES], difficulty[KZ_PRACTICE_DIFFICULTY_BYTES];
    int question_count = 0, duration = 0, available = 0, attempt_id;
    sqlite3 *db; sqlite3_stmt *statement = NULL; char *data;
    if (!require_session(token, &user, &code, &message)) { send_error(conn->socket_fd, request_id, code, message); return; }
    if (!find_json_string_member(payload_json, "topic", topic, sizeof(topic)) || topic[0] == '\0' ||
        !find_json_string_member(payload_json, "difficulty", difficulty, sizeof(difficulty)) ||
        !valid_difficulty(difficulty) || !find_json_int_member(payload_json, "question_count", &question_count) ||
        !find_json_int_member(payload_json, "duration_seconds", &duration) || question_count < 1 ||
        question_count > KZ_PRACTICE_MAX_QUESTIONS || duration < KZ_PRACTICE_MIN_DURATION || duration > KZ_PRACTICE_MAX_DURATION) {
        send_error(conn->socket_fd, request_id, "BAD_REQUEST", "Invalid practice configuration"); return;
    }
    db = kz_db_lock();
    if (db == NULL) { kz_db_unlock(); send_error(conn->socket_fd, request_id, "INTERNAL_ERROR", "Database error"); return; }
    if (!execute_sql(db, "BEGIN IMMEDIATE;")) { kz_db_unlock(); send_error(conn->socket_fd, request_id, "INTERNAL_ERROR", "Could not start practice"); return; }
    if (sqlite3_prepare_v2(db, "SELECT COUNT(*) FROM questions WHERE is_active = 1 AND topic = ? AND difficulty = ?;", -1, &statement, NULL) != SQLITE_OK) goto internal_error;
    (void)sqlite3_bind_text(statement, 1, topic, -1, SQLITE_STATIC); (void)sqlite3_bind_text(statement, 2, difficulty, -1, SQLITE_STATIC);
    if (sqlite3_step(statement) != SQLITE_ROW) goto internal_error;
    available = sqlite3_column_int(statement, 0); sqlite3_finalize(statement); statement = NULL;
    if (available < question_count) { (void)execute_sql(db, "ROLLBACK;"); kz_db_unlock(); send_error(conn->socket_fd, request_id, "CONFLICT", "Not enough active questions for practice"); return; }
    if (sqlite3_prepare_v2(db, "INSERT INTO practice_sessions(user_id, topic, difficulty, question_count, duration_seconds, ended_at) VALUES (?, ?, ?, ?, ?, datetime('now', '+' || ? || ' seconds'));", -1, &statement, NULL) != SQLITE_OK) goto internal_error;
    (void)sqlite3_bind_int(statement, 1, user.id); (void)sqlite3_bind_text(statement, 2, topic, -1, SQLITE_STATIC); (void)sqlite3_bind_text(statement, 3, difficulty, -1, SQLITE_STATIC); (void)sqlite3_bind_int(statement, 4, question_count); (void)sqlite3_bind_int(statement, 5, duration); (void)sqlite3_bind_int(statement, 6, duration);
    if (sqlite3_step(statement) != SQLITE_DONE) goto internal_error;
    sqlite3_finalize(statement); statement = NULL; attempt_id = (int)sqlite3_last_insert_rowid(db);
    if (!snapshot_questions(db, attempt_id, topic, difficulty, question_count) || !execute_sql(db, "COMMIT;")) goto internal_error;
    data = build_practice_json(db, attempt_id);
    if (data == NULL) { kz_db_unlock(); send_error(conn->socket_fd, request_id, "INTERNAL_ERROR", "Could not build practice response"); return; }
    kz_log_event_db(db, user.id, "PRACTICE_STARTED", "practice_session", "started", "{}"); kz_db_unlock();
    (void)send_ok_data(conn->socket_fd, request_id, data); free(data); return;
internal_error:
    sqlite3_finalize(statement); (void)execute_sql(db, "ROLLBACK;"); kz_db_unlock();
    send_error(conn->socket_fd, request_id, "INTERNAL_ERROR", "Could not start practice");
}

void handle_save_practice_answer(kz_connection *conn, const char *request_id,
                                 const char *token, const char *payload_json) {
    kz_auth_user user; const char *code = NULL; const char *message = NULL; char state[20]; bool expired = false;
    int attempt_id = 0, question_id = 0, selected = 0; sqlite3 *db; sqlite3_stmt *statement = NULL;
    if (!require_session(token, &user, &code, &message)) { send_error(conn->socket_fd, request_id, code, message); return; }
    if (!find_json_int_member(payload_json, "attempt_id", &attempt_id) || !find_json_int_member(payload_json, "question_id", &question_id) || !find_json_int_member(payload_json, "selected_option_position", &selected) || attempt_id <= 0 || question_id <= 0 || selected < 1 || selected > 4) { send_error(conn->socket_fd, request_id, "BAD_REQUEST", "Invalid practice answer payload"); return; }
    db = kz_db_lock(); if (db == NULL) { kz_db_unlock(); send_error(conn->socket_fd, request_id, "INTERNAL_ERROR", "Database error"); return; }
    if (!load_practice_owner(db, attempt_id, user.id, state, sizeof(state), &expired)) { kz_db_unlock(); send_error(conn->socket_fd, request_id, "NOT_FOUND", "Practice attempt not found"); return; }
    if (strcmp(state, "IN_PROGRESS") != 0 || expired) { kz_db_unlock(); send_error(conn->socket_fd, request_id, "CONFLICT", "Practice attempt is no longer active"); return; }
    if (sqlite3_prepare_v2(db, "INSERT INTO practice_answers(session_id, question_id, selected_option_position) SELECT ?, ?, ? WHERE EXISTS (SELECT 1 FROM practice_session_options WHERE session_id = ? AND question_id = ? AND position = ?) ON CONFLICT(session_id, question_id) DO UPDATE SET selected_option_position = excluded.selected_option_position, updated_at = CURRENT_TIMESTAMP;", -1, &statement, NULL) != SQLITE_OK) goto error;
    (void)sqlite3_bind_int(statement, 1, attempt_id); (void)sqlite3_bind_int(statement, 2, question_id); (void)sqlite3_bind_int(statement, 3, selected); (void)sqlite3_bind_int(statement, 4, attempt_id); (void)sqlite3_bind_int(statement, 5, question_id); (void)sqlite3_bind_int(statement, 6, selected);
    if (sqlite3_step(statement) != SQLITE_DONE || sqlite3_changes(db) != 1) goto error;
    sqlite3_finalize(statement); kz_db_unlock(); (void)send_ok_data(conn->socket_fd, request_id, "{\"saved\":true}"); return;
error:
    sqlite3_finalize(statement); kz_db_unlock(); send_error(conn->socket_fd, request_id, "BAD_REQUEST", "Question or option is not in this practice attempt");
}

void handle_submit_practice(kz_connection *conn, const char *request_id,
                            const char *token, const char *payload_json) {
    kz_auth_user user; const char *code = NULL; const char *message = NULL; char state[20]; bool expired = false;
    int attempt_id = 0, correct = 0, total = 0; double score = 0.0; sqlite3 *db; sqlite3_stmt *statement = NULL; char data[192];
    if (!require_session(token, &user, &code, &message)) { send_error(conn->socket_fd, request_id, code, message); return; }
    if (!find_json_int_member(payload_json, "attempt_id", &attempt_id) || attempt_id <= 0) { send_error(conn->socket_fd, request_id, "BAD_REQUEST", "attempt_id must be positive"); return; }
    db = kz_db_lock(); if (db == NULL) { kz_db_unlock(); send_error(conn->socket_fd, request_id, "INTERNAL_ERROR", "Database error"); return; }
    if (!load_practice_owner(db, attempt_id, user.id, state, sizeof(state), &expired)) { kz_db_unlock(); send_error(conn->socket_fd, request_id, "NOT_FOUND", "Practice attempt not found"); return; }
    if (strcmp(state, "IN_PROGRESS") == 0) {
        if (!execute_sql(db, "BEGIN IMMEDIATE;")) goto internal;
        if (sqlite3_prepare_v2(db, "SELECT COUNT(*), COALESCE(SUM(CASE WHEN a.selected_option_position = q.correct_option_position THEN 1 ELSE 0 END), 0) FROM practice_session_questions q LEFT JOIN practice_answers a ON a.session_id = q.session_id AND a.question_id = q.question_id WHERE q.session_id = ?;", -1, &statement, NULL) != SQLITE_OK) goto rollback;
        (void)sqlite3_bind_int(statement, 1, attempt_id); if (sqlite3_step(statement) != SQLITE_ROW) goto rollback;
        total = sqlite3_column_int(statement, 0); correct = sqlite3_column_int(statement, 1); sqlite3_finalize(statement); statement = NULL; score = total ? (double)correct * 10.0 / (double)total : 0.0;
        if (sqlite3_prepare_v2(db, "UPDATE practice_sessions SET state = ?, submitted_at = datetime('now'), score = ?, correct_count = ? WHERE id = ?;", -1, &statement, NULL) != SQLITE_OK) goto rollback;
        (void)sqlite3_bind_text(statement, 1, expired ? "AUTO_SUBMITTED" : "SUBMITTED", -1, SQLITE_STATIC); (void)sqlite3_bind_double(statement, 2, score); (void)sqlite3_bind_int(statement, 3, correct); (void)sqlite3_bind_int(statement, 4, attempt_id); if (sqlite3_step(statement) != SQLITE_DONE) goto rollback;
        sqlite3_finalize(statement); statement = NULL;
        if (sqlite3_prepare_v2(db, "INSERT INTO practice_attempts(user_id, score, correct_count, total, duration_seconds, configuration_json) SELECT user_id, score, correct_count, question_count, duration_seconds, '{\"source\":\"practice_session\"}' FROM practice_sessions WHERE id = ?;", -1, &statement, NULL) != SQLITE_OK) goto rollback;
        (void)sqlite3_bind_int(statement, 1, attempt_id); if (sqlite3_step(statement) != SQLITE_DONE || !execute_sql(db, "COMMIT;")) goto rollback;
        sqlite3_finalize(statement); statement = NULL; state[0] = '\0';
    }
    if (sqlite3_prepare_v2(db, "SELECT state, correct_count, question_count, score FROM practice_sessions WHERE id = ?;", -1, &statement, NULL) != SQLITE_OK) goto internal;
    (void)sqlite3_bind_int(statement, 1, attempt_id); if (sqlite3_step(statement) != SQLITE_ROW) goto internal;
    (void)snprintf(data, sizeof(data), "{\"attempt_id\":%d,\"state\":\"%s\",\"correct_count\":%d,\"total\":%d,\"score\":%.2f}", attempt_id, (const char *)sqlite3_column_text(statement, 0), sqlite3_column_int(statement, 1), sqlite3_column_int(statement, 2), sqlite3_column_double(statement, 3));
    sqlite3_finalize(statement); kz_log_event_db(db, user.id, "PRACTICE_SUBMITTED", "practice_session", "submitted", "{}"); kz_db_unlock(); (void)send_ok_data(conn->socket_fd, request_id, data); return;
rollback:
    sqlite3_finalize(statement); (void)execute_sql(db, "ROLLBACK;"); kz_db_unlock(); send_error(conn->socket_fd, request_id, "INTERNAL_ERROR", "Could not submit practice"); return;
internal:
    sqlite3_finalize(statement); kz_db_unlock(); send_error(conn->socket_fd, request_id, "INTERNAL_ERROR", "Could not read practice result");
}
