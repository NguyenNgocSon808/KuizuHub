#include "history.h"

#include "auth.h"
#include "db.h"
#include "log.h"

#include <stdbool.h>
#include <stdarg.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#define KZ_HISTORY_DEFAULT_LIMIT 20
#define KZ_HISTORY_MAX_LIMIT 50
#define KZ_MAX_STAT_BUCKETS 96

typedef struct {
    char topic[65];
    char difficulty[16];
    int correct_count;
    int total;
} kz_topic_stat;

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

static bool payload_mentions_member(const char *payload_json, const char *member) {
    char needle[96];
    int written;

    if (payload_json == NULL || member == NULL) {
        return false;
    }
    written = snprintf(needle, sizeof(needle), "\"%s\"", member);
    return written > 0 && (size_t)written < sizeof(needle) && strstr(payload_json, needle) != NULL;
}

static bool parse_pagination(const char *payload_json, int *out_limit, int *out_offset) {
    int value;

    if (payload_json == NULL || out_limit == NULL || out_offset == NULL) {
        return false;
    }
    *out_limit = KZ_HISTORY_DEFAULT_LIMIT;
    *out_offset = 0;
    if (payload_mentions_member(payload_json, "limit")) {
        if (!find_json_int_member(payload_json, "limit", &value) ||
            value < 1 || value > KZ_HISTORY_MAX_LIMIT) {
            return false;
        }
        *out_limit = value;
    }
    if (payload_mentions_member(payload_json, "offset")) {
        if (!find_json_int_member(payload_json, "offset", &value) || value < 0) {
            return false;
        }
        *out_offset = value;
    }
    return true;
}

static bool append_history_entry(char *buffer, size_t capacity, size_t *used,
                                 sqlite3_stmt *statement, bool first) {
    const char *kind = (const char *)sqlite3_column_text(statement, 0);
    const char *title = (const char *)sqlite3_column_text(statement, 3);
    const char *topic = (const char *)sqlite3_column_text(statement, 4);
    const char *difficulty = (const char *)sqlite3_column_text(statement, 5);
    const char *completed_at = (const char *)sqlite3_column_text(statement, 10);
    const char *state = (const char *)sqlite3_column_text(statement, 11);
    char escaped_kind[32];
    char escaped_title[512];
    char escaped_topic[130];
    char escaped_difficulty[32];
    char escaped_completed_at[64];
    char escaped_state[32];

    json_escape(kind ? kind : "", escaped_kind, sizeof(escaped_kind));
    json_escape(title ? title : "", escaped_title, sizeof(escaped_title));
    json_escape(topic ? topic : "", escaped_topic, sizeof(escaped_topic));
    json_escape(difficulty ? difficulty : "", escaped_difficulty, sizeof(escaped_difficulty));
    json_escape(completed_at ? completed_at : "", escaped_completed_at, sizeof(escaped_completed_at));
    json_escape(state ? state : "", escaped_state, sizeof(escaped_state));
    if (!append_format(buffer, capacity, used,
        "%s{\"kind\":\"%s\",\"attempt_id\":%d,\"room_id\":",
        first ? "" : ",", escaped_kind, sqlite3_column_int(statement, 1))) {
        return false;
    }
    if (sqlite3_column_type(statement, 2) == SQLITE_NULL) {
        if (!append_format(buffer, capacity, used, "null")) {
            return false;
        }
    } else if (!append_format(buffer, capacity, used, "%d", sqlite3_column_int(statement, 2))) {
        return false;
    }
    return append_format(buffer, capacity, used,
        ",\"title\":\"%s\",\"topic\":\"%s\",\"difficulty\":\"%s\","
        "\"score\":%.2f,\"correct_count\":%d,\"total\":%d,\"duration_seconds\":%d,"
        "\"completed_at\":\"%s\",\"state\":\"%s\"}",
        escaped_title, escaped_topic, escaped_difficulty, sqlite3_column_double(statement, 6),
        sqlite3_column_int(statement, 7), sqlite3_column_int(statement, 8),
        sqlite3_column_int(statement, 9), escaped_completed_at, escaped_state);
}

