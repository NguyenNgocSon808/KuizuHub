#include "room.h"
#include "auth.h"
#include "db.h"
#include "log.h"

#include <ctype.h>
#include <stdbool.h>
#include <stddef.h>
#include <sqlite3.h>
#include <stdarg.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#define KZ_MAX_ROOM_RULES 16
#define KZ_ROOM_NAME_BYTES 101
#define KZ_TOPIC_BYTES 65
#define KZ_DIFFICULTY_BYTES 16
#define KZ_RULE_JSON_BYTES 256
#define KZ_MIN_ROOM_DURATION_SECONDS 60
#define KZ_MAX_ROOM_DURATION_SECONDS 7200
#define KZ_MAX_RULE_QUESTION_COUNT 50

typedef struct {
    char topic[KZ_TOPIC_BYTES];
    char difficulty[KZ_DIFFICULTY_BYTES];
    int quantity;
} kz_room_rule;

static bool has_non_whitespace(const char *value) {
    if (value == NULL) {
        return false;
    }
    while (*value != '\0') {
        if (!isspace((unsigned char)*value)) {
            return true;
        }
        value++;
    }
    return false;
}

static bool is_valid_difficulty(const char *difficulty) {
    return difficulty != NULL &&
           (strcmp(difficulty, "easy") == 0 ||
            strcmp(difficulty, "medium") == 0 ||
            strcmp(difficulty, "hard") == 0);
}

static bool parse_room_rules(const char *payload_json, kz_room_rule *rules,
                             size_t *out_rule_count) {
    char serialized_rules[KZ_MAX_ROOM_RULES][KZ_RULE_JSON_BYTES];
    size_t rule_count = 0U;

    if (payload_json == NULL || rules == NULL || out_rule_count == NULL ||
        !find_json_object_array_member(payload_json, "rules",
                                       &serialized_rules[0][0],
                                       sizeof(serialized_rules[0]),
                                       KZ_MAX_ROOM_RULES, &rule_count)) {
        return false;
    }
    for (size_t index = 0U; index < rule_count; index++) {
        if (!find_json_string_member(serialized_rules[index], "topic",
                                     rules[index].topic, sizeof(rules[index].topic)) ||
            !find_json_string_member(serialized_rules[index], "difficulty",
                                     rules[index].difficulty, sizeof(rules[index].difficulty)) ||
            !find_json_int_member(serialized_rules[index], "quantity",
                                  &rules[index].quantity)) {
            return false;
        }
    }
    *out_rule_count = rule_count;
    return true;
}

static bool validate_room_input(const char *name, int duration_seconds,
                                const kz_room_rule *rules, size_t rule_count,
                                const char **out_message) {
    if (out_message != NULL) {
        *out_message = "Invalid room payload";
    }
    if (!has_non_whitespace(name)) {
        if (out_message != NULL) *out_message = "name must not be blank";
        return false;
    }
    if (duration_seconds < KZ_MIN_ROOM_DURATION_SECONDS ||
        duration_seconds > KZ_MAX_ROOM_DURATION_SECONDS) {
        if (out_message != NULL) *out_message = "duration_seconds must be between 60 and 7200";
        return false;
    }
    if (rules == NULL || rule_count == 0U || rule_count > KZ_MAX_ROOM_RULES) {
        if (out_message != NULL) *out_message = "rules must contain 1 to 16 items";
        return false;
    }
    for (size_t index = 0U; index < rule_count; index++) {
        if (!has_non_whitespace(rules[index].topic)) {
            if (out_message != NULL) *out_message = "rule topic must not be blank";
            return false;
        }
        if (!is_valid_difficulty(rules[index].difficulty)) {
            if (out_message != NULL) *out_message = "rule difficulty must be easy, medium, or hard";
            return false;
        }
        if (rules[index].quantity < 1 || rules[index].quantity > KZ_MAX_RULE_QUESTION_COUNT) {
            if (out_message != NULL) *out_message = "rule quantity must be between 1 and 50";
            return false;
        }
        for (size_t previous = 0U; previous < index; previous++) {
            if (strcmp(rules[index].topic, rules[previous].topic) == 0 &&
                strcmp(rules[index].difficulty, rules[previous].difficulty) == 0) {
                if (out_message != NULL) *out_message = "rules must not repeat topic and difficulty";
                return false;
            }
        }
    }
    return true;
}

static bool count_active_questions(sqlite3 *db, const kz_room_rule *rule,
                                   int *out_count) {
    sqlite3_stmt *statement = NULL;
    const char *sql =
        "SELECT COUNT(*) FROM questions "
        "WHERE is_active = 1 AND topic = ? AND difficulty = ?;";
    bool ok = false;

    if (db == NULL || rule == NULL || out_count == NULL ||
        sqlite3_prepare_v2(db, sql, -1, &statement, NULL) != SQLITE_OK) {
        return false;
    }
    (void)sqlite3_bind_text(statement, 1, rule->topic, -1, SQLITE_STATIC);
    (void)sqlite3_bind_text(statement, 2, rule->difficulty, -1, SQLITE_STATIC);
    if (sqlite3_step(statement) == SQLITE_ROW) {
        *out_count = sqlite3_column_int(statement, 0);
        ok = true;
    }
    sqlite3_finalize(statement);
    return ok;
}

static bool execute_sql(sqlite3 *db, const char *sql) {
    char *error_message = NULL;
    int rc;

    if (db == NULL || sql == NULL) {
        return false;
    }
    rc = sqlite3_exec(db, sql, NULL, NULL, &error_message);
    sqlite3_free(error_message);
    return rc == SQLITE_OK;
}

