#include "log.h"
#include "config.h"
#include "db.h"

#include <pthread.h>
#include <stdio.h>
#include <string.h>
#include <time.h>

#ifdef _WIN32
#include <direct.h>
#define KZ_MKDIR(path) _mkdir(path)
#else
#include <sys/stat.h>
#include <sys/types.h>
#define KZ_MKDIR(path) mkdir((path), 0755)
#endif

static pthread_mutex_t g_log_file_mutex = PTHREAD_MUTEX_INITIALIZER;

static void write_file_log(int actor_id, const char *action,
                           const char *entity_type, const char *entity_id,
                           const char *detail_json) {
    FILE *fp;
    time_t now = time(NULL);
    struct tm utc_tm;
    char ts[32];

    (void)KZ_MKDIR(KZ_LOG_DIR);
#ifdef _WIN32
    if (gmtime_s(&utc_tm, &now) != 0) {
        memset(&utc_tm, 0, sizeof(utc_tm));
    }
#else
    if (gmtime_r(&now, &utc_tm) == NULL) {
        memset(&utc_tm, 0, sizeof(utc_tm));
    }
#endif
    (void)strftime(ts, sizeof(ts), "%Y-%m-%dT%H:%M:%SZ", &utc_tm);

    pthread_mutex_lock(&g_log_file_mutex);
    fp = fopen(KZ_LOG_FILE_PATH, "ab");
    if (fp != NULL) {
        if (actor_id > 0) {
            fprintf(fp, "%s action=%s actor_id=%d entity=%s:%s detail=%s\n",
                    ts,
                    action ? action : "UNKNOWN",
                    actor_id,
                    entity_type ? entity_type : "system",
                    entity_id ? entity_id : "-",
                    (detail_json && detail_json[0] != '\0') ? detail_json : "{}");
        } else {
            fprintf(fp, "%s action=%s actor_id=null entity=%s:%s detail=%s\n",
                    ts,
                    action ? action : "UNKNOWN",
                    entity_type ? entity_type : "system",
                    entity_id ? entity_id : "-",
                    (detail_json && detail_json[0] != '\0') ? detail_json : "{}");
        }
        fflush(fp);
        fclose(fp);
    }
    pthread_mutex_unlock(&g_log_file_mutex);
}

void kz_log_event_db(sqlite3 *db, int actor_id, const char *action,
                     const char *entity_type, const char *entity_id,
                     const char *detail_json) {
    sqlite3_stmt *stmt = NULL;
    const char *sql =
        "INSERT INTO activity_logs(actor_id, action, entity_type, entity_id, detail_json) "
        "VALUES (?, ?, ?, ?, ?);";

    write_file_log(actor_id, action, entity_type, entity_id, detail_json);

    if (db == NULL) {
        return;
    }
    if (sqlite3_prepare_v2(db, sql, -1, &stmt, NULL) != SQLITE_OK) {
        return;
    }
    if (actor_id > 0) {
        (void)sqlite3_bind_int(stmt, 1, actor_id);
    } else {
        (void)sqlite3_bind_null(stmt, 1);
    }
    (void)sqlite3_bind_text(stmt, 2, action ? action : "UNKNOWN", -1, SQLITE_STATIC);
    (void)sqlite3_bind_text(stmt, 3, entity_type ? entity_type : "system", -1, SQLITE_STATIC);
    (void)sqlite3_bind_text(stmt, 4, entity_id ? entity_id : "-", -1, SQLITE_STATIC);
    (void)sqlite3_bind_text(stmt, 5, (detail_json && detail_json[0] != '\0') ? detail_json : "{}", -1, SQLITE_STATIC);

    (void)sqlite3_step(stmt);
    sqlite3_finalize(stmt);
}

void kz_log_event(int actor_id, const char *action,
                  const char *entity_type, const char *entity_id,
                  const char *detail_json) {
    sqlite3 *db = kz_db_lock();
    kz_log_event_db(db, actor_id, action, entity_type, entity_id, detail_json);
    kz_db_unlock();
}