void handle_get_my_history(kz_connection *conn, const char *request_id,
                           const char *token, const char *payload_json) {
    kz_auth_user user;
    const char *error_code = NULL;
    const char *error_message = NULL;
    sqlite3 *db;
    sqlite3_stmt *statement = NULL;
    const char *sql =
        "SELECT kind, attempt_id, room_id, title, topic, difficulty, score, correct_count, "
        "       total, duration_seconds, completed_at, state "
        "FROM ("
        "  SELECT 'PRACTICE' AS kind, s.id AS attempt_id, NULL AS room_id, 'Practice' AS title, "
        "         s.topic, s.difficulty, s.score, s.correct_count, s.question_count AS total, "
        "         s.duration_seconds, s.submitted_at AS completed_at, s.state "
        "  FROM practice_sessions s "
        "  WHERE s.user_id = ? AND s.state IN ('SUBMITTED', 'AUTO_SUBMITTED') "
        "    AND s.submitted_at IS NOT NULL "
        "  UNION ALL "
        "  SELECT 'EXAM' AS kind, p.room_id AS attempt_id, p.room_id, r.name, '', '', "
        "         p.score, p.correct_count, "
        "         (SELECT COUNT(*) FROM room_questions q WHERE q.room_id = p.room_id), "
        "         r.duration_seconds, p.submitted_at AS completed_at, p.state "
        "  FROM room_participants p JOIN exam_rooms r ON r.id = p.room_id "
        "  WHERE p.user_id = ? AND p.state IN ('SUBMITTED', 'AUTO_SUBMITTED') "
        "    AND p.submitted_at IS NOT NULL"
        ") ORDER BY completed_at DESC, kind ASC LIMIT ? OFFSET ?;";
    int limit;
    int offset;
    int emitted = 0;
    bool has_more = false;
    bool first = true;
    char *data_json;
    size_t used = 0U;

    if (!require_session(token, &user, &error_code, &error_message)) {
        send_error(conn->socket_fd, request_id, error_code, error_message);
        return;
    }
    if (!parse_pagination(payload_json, &limit, &offset)) {
        send_error(conn->socket_fd, request_id, "BAD_REQUEST", "limit must be 1-50 and offset must be non-negative");
        return;
    }
    data_json = (char *)malloc(KZ_MAX_NDJSON_LINE_BYTES - 512U);
    if (data_json == NULL) {
        send_error(conn->socket_fd, request_id, "INTERNAL_ERROR", "Out of memory");
        return;
    }
    if (!append_format(data_json, KZ_MAX_NDJSON_LINE_BYTES - 512U, &used, "{\"attempts\":[")) {
        free(data_json);
        send_error(conn->socket_fd, request_id, "INTERNAL_ERROR", "Could not build history");
        return;
    }
    db = kz_db_lock();
    if (db == NULL || sqlite3_prepare_v2(db, sql, -1, &statement, NULL) != SQLITE_OK) {
        kz_db_unlock();
        free(data_json);
        send_error(conn->socket_fd, request_id, "INTERNAL_ERROR", "Could not read history");
        return;
    }
    (void)sqlite3_bind_int(statement, 1, user.id);
    (void)sqlite3_bind_int(statement, 2, user.id);
    (void)sqlite3_bind_int(statement, 3, limit + 1);
    (void)sqlite3_bind_int(statement, 4, offset);
    while (sqlite3_step(statement) == SQLITE_ROW) {
        if (emitted >= limit) {
            has_more = true;
            break;
        }
        if (!append_history_entry(data_json, KZ_MAX_NDJSON_LINE_BYTES - 512U, &used,
                                  statement, first)) {
            sqlite3_finalize(statement);
            kz_db_unlock();
            free(data_json);
            send_error(conn->socket_fd, request_id, "INTERNAL_ERROR", "History response is too large");
            return;
        }
        first = false;
        emitted++;
    }
    sqlite3_finalize(statement);
    kz_log_event_db(db, user.id, "HISTORY_VIEWED", "user", "self", "{}");
    kz_db_unlock();
    if (!append_format(data_json, KZ_MAX_NDJSON_LINE_BYTES - 512U, &used,
        "],\"limit\":%d,\"offset\":%d,\"has_more\":%s}",
        limit, offset, has_more ? "true" : "false")) {
        free(data_json);
        send_error(conn->socket_fd, request_id, "INTERNAL_ERROR", "Could not build history");
        return;
    }
    (void)send_ok_data(conn->socket_fd, request_id, data_json);
    free(data_json);
}