static bool append_room_json(char *buffer, size_t capacity, size_t *used,
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

static bool insert_room_and_rules(sqlite3 *db, int owner_id, const char *name,
                                  int duration_seconds, const kz_room_rule *rules,
                                  size_t rule_count, int *out_room_id) {
    sqlite3_stmt *room_statement = NULL;
    sqlite3_stmt *rule_statement = NULL;
    const char *room_sql =
        "INSERT INTO exam_rooms(owner_id, name, status, duration_seconds) "
        "VALUES (?, ?, 'WAITING', ?);";
    const char *rule_sql =
        "INSERT INTO room_question_rules(room_id, topic, difficulty, quantity) "
        "VALUES (?, ?, ?, ?);";
    bool ok = false;

    if (db == NULL || name == NULL || rules == NULL || out_room_id == NULL ||
        sqlite3_prepare_v2(db, room_sql, -1, &room_statement, NULL) != SQLITE_OK) {
        goto done;
    }
    (void)sqlite3_bind_int(room_statement, 1, owner_id);
    (void)sqlite3_bind_text(room_statement, 2, name, -1, SQLITE_STATIC);
    (void)sqlite3_bind_int(room_statement, 3, duration_seconds);
    if (sqlite3_step(room_statement) != SQLITE_DONE) {
        goto done;
    }
    *out_room_id = (int)sqlite3_last_insert_rowid(db);
    sqlite3_finalize(room_statement);
    room_statement = NULL;

    if (sqlite3_prepare_v2(db, rule_sql, -1, &rule_statement, NULL) != SQLITE_OK) {
        goto done;
    }
    for (size_t index = 0U; index < rule_count; index++) {
        (void)sqlite3_bind_int(rule_statement, 1, *out_room_id);
        (void)sqlite3_bind_text(rule_statement, 2, rules[index].topic, -1, SQLITE_STATIC);
        (void)sqlite3_bind_text(rule_statement, 3, rules[index].difficulty, -1, SQLITE_STATIC);
        (void)sqlite3_bind_int(rule_statement, 4, rules[index].quantity);
        if (sqlite3_step(rule_statement) != SQLITE_DONE) {
            goto done;
        }
        (void)sqlite3_reset(rule_statement);
        (void)sqlite3_clear_bindings(rule_statement);
    }
    ok = true;

done:
    sqlite3_finalize(room_statement);
    sqlite3_finalize(rule_statement);
    return ok;
}

void handle_create_room(kz_connection *conn, const char *request_id,
                        const char *token, const char *payload_json) {
    kz_auth_user user;
    const char *error_code = NULL;
    const char *error_message = NULL;
    char name[KZ_ROOM_NAME_BYTES];
    kz_room_rule rules[KZ_MAX_ROOM_RULES];
    size_t rule_count = 0U;
    int duration_seconds = 0;
    sqlite3 *db;
    int room_id = 0;
    char room_id_text[32];
    char escaped_name[KZ_ROOM_NAME_BYTES * 2U + 1U];
    char detail_json[256];
    char data_json[320];

    if (!require_session(token, &user, &error_code, &error_message)) {
        send_error(conn->socket_fd, request_id, error_code, error_message);
        return;
    }
    if (strcmp(user.role, "HOST") != 0 && strcmp(user.role, "ADMIN") != 0) {
        send_error(conn->socket_fd, request_id, "FORBIDDEN",
                   "Only HOST or ADMIN can create a room");
        return;
    }
    if (!find_json_string_member(payload_json, "name", name, sizeof(name)) ||
        !find_json_int_member(payload_json, "duration_seconds", &duration_seconds) ||
        !parse_room_rules(payload_json, rules, &rule_count)) {
        send_error(conn->socket_fd, request_id, "BAD_REQUEST",
                   "name, duration_seconds, and rules are required");
        return;
    }
    if (!validate_room_input(name, duration_seconds, rules, rule_count, &error_message)) {
        send_error(conn->socket_fd, request_id, "BAD_REQUEST", error_message);
        return;
    }

    db = kz_db_lock();
    if (db == NULL) {
        kz_db_unlock();
        send_error(conn->socket_fd, request_id, "INTERNAL_ERROR", "Database error");
        return;
    }
    if (!execute_sql(db, "BEGIN IMMEDIATE;")) {
        kz_db_unlock();
        send_error(conn->socket_fd, request_id, "INTERNAL_ERROR", "Could not start room creation");
        return;
    }
    for (size_t index = 0U; index < rule_count; index++) {
        int available = 0;
        if (!count_active_questions(db, &rules[index], &available)) {
            (void)execute_sql(db, "ROLLBACK;");
            kz_db_unlock();
            send_error(conn->socket_fd, request_id, "INTERNAL_ERROR",
                       "Could not validate available questions");
            return;
        }
        if (available < rules[index].quantity) {
            (void)execute_sql(db, "ROLLBACK;");
            kz_db_unlock();
            send_error(conn->socket_fd, request_id, "CONFLICT",
                       "Not enough active questions for a room rule");
            return;
        }
    }
    if (!insert_room_and_rules(db, user.id, name, duration_seconds,
                               rules, rule_count, &room_id) ||
        !execute_sql(db, "COMMIT;")) {
        (void)execute_sql(db, "ROLLBACK;");
        kz_db_unlock();
        send_error(conn->socket_fd, request_id, "INTERNAL_ERROR",
                   "Could not create room; no changes were saved");
        return;
    }

    (void)snprintf(room_id_text, sizeof(room_id_text), "%d", room_id);
    json_escape(name, escaped_name, sizeof(escaped_name));
    /* Keep audit data structural only: a room name is free-form user input and
     * must not be copied into an audit trail where it could contain a secret. */
    (void)snprintf(detail_json, sizeof(detail_json),
                   "{\"rule_count\":%u}", (unsigned int)rule_count);
    kz_log_event_db(db, user.id, "ROOM_CREATED", "exam_room", room_id_text, detail_json);
    kz_db_unlock();

    (void)snprintf(data_json, sizeof(data_json),
                   "{\"room_id\":%d,\"name\":\"%s\",\"status\":\"WAITING\","
                   "\"duration_seconds\":%d}",
                   room_id, escaped_name, duration_seconds);
    (void)send_ok_data(conn->socket_fd, request_id, data_json);
}

void handle_join_room(kz_connection *conn, const char *request_id,
                      const char *token, const char *payload_json) {
    kz_auth_user user;
    const char *error_code = NULL;
    const char *error_message = NULL;
    sqlite3 *db;
    sqlite3_stmt *room_statement = NULL;
    sqlite3_stmt *join_statement = NULL;
    sqlite3_stmt *count_statement = NULL;
    const char *room_sql = "SELECT status FROM exam_rooms WHERE id = ?;";
    const char *join_sql =
        "INSERT INTO room_participants(room_id, user_id, state) VALUES (?, ?, 'JOINED');";
    const char *count_sql =
        "SELECT COUNT(*) FROM room_participants WHERE room_id = ?;";
    const char *status;
    int room_id = 0;
    int participant_count = 0;
    int step_result;
    bool transaction_started = false;
    char room_id_text[32];
    char detail_json[96];
    char data_json[160];

    if (!require_session(token, &user, &error_code, &error_message)) {
        send_error(conn->socket_fd, request_id, error_code, error_message);
        return;
    }
    if (!find_json_int_member(payload_json, "room_id", &room_id) || room_id <= 0) {
        send_error(conn->socket_fd, request_id, "BAD_REQUEST",
                   "room_id must be a positive integer");
        return;
    }

    db = kz_db_lock();
    if (db == NULL) {
        kz_db_unlock();
        send_error(conn->socket_fd, request_id, "INTERNAL_ERROR", "Database error");
        return;
    }
    if (!execute_sql(db, "BEGIN IMMEDIATE;")) {
        kz_db_unlock();
        send_error(conn->socket_fd, request_id, "INTERNAL_ERROR",
                   "Could not start room join");
        return;
    }
    transaction_started = true;

    if (sqlite3_prepare_v2(db, room_sql, -1, &room_statement, NULL) != SQLITE_OK) {
        error_code = "INTERNAL_ERROR";
        error_message = "Could not read room";
        goto rollback;
    }
    (void)sqlite3_bind_int(room_statement, 1, room_id);
    if (sqlite3_step(room_statement) != SQLITE_ROW) {
        error_code = "NOT_FOUND";
        error_message = "Room not found";
        goto rollback;
    }
    status = (const char *)sqlite3_column_text(room_statement, 0);
    if (status == NULL || strcmp(status, "WAITING") != 0) {
        error_code = "CONFLICT";
        error_message = "Room is not accepting participants";
        goto rollback;
    }
    sqlite3_finalize(room_statement);
    room_statement = NULL;

    if (sqlite3_prepare_v2(db, join_sql, -1, &join_statement, NULL) != SQLITE_OK) {
        error_code = "INTERNAL_ERROR";
        error_message = "Could not join room";
        goto rollback;
    }
    (void)sqlite3_bind_int(join_statement, 1, room_id);
    (void)sqlite3_bind_int(join_statement, 2, user.id);
    step_result = sqlite3_step(join_statement);
    if (step_result != SQLITE_DONE) {
        error_code = step_result == SQLITE_CONSTRAINT ? "CONFLICT" : "INTERNAL_ERROR";
        error_message = step_result == SQLITE_CONSTRAINT ? "Already joined this room" :
                                                        "Could not join room";
        goto rollback;
    }
    sqlite3_finalize(join_statement);
    join_statement = NULL;

    if (sqlite3_prepare_v2(db, count_sql, -1, &count_statement, NULL) != SQLITE_OK) {
        error_code = "INTERNAL_ERROR";
        error_message = "Could not count room participants";
        goto rollback;
    }
    (void)sqlite3_bind_int(count_statement, 1, room_id);
    if (sqlite3_step(count_statement) != SQLITE_ROW) {
        error_code = "INTERNAL_ERROR";
        error_message = "Could not count room participants";
        goto rollback;
    }
    participant_count = sqlite3_column_int(count_statement, 0);
    sqlite3_finalize(count_statement);
    count_statement = NULL;

    (void)snprintf(room_id_text, sizeof(room_id_text), "%d", room_id);
    (void)snprintf(detail_json, sizeof(detail_json),
                   "{\"participant_count\":%d}", participant_count);
    kz_log_event_db(db, user.id, "ROOM_JOINED", "exam_room", room_id_text, detail_json);
    if (!execute_sql(db, "COMMIT;")) {
        error_code = "INTERNAL_ERROR";
        error_message = "Could not save room join";
        goto rollback;
    }
    transaction_started = false;
    kz_db_unlock();

    (void)snprintf(data_json, sizeof(data_json),
                   "{\"room_id\":%d,\"status\":\"WAITING\","
                   "\"participant_state\":\"JOINED\",\"participant_count\":%d}",
                   room_id, participant_count);
    (void)send_ok_data(conn->socket_fd, request_id, data_json);
    return;

rollback:
    sqlite3_finalize(room_statement);
    sqlite3_finalize(join_statement);
    sqlite3_finalize(count_statement);
    if (transaction_started) {
        (void)execute_sql(db, "ROLLBACK;");
    }
    kz_db_unlock();
    send_error(conn->socket_fd, request_id, error_code, error_message);
}

static bool snapshot_room_questions(sqlite3 *db, int room_id, int *out_total) {
    sqlite3_stmt *rules = NULL;
    sqlite3_stmt *questions = NULL;
    sqlite3_stmt *insert_question = NULL;
    sqlite3_stmt *options = NULL;
    sqlite3_stmt *insert_option = NULL;
    const char *rules_sql =
        "SELECT topic, difficulty, quantity FROM room_question_rules "
        "WHERE room_id = ? ORDER BY topic, difficulty;";
    const char *questions_sql =
        "SELECT id, content, correct_option_id FROM questions "
        "WHERE is_active = 1 AND topic = ? AND difficulty = ? "
        "AND correct_option_id IS NOT NULL ORDER BY RANDOM() LIMIT ?;";
    const char *insert_question_sql =
        "INSERT INTO room_questions "
        "(room_id, question_id, position, content_snapshot, correct_option_snapshot) "
        "VALUES (?, ?, ?, ?, ?);";
    const char *options_sql =
        "SELECT id, position, label, content FROM question_options "
        "WHERE question_id = ? ORDER BY position;";
    const char *insert_option_sql =
        "INSERT INTO room_question_options "
        "(room_id, question_id, option_id_snapshot, position, label, content_snapshot) "
        "VALUES (?, ?, ?, ?, ?, ?);";
    bool ok = false;
    int next_position = 1;

    if (db == NULL || out_total == NULL ||
        sqlite3_prepare_v2(db, rules_sql, -1, &rules, NULL) != SQLITE_OK ||
        sqlite3_prepare_v2(db, questions_sql, -1, &questions, NULL) != SQLITE_OK ||
        sqlite3_prepare_v2(db, insert_question_sql, -1, &insert_question, NULL) != SQLITE_OK ||
        sqlite3_prepare_v2(db, options_sql, -1, &options, NULL) != SQLITE_OK ||
        sqlite3_prepare_v2(db, insert_option_sql, -1, &insert_option, NULL) != SQLITE_OK) {
        goto done;
    }

    (void)sqlite3_bind_int(rules, 1, room_id);
    while (sqlite3_step(rules) == SQLITE_ROW) {
        const char *topic = (const char *)sqlite3_column_text(rules, 0);
        const char *difficulty = (const char *)sqlite3_column_text(rules, 1);
        int quantity = sqlite3_column_int(rules, 2);
        int selected = 0;

        if (topic == NULL || difficulty == NULL || quantity <= 0) {
            goto done;
        }
        (void)sqlite3_bind_text(questions, 1, topic, -1, SQLITE_STATIC);
        (void)sqlite3_bind_text(questions, 2, difficulty, -1, SQLITE_STATIC);
        (void)sqlite3_bind_int(questions, 3, quantity);
        while (sqlite3_step(questions) == SQLITE_ROW) {
            int question_id = sqlite3_column_int(questions, 0);
            const char *content = (const char *)sqlite3_column_text(questions, 1);
            int correct_option_id = sqlite3_column_int(questions, 2);
            int option_count = 0;

            (void)sqlite3_bind_int(insert_question, 1, room_id);
            (void)sqlite3_bind_int(insert_question, 2, question_id);
            (void)sqlite3_bind_int(insert_question, 3, next_position);
            (void)sqlite3_bind_text(insert_question, 4, content ? content : "", -1, SQLITE_STATIC);
            (void)sqlite3_bind_int(insert_question, 5, correct_option_id);
            if (sqlite3_step(insert_question) != SQLITE_DONE) {
                goto done;
            }
            (void)sqlite3_reset(insert_question);
            (void)sqlite3_clear_bindings(insert_question);

            (void)sqlite3_bind_int(options, 1, question_id);
            while (sqlite3_step(options) == SQLITE_ROW) {
                (void)sqlite3_bind_int(insert_option, 1, room_id);
                (void)sqlite3_bind_int(insert_option, 2, question_id);
                (void)sqlite3_bind_int(insert_option, 3, sqlite3_column_int(options, 0));
                (void)sqlite3_bind_int(insert_option, 4, sqlite3_column_int(options, 1));
                (void)sqlite3_bind_text(insert_option, 5,
                                        (const char *)sqlite3_column_text(options, 2),
                                        -1, SQLITE_STATIC);
                (void)sqlite3_bind_text(insert_option, 6,
                                        (const char *)sqlite3_column_text(options, 3),
                                        -1, SQLITE_STATIC);
                if (sqlite3_step(insert_option) != SQLITE_DONE) {
                    goto done;
                }
                (void)sqlite3_reset(insert_option);
                (void)sqlite3_clear_bindings(insert_option);
                option_count++;
            }
            (void)sqlite3_reset(options);
            (void)sqlite3_clear_bindings(options);
            if (option_count != 4) {
                goto done;
            }
            selected++;
            next_position++;
        }
        (void)sqlite3_reset(questions);
        (void)sqlite3_clear_bindings(questions);
        if (selected != quantity) {
            goto done;
        }
    }
    if (next_position == 1) {
        goto done;
    }
    *out_total = next_position - 1;
    ok = true;

done:
    sqlite3_finalize(rules);
    sqlite3_finalize(questions);
    sqlite3_finalize(insert_question);
    sqlite3_finalize(options);
    sqlite3_finalize(insert_option);
    return ok;
}

void handle_start_room(kz_connection *conn, const char *request_id,
                       const char *token, const char *payload_json) {
    kz_auth_user user;
    const char *error_code = NULL;
    const char *error_message = NULL;
    sqlite3 *db;
    sqlite3_stmt *room_statement = NULL;
    sqlite3_stmt *update_room = NULL;
    sqlite3_stmt *update_participants = NULL;
    int room_id = 0;
    int duration_seconds = 0;
    int total_questions = 0;
    int participants_started = 0;
    bool transaction_started = false;
    char room_id_text[32];
    char detail_json[128];
    char data_json[192];

    if (!require_session(token, &user, &error_code, &error_message)) {
        send_error(conn->socket_fd, request_id, error_code, error_message);
        return;
    }
    if (!find_json_int_member(payload_json, "room_id", &room_id) || room_id <= 0) {
        send_error(conn->socket_fd, request_id, "BAD_REQUEST",
                   "room_id must be a positive integer");
        return;
    }

    db = kz_db_lock();
    if (db == NULL) {
        kz_db_unlock();
        send_error(conn->socket_fd, request_id, "INTERNAL_ERROR", "Database error");
        return;
    }
    if (!execute_sql(db, "BEGIN IMMEDIATE;")) {
        kz_db_unlock();
        send_error(conn->socket_fd, request_id, "INTERNAL_ERROR", "Could not start room");
        return;
    }
    transaction_started = true;

    if (sqlite3_prepare_v2(db,
                           "SELECT owner_id, status, duration_seconds FROM exam_rooms WHERE id = ?;",
                           -1, &room_statement, NULL) != SQLITE_OK) {
        error_code = "INTERNAL_ERROR";
        error_message = "Could not read room";
        goto rollback;
    }
    (void)sqlite3_bind_int(room_statement, 1, room_id);
    if (sqlite3_step(room_statement) != SQLITE_ROW) {
        error_code = "NOT_FOUND";
        error_message = "Room not found";
        goto rollback;
    }
    if (sqlite3_column_int(room_statement, 0) != user.id) {
        error_code = "FORBIDDEN";
        error_message = "Only the room owner can perform this action";
        goto rollback;
    }
    if (strcmp((const char *)sqlite3_column_text(room_statement, 1), "WAITING") != 0) {
        error_code = "CONFLICT";
        error_message = "Room is not in WAITING state";
        goto rollback;
    }
    duration_seconds = sqlite3_column_int(room_statement, 2);
    sqlite3_finalize(room_statement);
    room_statement = NULL;

    if (!snapshot_room_questions(db, room_id, &total_questions)) {
        error_code = "CONFLICT";
        error_message = "Could not create a complete room question snapshot";
        goto rollback;
    }

    if (sqlite3_prepare_v2(db,
                           "UPDATE exam_rooms SET status = 'RUNNING', started_at = datetime('now'), "
                           "ended_at = datetime('now', '+' || ? || ' seconds') "
                           "WHERE id = ? AND status = 'WAITING';",
                           -1, &update_room, NULL) != SQLITE_OK) {
        error_code = "INTERNAL_ERROR";
        error_message = "Could not start room";
        goto rollback;
    }
    (void)sqlite3_bind_int(update_room, 1, duration_seconds);
    (void)sqlite3_bind_int(update_room, 2, room_id);
    if (sqlite3_step(update_room) != SQLITE_DONE || sqlite3_changes(db) != 1) {
        error_code = "CONFLICT";
        error_message = "Room is not in WAITING state";
        goto rollback;
    }
    sqlite3_finalize(update_room);
    update_room = NULL;

    if (sqlite3_prepare_v2(db,
                           "UPDATE room_participants SET state = 'IN_PROGRESS' "
                           "WHERE room_id = ? AND state = 'JOINED';",
                           -1, &update_participants, NULL) != SQLITE_OK) {
        error_code = "INTERNAL_ERROR";
        error_message = "Could not start room participants";
        goto rollback;
    }
    (void)sqlite3_bind_int(update_participants, 1, room_id);
    if (sqlite3_step(update_participants) != SQLITE_DONE) {
        error_code = "INTERNAL_ERROR";
        error_message = "Could not start room participants";
        goto rollback;
    }
    participants_started = sqlite3_changes(db);
    sqlite3_finalize(update_participants);
    update_participants = NULL;

    (void)snprintf(room_id_text, sizeof(room_id_text), "%d", room_id);
    (void)snprintf(detail_json, sizeof(detail_json),
                   "{\"question_count\":%d,\"participants_started\":%d}",
                   total_questions, participants_started);
    kz_log_event_db(db, user.id, "ROOM_STARTED", "exam_room", room_id_text, detail_json);
    if (!execute_sql(db, "COMMIT;")) {
        error_code = "INTERNAL_ERROR";
        error_message = "Could not save room start";
        goto rollback;
    }
    transaction_started = false;
    kz_db_unlock();

    (void)snprintf(data_json, sizeof(data_json),
                   "{\"room_id\":%d,\"status\":\"RUNNING\","
                   "\"question_count\":%d,\"participants_started\":%d}",
                   room_id, total_questions, participants_started);
    (void)send_ok_data(conn->socket_fd, request_id, data_json);
    return;

rollback:
    sqlite3_finalize(room_statement);
    sqlite3_finalize(update_room);
    sqlite3_finalize(update_participants);
    if (transaction_started) {
        (void)execute_sql(db, "ROLLBACK;");
    }
    kz_db_unlock();
    send_error(conn->socket_fd, request_id, error_code, error_message);
}

static char *build_exam_json(sqlite3 *db, int room_id, int user_id) {
    sqlite3_stmt *questions = NULL;
    sqlite3_stmt *options = NULL;
    sqlite3_stmt *answers = NULL;
    char *result = (char *)malloc(KZ_MAX_NDJSON_LINE_BYTES);
    size_t used = 0U;
    bool failed = result == NULL;
    bool first_question = true;
    int question_count = 0;

    if (!failed && !append_room_json(result, KZ_MAX_NDJSON_LINE_BYTES, &used,
                                     "{\"room_id\":%d,\"status\":\"RUNNING\",\"questions\":[", room_id)) failed = true;
    if (!failed && sqlite3_prepare_v2(db,
        "SELECT question_id, position, content_snapshot FROM room_questions WHERE room_id = ? ORDER BY position;",
        -1, &questions, NULL) != SQLITE_OK) failed = true;
    if (!failed && sqlite3_prepare_v2(db,
        "SELECT option_id_snapshot, position, label, content_snapshot FROM room_question_options "
        "WHERE room_id = ? AND question_id = ? ORDER BY position;", -1, &options, NULL) != SQLITE_OK) failed = true;
    if (!failed && sqlite3_prepare_v2(db,
        "SELECT selected_option_id FROM attempt_answers WHERE room_id = ? AND user_id = ? AND question_id = ?;",
        -1, &answers, NULL) != SQLITE_OK) failed = true;

    if (!failed) {
        (void)sqlite3_bind_int(questions, 1, room_id);
        while (sqlite3_step(questions) == SQLITE_ROW && !failed) {
            int question_id = sqlite3_column_int(questions, 0);
            char escaped_content[2401];
            bool first_option = true;
            int option_count = 0;
            int selected_option_id = 0;
            const char *content = (const char *)sqlite3_column_text(questions, 2);
            json_escape(content ? content : "", escaped_content, sizeof(escaped_content));
            if (!append_room_json(result, KZ_MAX_NDJSON_LINE_BYTES, &used,
                "%s{\"id\":%d,\"position\":%d,\"content\":\"%s\",\"options\":[",
                first_question ? "" : ",", question_id, sqlite3_column_int(questions, 1), escaped_content)) { failed = true; break; }
            (void)sqlite3_bind_int(options, 1, room_id);
            (void)sqlite3_bind_int(options, 2, question_id);
            while (sqlite3_step(options) == SQLITE_ROW) {
                char escaped_label[32];
                char escaped_option[801];
                json_escape((const char *)sqlite3_column_text(options, 2), escaped_label, sizeof(escaped_label));
                json_escape((const char *)sqlite3_column_text(options, 3), escaped_option, sizeof(escaped_option));
                if (!append_room_json(result, KZ_MAX_NDJSON_LINE_BYTES, &used,
                    "%s{\"id\":%d,\"position\":%d,\"label\":\"%s\",\"content\":\"%s\"}",
                    first_option ? "" : ",", sqlite3_column_int(options, 0), sqlite3_column_int(options, 1),
                    escaped_label, escaped_option)) { failed = true; break; }
                first_option = false;
                option_count++;
            }
            (void)sqlite3_reset(options); (void)sqlite3_clear_bindings(options);
            if (failed || option_count != 4) { failed = true; break; }
            (void)sqlite3_bind_int(answers, 1, room_id);
            (void)sqlite3_bind_int(answers, 2, user_id);
            (void)sqlite3_bind_int(answers, 3, question_id);
            if (sqlite3_step(answers) == SQLITE_ROW) selected_option_id = sqlite3_column_int(answers, 0);
            (void)sqlite3_reset(answers); (void)sqlite3_clear_bindings(answers);
            if (selected_option_id > 0) {
                if (!append_room_json(result, KZ_MAX_NDJSON_LINE_BYTES, &used,
                    "],\"selected_option_id\":%d}", selected_option_id)) { failed = true; break; }
            } else if (!append_room_json(result, KZ_MAX_NDJSON_LINE_BYTES, &used,
                "],\"selected_option_id\":null}")) { failed = true; break; }
            first_question = false;
            question_count++;
        }
    }
    sqlite3_finalize(questions); sqlite3_finalize(options); sqlite3_finalize(answers);
    if (failed || question_count == 0 ||
        !append_room_json(result, KZ_MAX_NDJSON_LINE_BYTES, &used, "]}")) { free(result); return NULL; }
    return result;
}

void handle_get_exam(kz_connection *conn, const char *request_id,
                     const char *token, const char *payload_json) {
    kz_auth_user user;
    const char *error_code = NULL;
    const char *error_message = NULL;
    sqlite3 *db;
    sqlite3_stmt *statement = NULL;
    int room_id = 0;
    char *data_json;

    if (!require_session(token, &user, &error_code, &error_message)) { send_error(conn->socket_fd, request_id, error_code, error_message); return; }
    if (!find_json_int_member(payload_json, "room_id", &room_id) || room_id <= 0) { send_error(conn->socket_fd, request_id, "BAD_REQUEST", "room_id must be a positive integer"); return; }
    db = kz_db_lock();
    if (db == NULL) { kz_db_unlock(); send_error(conn->socket_fd, request_id, "INTERNAL_ERROR", "Database error"); return; }
    if (sqlite3_prepare_v2(db, "SELECT status FROM exam_rooms WHERE id = ?;", -1, &statement, NULL) != SQLITE_OK) { error_code = "INTERNAL_ERROR"; error_message = "Could not read room"; goto error; }
    (void)sqlite3_bind_int(statement, 1, room_id);
    if (sqlite3_step(statement) != SQLITE_ROW) { error_code = "NOT_FOUND"; error_message = "Room not found"; goto error; }
    if (strcmp((const char *)sqlite3_column_text(statement, 0), "RUNNING") != 0) { error_code = "CONFLICT"; error_message = "Room is not running"; goto error; }
    sqlite3_finalize(statement); statement = NULL;
    if (sqlite3_prepare_v2(db, "SELECT 1 FROM room_participants WHERE room_id = ? AND user_id = ?;", -1, &statement, NULL) != SQLITE_OK) { error_code = "INTERNAL_ERROR"; error_message = "Could not read room participant"; goto error; }
    (void)sqlite3_bind_int(statement, 1, room_id); (void)sqlite3_bind_int(statement, 2, user.id);
    if (sqlite3_step(statement) != SQLITE_ROW) { error_code = "FORBIDDEN"; error_message = "Only room participants can view this exam"; goto error; }
    sqlite3_finalize(statement); statement = NULL;
    data_json = build_exam_json(db, room_id, user.id);
    if (data_json == NULL) { error_code = "INTERNAL_ERROR"; error_message = "Could not build exam snapshot"; goto error; }
    kz_db_unlock(); (void)send_ok_data(conn->socket_fd, request_id, data_json); free(data_json); return;
error:
    sqlite3_finalize(statement); kz_db_unlock(); send_error(conn->socket_fd, request_id, error_code, error_message);
}

void handle_save_answer(kz_connection *conn, const char *request_id,
                        const char *token, const char *payload_json) {
    kz_auth_user user;
    const char *error_code = NULL;
    const char *error_message = NULL;
    sqlite3 *db;
    sqlite3_stmt *statement = NULL;
    int room_id = 0;
    int question_id = 0;
    int option_id = 0;
    bool transaction_started = false;
    char room_id_text[32];
    char detail_json[96];

    if (!require_session(token, &user, &error_code, &error_message)) { send_error(conn->socket_fd, request_id, error_code, error_message); return; }
    if (!find_json_int_member(payload_json, "room_id", &room_id) ||
        !find_json_int_member(payload_json, "question_id", &question_id) ||
        !find_json_int_member(payload_json, "option_id", &option_id) ||
        room_id <= 0 || question_id <= 0 || option_id <= 0) {
        send_error(conn->socket_fd, request_id, "BAD_REQUEST", "room_id, question_id, and option_id must be positive integers");
        return;
    }
    db = kz_db_lock();
    if (db == NULL) { kz_db_unlock(); send_error(conn->socket_fd, request_id, "INTERNAL_ERROR", "Database error"); return; }
    if (!execute_sql(db, "BEGIN IMMEDIATE;")) { kz_db_unlock(); send_error(conn->socket_fd, request_id, "INTERNAL_ERROR", "Could not save answer"); return; }
    transaction_started = true;

    if (sqlite3_prepare_v2(db,
        "SELECT r.status, r.ended_at <= datetime('now'), rp.state "
        "FROM exam_rooms r LEFT JOIN room_participants rp ON rp.room_id = r.id AND rp.user_id = ? "
        "WHERE r.id = ?;", -1, &statement, NULL) != SQLITE_OK) { error_code = "INTERNAL_ERROR"; error_message = "Could not read room"; goto rollback; }
    (void)sqlite3_bind_int(statement, 1, user.id); (void)sqlite3_bind_int(statement, 2, room_id);
    if (sqlite3_step(statement) != SQLITE_ROW) { error_code = "NOT_FOUND"; error_message = "Room not found"; goto rollback; }
    if (strcmp((const char *)sqlite3_column_text(statement, 0), "RUNNING") != 0 || sqlite3_column_int(statement, 1) != 0) { error_code = "CONFLICT"; error_message = "Room is no longer accepting answers"; goto rollback; }
    if (sqlite3_column_type(statement, 2) == SQLITE_NULL) { error_code = "FORBIDDEN"; error_message = "Only room participants can save answers"; goto rollback; }
    if (strcmp((const char *)sqlite3_column_text(statement, 2), "IN_PROGRESS") != 0) { error_code = "CONFLICT"; error_message = "Participant is no longer taking this exam"; goto rollback; }
    sqlite3_finalize(statement); statement = NULL;

    if (sqlite3_prepare_v2(db, "SELECT 1 FROM room_questions WHERE room_id = ? AND question_id = ?;", -1, &statement, NULL) != SQLITE_OK) { error_code = "INTERNAL_ERROR"; error_message = "Could not validate question"; goto rollback; }
    (void)sqlite3_bind_int(statement, 1, room_id); (void)sqlite3_bind_int(statement, 2, question_id);
    if (sqlite3_step(statement) != SQLITE_ROW) { error_code = "BAD_REQUEST"; error_message = "Question is not in this room"; goto rollback; }
    sqlite3_finalize(statement); statement = NULL;
    if (sqlite3_prepare_v2(db,
        "SELECT 1 FROM room_question_options WHERE room_id = ? AND question_id = ? AND option_id_snapshot = ?;",
        -1, &statement, NULL) != SQLITE_OK) { error_code = "INTERNAL_ERROR"; error_message = "Could not validate option"; goto rollback; }
    (void)sqlite3_bind_int(statement, 1, room_id); (void)sqlite3_bind_int(statement, 2, question_id); (void)sqlite3_bind_int(statement, 3, option_id);
    if (sqlite3_step(statement) != SQLITE_ROW) { error_code = "BAD_REQUEST"; error_message = "Option is not in this room question"; goto rollback; }
    sqlite3_finalize(statement); statement = NULL;

    if (sqlite3_prepare_v2(db,
        "INSERT INTO attempt_answers(room_id, user_id, question_id, selected_option_id) VALUES (?, ?, ?, ?) "
        "ON CONFLICT(room_id, user_id, question_id) DO UPDATE SET selected_option_id = excluded.selected_option_id, updated_at = CURRENT_TIMESTAMP;",
        -1, &statement, NULL) != SQLITE_OK) { error_code = "INTERNAL_ERROR"; error_message = "Could not save answer"; goto rollback; }
    (void)sqlite3_bind_int(statement, 1, room_id); (void)sqlite3_bind_int(statement, 2, user.id);
    (void)sqlite3_bind_int(statement, 3, question_id); (void)sqlite3_bind_int(statement, 4, option_id);
    if (sqlite3_step(statement) != SQLITE_DONE) { error_code = "INTERNAL_ERROR"; error_message = "Could not save answer"; goto rollback; }
    sqlite3_finalize(statement); statement = NULL;

    (void)snprintf(room_id_text, sizeof(room_id_text), "%d", room_id);
    (void)snprintf(detail_json, sizeof(detail_json), "{\"question_id\":%d}", question_id);
    kz_log_event_db(db, user.id, "ANSWER_SAVED", "exam_room", room_id_text, detail_json);
    if (!execute_sql(db, "COMMIT;")) { error_code = "INTERNAL_ERROR"; error_message = "Could not save answer"; goto rollback; }
    transaction_started = false;
    kz_db_unlock(); (void)send_ok_data(conn->socket_fd, request_id, "{\"saved\":true}"); return;
rollback:
    sqlite3_finalize(statement);
    if (transaction_started) (void)execute_sql(db, "ROLLBACK;");
    kz_db_unlock(); send_error(conn->socket_fd, request_id, error_code, error_message);
}

void handle_submit_exam(kz_connection *conn, const char *request_id,
                        const char *token, const char *payload_json) {
    kz_auth_user user;
    const char *error_code = NULL;
    const char *error_message = NULL;
    sqlite3 *db;
    sqlite3_stmt *statement = NULL;
    int room_id = 0;
    int correct_count = 0;
    int total = 0;
    double score = 0.0;
    bool expired = false;
    const char *new_state;
    char state[20] = {0};
    char data_json[192];
    char room_id_text[32];

    if (!require_session(token, &user, &error_code, &error_message)) { send_error(conn->socket_fd, request_id, error_code, error_message); return; }
    if (!find_json_int_member(payload_json, "room_id", &room_id) || room_id <= 0) { send_error(conn->socket_fd, request_id, "BAD_REQUEST", "room_id must be a positive integer"); return; }
    db = kz_db_lock();
    if (db == NULL) { kz_db_unlock(); send_error(conn->socket_fd, request_id, "INTERNAL_ERROR", "Database error"); return; }
    if (!execute_sql(db, "BEGIN IMMEDIATE;")) { kz_db_unlock(); send_error(conn->socket_fd, request_id, "INTERNAL_ERROR", "Could not submit exam"); return; }

    if (sqlite3_prepare_v2(db,
        "SELECT r.status, r.ended_at <= datetime('now'), rp.state, rp.score, rp.correct_count "
        "FROM exam_rooms r LEFT JOIN room_participants rp ON rp.room_id = r.id AND rp.user_id = ? WHERE r.id = ?;",
        -1, &statement, NULL) != SQLITE_OK) { error_code = "INTERNAL_ERROR"; error_message = "Could not read exam state"; goto rollback; }
    (void)sqlite3_bind_int(statement, 1, user.id); (void)sqlite3_bind_int(statement, 2, room_id);
    if (sqlite3_step(statement) != SQLITE_ROW) { error_code = "NOT_FOUND"; error_message = "Room not found"; goto rollback; }
    if (sqlite3_column_type(statement, 2) == SQLITE_NULL) { error_code = "FORBIDDEN"; error_message = "Only room participants can submit"; goto rollback; }
    (void)snprintf(state, sizeof(state), "%s", (const char *)sqlite3_column_text(statement, 2));
    if (strcmp(state, "SUBMITTED") == 0 || strcmp(state, "AUTO_SUBMITTED") == 0) {
        correct_count = sqlite3_column_int(statement, 4);
        score = sqlite3_column_double(statement, 3);
        sqlite3_finalize(statement); statement = NULL;
        if (sqlite3_prepare_v2(db, "SELECT COUNT(*) FROM room_questions WHERE room_id = ?;", -1, &statement, NULL) != SQLITE_OK) { error_code = "INTERNAL_ERROR"; error_message = "Could not read exam result"; goto rollback; }
        (void)sqlite3_bind_int(statement, 1, room_id);
        if (sqlite3_step(statement) != SQLITE_ROW) { error_code = "INTERNAL_ERROR"; error_message = "Could not read exam result"; goto rollback; }
        total = sqlite3_column_int(statement, 0);
        sqlite3_finalize(statement); statement = NULL;
        if (!execute_sql(db, "COMMIT;")) { error_code = "INTERNAL_ERROR"; error_message = "Could not read exam result"; goto rollback; }
        kz_db_unlock();
        (void)snprintf(data_json, sizeof(data_json), "{\"room_id\":%d,\"state\":\"%s\",\"correct_count\":%d,\"total\":%d,\"score\":%.2f}", room_id, state, correct_count, total, score);
        (void)send_ok_data(conn->socket_fd, request_id, data_json);
        return;
    }
    if (strcmp(state, "IN_PROGRESS") != 0) { error_code = "CONFLICT"; error_message = "Participant is not taking this exam"; goto rollback; }
    if (strcmp((const char *)sqlite3_column_text(statement, 0), "RUNNING") != 0) { error_code = "CONFLICT"; error_message = "Room is not running"; goto rollback; }
    expired = sqlite3_column_int(statement, 1) != 0;
    sqlite3_finalize(statement); statement = NULL;

    if (sqlite3_prepare_v2(db,
        "SELECT COUNT(*), COALESCE(SUM(CASE WHEN a.selected_option_id = q.correct_option_snapshot THEN 1 ELSE 0 END), 0) "
        "FROM room_questions q LEFT JOIN attempt_answers a ON a.room_id = q.room_id AND a.question_id = q.question_id AND a.user_id = ? "
        "WHERE q.room_id = ?;", -1, &statement, NULL) != SQLITE_OK) { error_code = "INTERNAL_ERROR"; error_message = "Could not grade exam"; goto rollback; }
    (void)sqlite3_bind_int(statement, 1, user.id); (void)sqlite3_bind_int(statement, 2, room_id);
    if (sqlite3_step(statement) != SQLITE_ROW) { error_code = "INTERNAL_ERROR"; error_message = "Could not grade exam"; goto rollback; }
    total = sqlite3_column_int(statement, 0); correct_count = sqlite3_column_int(statement, 1);
    sqlite3_finalize(statement); statement = NULL;
    if (total <= 0) { error_code = "INTERNAL_ERROR"; error_message = "Exam snapshot is empty"; goto rollback; }
    score = (double)correct_count * 10.0 / (double)total;
    new_state = expired ? "AUTO_SUBMITTED" : "SUBMITTED";
    if (sqlite3_prepare_v2(db,
        "UPDATE room_participants SET state = ?, submitted_at = datetime('now'), score = ?, correct_count = ? "
        "WHERE room_id = ? AND user_id = ? AND state = 'IN_PROGRESS';", -1, &statement, NULL) != SQLITE_OK) { error_code = "INTERNAL_ERROR"; error_message = "Could not save exam result"; goto rollback; }
    (void)sqlite3_bind_text(statement, 1, new_state, -1, SQLITE_STATIC); (void)sqlite3_bind_double(statement, 2, score);
    (void)sqlite3_bind_int(statement, 3, correct_count); (void)sqlite3_bind_int(statement, 4, room_id); (void)sqlite3_bind_int(statement, 5, user.id);
    if (sqlite3_step(statement) != SQLITE_DONE || sqlite3_changes(db) != 1) { error_code = "CONFLICT"; error_message = "Exam was already submitted"; goto rollback; }
    sqlite3_finalize(statement); statement = NULL;
    (void)snprintf(room_id_text, sizeof(room_id_text), "%d", room_id);
    kz_log_event_db(db, user.id, expired ? "EXAM_AUTO_SUBMITTED" : "EXAM_SUBMITTED", "exam_room", room_id_text, "{}");
    if (!execute_sql(db, "COMMIT;")) { error_code = "INTERNAL_ERROR"; error_message = "Could not save exam result"; goto rollback; }
    kz_db_unlock();
    (void)snprintf(data_json, sizeof(data_json), "{\"room_id\":%d,\"state\":\"%s\",\"correct_count\":%d,\"total\":%d,\"score\":%.2f}", room_id, new_state, correct_count, total, score);
    (void)send_ok_data(conn->socket_fd, request_id, data_json);
    return;
rollback:
    sqlite3_finalize(statement); (void)execute_sql(db, "ROLLBACK;"); kz_db_unlock();
    send_error(conn->socket_fd, request_id, error_code, error_message);
}

static int process_one_expired_room(void) {
    sqlite3 *db;
    sqlite3_stmt *statement = NULL;
    int room_id = 0;
    int total = 0;
    int outcome = -1;
    int step_result;
    char room_id_text[32];

    db = kz_db_lock();
    if (db == NULL) { kz_db_unlock(); return -1; }
    if (!execute_sql(db, "BEGIN IMMEDIATE;")) { kz_db_unlock(); return -1; }
    if (sqlite3_prepare_v2(db,
        "SELECT id FROM exam_rooms WHERE status = 'RUNNING' AND ended_at <= datetime('now') "
        "ORDER BY id LIMIT 1;", -1, &statement, NULL) != SQLITE_OK) goto rollback;
    if (sqlite3_step(statement) != SQLITE_ROW) {
        sqlite3_finalize(statement); statement = NULL;
        if (execute_sql(db, "COMMIT;")) outcome = 0;
        goto done;
    }
    room_id = sqlite3_column_int(statement, 0);
    sqlite3_finalize(statement); statement = NULL;
    if (sqlite3_prepare_v2(db, "SELECT COUNT(*) FROM room_questions WHERE room_id = ?;", -1, &statement, NULL) != SQLITE_OK) goto rollback;
    (void)sqlite3_bind_int(statement, 1, room_id);
    if (sqlite3_step(statement) != SQLITE_ROW) goto rollback;
    total = sqlite3_column_int(statement, 0);
    sqlite3_finalize(statement); statement = NULL;
    if (total <= 0) goto rollback;

    if (sqlite3_prepare_v2(db,
        "SELECT user_id FROM room_participants "
        "WHERE room_id = ? AND state IN ('JOINED', 'IN_PROGRESS');",
        -1, &statement, NULL) != SQLITE_OK) goto rollback;
    (void)sqlite3_bind_int(statement, 1, room_id);
    (void)snprintf(room_id_text, sizeof(room_id_text), "%d", room_id);
    while ((step_result = sqlite3_step(statement)) == SQLITE_ROW) {
        kz_log_event_db(db, sqlite3_column_int(statement, 0), "EXAM_AUTO_SUBMITTED",
                        "exam_room", room_id_text, "{}");
    }
    if (step_result != SQLITE_DONE) goto rollback;
    sqlite3_finalize(statement); statement = NULL;

    if (sqlite3_prepare_v2(db,
        "UPDATE room_participants SET state = 'AUTO_SUBMITTED', submitted_at = datetime('now'), "
        "correct_count = (SELECT COALESCE(SUM(CASE WHEN a.selected_option_id = q.correct_option_snapshot THEN 1 ELSE 0 END), 0) "
        "FROM room_questions q LEFT JOIN attempt_answers a ON a.room_id = q.room_id AND a.question_id = q.question_id AND a.user_id = room_participants.user_id "
        "WHERE q.room_id = room_participants.room_id), "
        "score = 10.0 * (SELECT COALESCE(SUM(CASE WHEN a.selected_option_id = q.correct_option_snapshot THEN 1 ELSE 0 END), 0) "
        "FROM room_questions q LEFT JOIN attempt_answers a ON a.room_id = q.room_id AND a.question_id = q.question_id AND a.user_id = room_participants.user_id "
        "WHERE q.room_id = room_participants.room_id) / ? "
        "WHERE room_id = ? AND state IN ('JOINED', 'IN_PROGRESS');",
        -1, &statement, NULL) != SQLITE_OK) goto rollback;
    (void)sqlite3_bind_int(statement, 1, total); (void)sqlite3_bind_int(statement, 2, room_id);
    if (sqlite3_step(statement) != SQLITE_DONE) goto rollback;
    sqlite3_finalize(statement); statement = NULL;

    if (sqlite3_prepare_v2(db,
        "UPDATE exam_rooms SET status = 'ENDED' WHERE id = ? AND status = 'RUNNING' "
        "AND ended_at <= datetime('now');", -1, &statement, NULL) != SQLITE_OK) goto rollback;
    (void)sqlite3_bind_int(statement, 1, room_id);
    if (sqlite3_step(statement) != SQLITE_DONE || sqlite3_changes(db) != 1) goto rollback;
    sqlite3_finalize(statement); statement = NULL;
    kz_log_event_db(db, 0, "ROOM_ENDED", "exam_room", room_id_text, "{}");
    if (!execute_sql(db, "COMMIT;")) goto rollback;
    outcome = 1;
    goto done;

rollback:
    sqlite3_finalize(statement);
    (void)execute_sql(db, "ROLLBACK;");
done:
    kz_db_unlock();
    return outcome;
}

void process_expired_rooms(void) {
    while (process_one_expired_room() == 1) {
        /* Each room is committed independently so the DB mutex is not held for a batch. */
    }
}
