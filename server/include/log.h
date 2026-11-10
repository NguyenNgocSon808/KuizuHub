#ifndef KUIZUHUB_LOG_H
#define KUIZUHUB_LOG_H

#include <sqlite3.h>

/**
 * Record an activity log entry to both `logs/server.log` and SQLite `activity_logs`
 * when the caller already holds `kz_db_lock()`.
 *
 * Pass actor_id <= 0 when the actor is unauthenticated or system-level.
 * NEVER pass plaintext passwords, password hashes, or session tokens in detail_json.
 */
void kz_log_event_db(sqlite3 *db, int actor_id, const char *action,
                     const char *entity_type, const char *entity_id,
                     const char *detail_json);

/**
 * Record an activity log entry to both `logs/server.log` and SQLite `activity_logs`
 * (acquires and releases `kz_db_lock()` internally).
 */
void kz_log_event(int actor_id, const char *action,
                  const char *entity_type, const char *entity_id,
                  const char *detail_json);

#endif