static bool load_summary(sqlite3 *db, int user_id, int *out_attempts,
                         double *out_score_sum, int *out_correct, int *out_total) {
    sqlite3_stmt *statement = NULL;
    const char *sql =
        "SELECT COUNT(*), COALESCE(SUM(score), 0.0), COALESCE(SUM(correct_count), 0), "
        "       COALESCE(SUM(total), 0) FROM ("
        "  SELECT score, correct_count, question_count AS total FROM practice_sessions "
        "  WHERE user_id = ? AND state IN ('SUBMITTED', 'AUTO_SUBMITTED') "
        "  UNION ALL "
        "  SELECT p.score, p.correct_count, "
        "         (SELECT COUNT(*) FROM room_questions q WHERE q.room_id = p.room_id) "
        "  FROM room_participants p "
        "  WHERE p.user_id = ? AND p.state IN ('SUBMITTED', 'AUTO_SUBMITTED')"
        ");";
    bool ok = false;

    if (sqlite3_prepare_v2(db, sql, -1, &statement, NULL) != SQLITE_OK) {
        return false;
    }
    (void)sqlite3_bind_int(statement, 1, user_id);
    (void)sqlite3_bind_int(statement, 2, user_id);
    if (sqlite3_step(statement) == SQLITE_ROW) {
        *out_attempts = sqlite3_column_int(statement, 0);
        *out_score_sum = sqlite3_column_double(statement, 1);
        *out_correct = sqlite3_column_int(statement, 2);
        *out_total = sqlite3_column_int(statement, 3);
        ok = true;
    }
    sqlite3_finalize(statement);
    return ok;
}

static bool add_topic_stat(kz_topic_stat *buckets, size_t *count,
                           const char *topic, const char *difficulty,
                           int correct_count, int total) {
    const char *safe_topic = (topic != NULL && topic[0] != '\0') ? topic : "Khác";
    const char *safe_difficulty = (difficulty != NULL && difficulty[0] != '\0')
        ? difficulty : "unknown";

    for (size_t index = 0U; index < *count; index++) {
        if (strcmp(buckets[index].topic, safe_topic) == 0 &&
            strcmp(buckets[index].difficulty, safe_difficulty) == 0) {
            buckets[index].correct_count += correct_count;
            buckets[index].total += total;
            return true;
        }
    }
    if (*count >= KZ_MAX_STAT_BUCKETS) {
        return false;
    }
    (void)snprintf(buckets[*count].topic, sizeof(buckets[*count].topic), "%s", safe_topic);
    (void)snprintf(buckets[*count].difficulty, sizeof(buckets[*count].difficulty), "%s", safe_difficulty);
    buckets[*count].correct_count = correct_count;
    buckets[*count].total = total;
    (*count)++;
    return true;
}

static bool load_topic_stats(sqlite3 *db, int user_id, kz_topic_stat *buckets,
                             size_t *bucket_count) {
    sqlite3_stmt *statement = NULL;
    const char *practice_sql =
        "SELECT COALESCE(NULLIF(q.topic_snapshot, ''), s.topic), "
        "       COALESCE(NULLIF(q.difficulty_snapshot, ''), s.difficulty), COUNT(*), "
        "       COALESCE(SUM(CASE WHEN a.selected_option_position = q.correct_option_position "
        "                         THEN 1 ELSE 0 END), 0) "
        "FROM practice_sessions s "
        "JOIN practice_session_questions q ON q.session_id = s.id "
        "LEFT JOIN practice_answers a ON a.session_id = q.session_id AND a.question_id = q.question_id "
        "WHERE s.user_id = ? AND s.state IN ('SUBMITTED', 'AUTO_SUBMITTED') "
        "GROUP BY 1, 2;";
    const char *exam_sql =
        "SELECT COALESCE(NULLIF(rq.topic_snapshot, ''), COALESCE(q.topic, '')), "
        "       COALESCE(NULLIF(rq.difficulty_snapshot, ''), COALESCE(q.difficulty, '')), COUNT(*), "
        "       COALESCE(SUM(CASE WHEN a.selected_option_id = rq.correct_option_snapshot "
        "                         THEN 1 ELSE 0 END), 0) "
        "FROM room_participants p "
        "JOIN room_questions rq ON rq.room_id = p.room_id "
        "LEFT JOIN questions q ON q.id = rq.question_id "
        "LEFT JOIN attempt_answers a ON a.room_id = rq.room_id AND a.question_id = rq.question_id "
        " AND a.user_id = p.user_id "
        "WHERE p.user_id = ? AND p.state IN ('SUBMITTED', 'AUTO_SUBMITTED') "
        "GROUP BY 1, 2;";
    const char *queries[] = {practice_sql, exam_sql};

    *bucket_count = 0U;
    for (size_t query_index = 0U; query_index < sizeof(queries) / sizeof(queries[0]); query_index++) {
        if (sqlite3_prepare_v2(db, queries[query_index], -1, &statement, NULL) != SQLITE_OK) {
            return false;
        }
        (void)sqlite3_bind_int(statement, 1, user_id);
        while (sqlite3_step(statement) == SQLITE_ROW) {
            if (!add_topic_stat(buckets, bucket_count,
                                (const char *)sqlite3_column_text(statement, 0),
                                (const char *)sqlite3_column_text(statement, 1),
                                sqlite3_column_int(statement, 3), sqlite3_column_int(statement, 2))) {
                sqlite3_finalize(statement);
                return false;
            }
        }
        sqlite3_finalize(statement);
        statement = NULL;
    }
    return true;
}

static int date_ordinal(const char *date_text) {
    int year;
    int month;
    int day;
    static const int month_days[] = {31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31};
    int days_before_month = 0;
    int prior_year;

    if (date_text == NULL || sscanf(date_text, "%d-%d-%d", &year, &month, &day) != 3 ||
        year < 1 || month < 1 || month > 12 || day < 1 || day > month_days[month - 1] +
        ((month == 2 && ((year % 4 == 0 && year % 100 != 0) || year % 400 == 0)) ? 1 : 0)) {
        return -1;
    }
    for (int index = 1; index < month; index++) {
        days_before_month += month_days[index - 1];
    }
    if (month > 2 && ((year % 4 == 0 && year % 100 != 0) || year % 400 == 0)) {
        days_before_month++;
    }
    prior_year = year - 1;
    return prior_year * 365 + prior_year / 4 - prior_year / 100 + prior_year / 400 +
           days_before_month + day;
}

static bool load_streak_days(sqlite3 *db, int user_id, int *out_streak_days) {
    sqlite3_stmt *statement = NULL;
    const char *sql =
        "SELECT date(completed_at) FROM ("
        " SELECT submitted_at AS completed_at FROM practice_sessions "
        " WHERE user_id = ? AND state IN ('SUBMITTED', 'AUTO_SUBMITTED') AND submitted_at IS NOT NULL "
        " UNION ALL "
        " SELECT submitted_at AS completed_at FROM room_participants "
        " WHERE user_id = ? AND state IN ('SUBMITTED', 'AUTO_SUBMITTED') AND submitted_at IS NOT NULL"
        ") GROUP BY date(completed_at) ORDER BY date(completed_at) DESC;";
    int previous_day = -1;
    int streak = 0;

    if (sqlite3_prepare_v2(db, sql, -1, &statement, NULL) != SQLITE_OK) {
        return false;
    }
    (void)sqlite3_bind_int(statement, 1, user_id);
    (void)sqlite3_bind_int(statement, 2, user_id);
    while (sqlite3_step(statement) == SQLITE_ROW) {
        int current_day = date_ordinal((const char *)sqlite3_column_text(statement, 0));
        if (current_day < 0 || (previous_day >= 0 && current_day != previous_day - 1)) {
            break;
        }
        streak++;
        previous_day = current_day;
    }
    sqlite3_finalize(statement);
    *out_streak_days = streak;
    return true;
}

void handle_get_my_stats(kz_connection *conn, const char *request_id,
                         const char *token, const char *payload_json) {
    kz_auth_user user;
    const char *error_code = NULL;
    const char *error_message = NULL;
    sqlite3 *db;
    kz_topic_stat buckets[KZ_MAX_STAT_BUCKETS];
    size_t bucket_count = 0U;
    int attempts = 0;
    int correct_count = 0;
    int total = 0;
    int streak_days = 0;
    double score_sum = 0.0;
    char *data_json;
    size_t used = 0U;
    bool first = true;

    (void)payload_json;
    if (!require_session(token, &user, &error_code, &error_message)) {
        send_error(conn->socket_fd, request_id, error_code, error_message);
        return;
    }
    db = kz_db_lock();
    if (db == NULL || !load_summary(db, user.id, &attempts, &score_sum, &correct_count, &total) ||
        !load_topic_stats(db, user.id, buckets, &bucket_count) ||
        !load_streak_days(db, user.id, &streak_days)) {
        kz_db_unlock();
        send_error(conn->socket_fd, request_id, "INTERNAL_ERROR", "Could not calculate statistics");
        return;
    }
    data_json = (char *)malloc(KZ_MAX_NDJSON_LINE_BYTES - 512U);
    if (data_json == NULL) {
        kz_db_unlock();
        send_error(conn->socket_fd, request_id, "INTERNAL_ERROR", "Out of memory");
        return;
    }
    if (!append_format(data_json, KZ_MAX_NDJSON_LINE_BYTES - 512U, &used,
        "{\"attempts\":%d,\"average_score\":%.2f,\"correct_count\":%d,"
        "\"total_questions\":%d,\"accuracy_percent\":%.2f,\"streak_days\":%d,\"by_topic\":[",
        attempts, attempts > 0 ? score_sum / (double)attempts : 0.0, correct_count, total,
        total > 0 ? 100.0 * (double)correct_count / (double)total : 0.0, streak_days)) {
        free(data_json);
        kz_db_unlock();
        send_error(conn->socket_fd, request_id, "INTERNAL_ERROR", "Could not build statistics");
        return;
    }
    for (size_t index = 0U; index < bucket_count; index++) {
        char escaped_topic[130];
        char escaped_difficulty[32];
        json_escape(buckets[index].topic, escaped_topic, sizeof(escaped_topic));
        json_escape(buckets[index].difficulty, escaped_difficulty, sizeof(escaped_difficulty));
        if (!append_format(data_json, KZ_MAX_NDJSON_LINE_BYTES - 512U, &used,
            "%s{\"topic\":\"%s\",\"difficulty\":\"%s\",\"correct_count\":%d,"
            "\"total\":%d,\"accuracy_percent\":%.2f}", first ? "" : ",",
            escaped_topic, escaped_difficulty, buckets[index].correct_count, buckets[index].total,
            buckets[index].total > 0 ? 100.0 * (double)buckets[index].correct_count /
                                       (double)buckets[index].total : 0.0)) {
            free(data_json);
            kz_db_unlock();
            send_error(conn->socket_fd, request_id, "INTERNAL_ERROR", "Statistics response is too large");
            return;
        }
        first = false;
    }
    kz_log_event_db(db, user.id, "STATS_VIEWED", "user", "self", "{}");
    kz_db_unlock();
    if (!append_format(data_json, KZ_MAX_NDJSON_LINE_BYTES - 512U, &used, "]}")) {
        free(data_json);
        send_error(conn->socket_fd, request_id, "INTERNAL_ERROR", "Could not build statistics");
        return;
    }
    (void)send_ok_data(conn->socket_fd, request_id, data_json);
    free(data_json);
}

void handle_get_leaderboard(kz_connection *conn, const char *request_id,
                            const char *token, const char *payload_json) {
    kz_auth_user user;
    const char *error_code = NULL;
    const char *error_message = NULL;
    sqlite3 *db;
    sqlite3_stmt *statement = NULL;
    sqlite3_stmt *entries = NULL;
    int room_id = 0;
    int limit;
    int offset;
    int total_questions = 0;
    int emitted = 0;
    bool first = true;
    bool has_more = false;
    char room_name[256] = {0};
    char *data_json = NULL;
    size_t used = 0U;
    char room_id_text[32];

    if (!require_session(token, &user, &error_code, &error_message)) {
        send_error(conn->socket_fd, request_id, error_code, error_message);
        return;
    }
    if (!find_json_int_member(payload_json, "room_id", &room_id) || room_id <= 0 ||
        !parse_pagination(payload_json, &limit, &offset)) {
        send_error(conn->socket_fd, request_id, "BAD_REQUEST",
                   "room_id is required; limit must be 1-50 and offset must be non-negative");
        return;
    }
    db = kz_db_lock();
    if (db == NULL) {
        kz_db_unlock();
        send_error(conn->socket_fd, request_id, "INTERNAL_ERROR", "Database error");
        return;
    }
    if (sqlite3_prepare_v2(db,
        "SELECT name, status, (SELECT COUNT(*) FROM room_questions WHERE room_id = exam_rooms.id) "
        "FROM exam_rooms WHERE id = ?;", -1, &statement, NULL) != SQLITE_OK) {
        error_code = "INTERNAL_ERROR";
        error_message = "Could not read room";
        goto error;
    }
    (void)sqlite3_bind_int(statement, 1, room_id);
    if (sqlite3_step(statement) != SQLITE_ROW) {
        error_code = "NOT_FOUND";
        error_message = "Room not found";
        goto error;
    }
    {
        const char *name = (const char *)sqlite3_column_text(statement, 0);
        const char *status = (const char *)sqlite3_column_text(statement, 1);
        (void)snprintf(room_name, sizeof(room_name), "%s", name ? name : "");
        if (status == NULL || strcmp(status, "ENDED") != 0) {
            error_code = "CONFLICT";
            error_message = "Leaderboard is available only after the room has ended";
            goto error;
        }
    }
    total_questions = sqlite3_column_int(statement, 2);
    sqlite3_finalize(statement);
    statement = NULL;

    data_json = (char *)malloc(KZ_MAX_NDJSON_LINE_BYTES - 512U);
    if (data_json == NULL) {
        error_code = "INTERNAL_ERROR";
        error_message = "Out of memory";
        goto error;
    }
    {
        char escaped_name[512];
        json_escape(room_name, escaped_name, sizeof(escaped_name));
        if (!append_format(data_json, KZ_MAX_NDJSON_LINE_BYTES - 512U, &used,
            "{\"room_id\":%d,\"room_name\":\"%s\",\"entries\":[", room_id, escaped_name)) {
            error_code = "INTERNAL_ERROR";
            error_message = "Could not build leaderboard";
            goto error;
        }
    }
    if (sqlite3_prepare_v2(db,
        "SELECT p.user_id, u.username, p.state, p.score, p.correct_count, p.submitted_at "
        "FROM room_participants p JOIN users u ON u.id = p.user_id "
        "WHERE p.room_id = ? AND p.state IN ('SUBMITTED', 'AUTO_SUBMITTED') "
        "ORDER BY p.score DESC, CASE WHEN p.submitted_at IS NULL THEN 1 ELSE 0 END, "
        "p.submitted_at ASC, p.user_id ASC LIMIT ? OFFSET ?;",
        -1, &entries, NULL) != SQLITE_OK) {
        error_code = "INTERNAL_ERROR";
        error_message = "Could not read leaderboard";
        goto error;
    }
    (void)sqlite3_bind_int(entries, 1, room_id);
    (void)sqlite3_bind_int(entries, 2, limit + 1);
    (void)sqlite3_bind_int(entries, 3, offset);
    while (sqlite3_step(entries) == SQLITE_ROW) {
        const char *username;
        const char *state;
        const char *submitted_at;
        char escaped_username[128];
        char escaped_state[32];
        char escaped_submitted_at[64];
        if (emitted >= limit) {
            has_more = true;
            break;
        }
        username = (const char *)sqlite3_column_text(entries, 1);
        state = (const char *)sqlite3_column_text(entries, 2);
        submitted_at = (const char *)sqlite3_column_text(entries, 5);
        json_escape(username ? username : "", escaped_username, sizeof(escaped_username));
        json_escape(state ? state : "", escaped_state, sizeof(escaped_state));
        json_escape(submitted_at ? submitted_at : "", escaped_submitted_at, sizeof(escaped_submitted_at));
        if (!append_format(data_json, KZ_MAX_NDJSON_LINE_BYTES - 512U, &used,
            "%s{\"rank\":%d,\"user_id\":%d,\"username\":\"%s\",\"state\":\"%s\","
            "\"score\":%.2f,\"correct_count\":%d,\"total\":%d,",
            first ? "" : ",", offset + emitted + 1, sqlite3_column_int(entries, 0),
            escaped_username, escaped_state, sqlite3_column_double(entries, 3),
            sqlite3_column_int(entries, 4), total_questions) ||
            (submitted_at != NULL
                ? !append_format(data_json, KZ_MAX_NDJSON_LINE_BYTES - 512U, &used,
                                 "\"submitted_at\":\"%s\"}", escaped_submitted_at)
                : !append_format(data_json, KZ_MAX_NDJSON_LINE_BYTES - 512U, &used,
                                 "\"submitted_at\":null}"))) {
            error_code = "INTERNAL_ERROR";
            error_message = "Leaderboard response is too large";
            goto error;
        }
        first = false;
        emitted++;
    }
    sqlite3_finalize(entries);
    entries = NULL;
    (void)snprintf(room_id_text, sizeof(room_id_text), "%d", room_id);
    kz_log_event_db(db, user.id, "LEADERBOARD_VIEWED", "exam_room", room_id_text, "{}");
    kz_db_unlock();
    if (!append_format(data_json, KZ_MAX_NDJSON_LINE_BYTES - 512U, &used,
        "],\"limit\":%d,\"offset\":%d,\"has_more\":%s}",
        limit, offset, has_more ? "true" : "false")) {
        free(data_json);
        send_error(conn->socket_fd, request_id, "INTERNAL_ERROR", "Could not build leaderboard");
        return;
    }
    (void)send_ok_data(conn->socket_fd, request_id, data_json);
    free(data_json);
    return;

error:
    sqlite3_finalize(statement);
    sqlite3_finalize(entries);
    kz_db_unlock();
    free(data_json);
    send_error(conn->socket_fd, request_id, error_code, error_message);
}
