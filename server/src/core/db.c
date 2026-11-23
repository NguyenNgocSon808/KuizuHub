#include "db.h"
#include "config.h"

#include <pthread.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#ifdef _WIN32
#include <direct.h>
#define KZ_MKDIR(path) _mkdir(path)
#else
#include <sys/stat.h>
#include <sys/types.h>
#define KZ_MKDIR(path) mkdir((path), 0755)
#endif

static sqlite3 *g_db = NULL;
static pthread_mutex_t g_db_mutex = PTHREAD_MUTEX_INITIALIZER;

static void ensure_parent_dir(const char *file_path) {
    char dir_path[512];
    const char *slash = strrchr(file_path, '/');
    const char *backslash = strrchr(file_path, '\\');
    const char *sep = slash;

    if (backslash != NULL && (sep == NULL || backslash > sep)) {
        sep = backslash;
    }
    if (sep == NULL) {
        return;
    }
    size_t len = (size_t)(sep - file_path);
    if (len == 0U || len >= sizeof(dir_path)) {
        return;
    }
    memcpy(dir_path, file_path, len);
    dir_path[len] = '\0';
    (void)KZ_MKDIR(dir_path);
}

static bool has_users_table(sqlite3 *db) {
    sqlite3_stmt *stmt = NULL;
    const char *sql = "SELECT 1 FROM sqlite_master WHERE type='table' AND name='users' LIMIT 1;";
    bool exists = false;

    if (sqlite3_prepare_v2(db, sql, -1, &stmt, NULL) == SQLITE_OK) {
        if (sqlite3_step(stmt) == SQLITE_ROW) {
            exists = true;
        }
        sqlite3_finalize(stmt);
    }
    return exists;
}

static bool apply_migration_file(sqlite3 *db, const char *migration_path) {
    FILE *file = fopen(migration_path, "rb");
    long file_size;
    char *sql_buf;
    char *err_msg = NULL;
    int rc;

    if (file == NULL) {
        fprintf(stderr, "Cannot open migration file: %s\n", migration_path);
        return false;
    }
    if (fseek(file, 0, SEEK_END) != 0) {
        fclose(file);
        return false;
    }
    file_size = ftell(file);
    if (file_size < 0 || fseek(file, 0, SEEK_SET) != 0) {
        fclose(file);
        return false;
    }
    sql_buf = (char *)malloc((size_t)file_size + 1U);
    if (sql_buf == NULL) {
        fclose(file);
        return false;
    }
    if (file_size > 0 && fread(sql_buf, 1U, (size_t)file_size, file) != (size_t)file_size) {
        free(sql_buf);
        fclose(file);
        return false;
    }
    sql_buf[file_size] = '\0';
    fclose(file);

    rc = sqlite3_exec(db, sql_buf, NULL, NULL, &err_msg);
    free(sql_buf);
    if (rc != SQLITE_OK) {
        fprintf(stderr, "Migration failed: %s\n", err_msg ? err_msg : "unknown error");
        sqlite3_free(err_msg);
        return false;
    }
    return true;
}

static bool execute_sql(sqlite3 *db, const char *sql) {
    char *err_msg = NULL;
    int rc = sqlite3_exec(db, sql, NULL, NULL, &err_msg);

    if (rc == SQLITE_OK) {
        return true;
    }
    fprintf(stderr, "Database statement failed: %s\n", err_msg ? err_msg : "unknown error");
    sqlite3_free(err_msg);
    return false;
}

static bool ensure_migration_registry(sqlite3 *db) {
    return execute_sql(
        db,
        "CREATE TABLE IF NOT EXISTS schema_migrations ("
        "name TEXT PRIMARY KEY, applied_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP"
        ");"
    );
}

static bool migration_is_recorded(sqlite3 *db, const char *name) {
    sqlite3_stmt *stmt = NULL;
    bool recorded = false;

    if (sqlite3_prepare_v2(db,
                           "SELECT 1 FROM schema_migrations WHERE name = ? LIMIT 1;",
                           -1, &stmt, NULL) != SQLITE_OK) {
        return false;
    }
    (void)sqlite3_bind_text(stmt, 1, name, -1, SQLITE_STATIC);
    recorded = sqlite3_step(stmt) == SQLITE_ROW;
    sqlite3_finalize(stmt);
    return recorded;
}

static bool record_migration(sqlite3 *db, const char *name) {
    sqlite3_stmt *stmt = NULL;
    bool ok = false;

    if (sqlite3_prepare_v2(db,
                           "INSERT INTO schema_migrations(name) VALUES (?);",
                           -1, &stmt, NULL) != SQLITE_OK) {
        return false;
    }
    (void)sqlite3_bind_text(stmt, 1, name, -1, SQLITE_STATIC);
    ok = sqlite3_step(stmt) == SQLITE_DONE;
    sqlite3_finalize(stmt);
    return ok;
}

static bool questions_have_explanation_column(sqlite3 *db) {
    sqlite3_stmt *stmt = NULL;
    bool exists = false;

    if (sqlite3_prepare_v2(db, "PRAGMA table_info(questions);", -1, &stmt, NULL) != SQLITE_OK) {
        return false;
    }
    while (sqlite3_step(stmt) == SQLITE_ROW) {
        const char *column_name = (const char *)sqlite3_column_text(stmt, 1);
        if (column_name != NULL && strcmp(column_name, "explanation") == 0) {
            exists = true;
            break;
        }
    }
    sqlite3_finalize(stmt);
    return exists;
}

static bool apply_registered_migration(sqlite3 *db, const char *name,
                                       const char *migration_path) {
    bool ok;

    if (migration_is_recorded(db, name)) {
        return true;
    }
    if (!execute_sql(db, "BEGIN IMMEDIATE;")) {
        return false;
    }
    ok = apply_migration_file(db, migration_path) && record_migration(db, name);
    if (ok && execute_sql(db, "COMMIT;")) {
        return true;
    }
    (void)execute_sql(db, "ROLLBACK;");
    return false;
}

bool kz_db_init(const char *db_path, const char *migration_path) {
    char *err_msg = NULL;
    const char *path = (db_path != NULL && db_path[0] != '\0') ? db_path : KZ_DATABASE_PATH;
    const char *mig = (migration_path != NULL && migration_path[0] != '\0') ? migration_path : KZ_MIGRATION_PATH;
    bool has_explanation = false;

    pthread_mutex_lock(&g_db_mutex);
    if (g_db != NULL) {
        pthread_mutex_unlock(&g_db_mutex);
        return true;
    }

    ensure_parent_dir(path);
    if (sqlite3_open(path, &g_db) != SQLITE_OK) {
        fprintf(stderr, "Cannot open SQLite database %s: %s\n", path,
                g_db ? sqlite3_errmsg(g_db) : "out of memory");
        if (g_db != NULL) {
            sqlite3_close(g_db);
            g_db = NULL;
        }
        pthread_mutex_unlock(&g_db_mutex);
        return false;
    }

    (void)sqlite3_busy_timeout(g_db, 5000);
    if (sqlite3_exec(g_db, "PRAGMA foreign_keys = ON; PRAGMA journal_mode = WAL;", NULL, NULL, &err_msg) != SQLITE_OK) {
        fprintf(stderr, "Failed to configure SQLite PRAGMAs: %s\n", err_msg ? err_msg : "");
        sqlite3_free(err_msg);
        sqlite3_close(g_db);
        g_db = NULL;
        pthread_mutex_unlock(&g_db_mutex);
        return false;
    }

    if (!ensure_migration_registry(g_db)) {
        sqlite3_close(g_db);
        g_db = NULL;
        pthread_mutex_unlock(&g_db_mutex);
        return false;
    }

    if (!has_users_table(g_db)) {
        if (!apply_registered_migration(g_db, "001_initial", mig)) {
            sqlite3_close(g_db);
            g_db = NULL;
            pthread_mutex_unlock(&g_db_mutex);
            return false;
        }
    } else if (!migration_is_recorded(g_db, "001_initial") &&
               !record_migration(g_db, "001_initial")) {
        fprintf(stderr, "Failed to register existing initial schema\n");
        sqlite3_close(g_db);
        g_db = NULL;
        pthread_mutex_unlock(&g_db_mutex);
        return false;
    }

    has_explanation = questions_have_explanation_column(g_db);
    if (!migration_is_recorded(g_db, "002_question_explanation") &&
        ((has_explanation && !record_migration(g_db, "002_question_explanation")) ||
         (!has_explanation && !apply_registered_migration(g_db, "002_question_explanation",
                                                           KZ_MIGRATION_002_PATH)))) {
        sqlite3_close(g_db);
        g_db = NULL;
        pthread_mutex_unlock(&g_db_mutex);
        return false;
    }

    if (!apply_registered_migration(g_db, "003_practice_sessions", KZ_MIGRATION_003_PATH)) {
        sqlite3_close(g_db);
        g_db = NULL;
        pthread_mutex_unlock(&g_db_mutex);
        return false;
    }

    if (!apply_registered_migration(g_db, "004_room_question_options", KZ_MIGRATION_004_PATH)) {
        sqlite3_close(g_db);
        g_db = NULL;
        pthread_mutex_unlock(&g_db_mutex);
        return false;
    }

    if (!apply_registered_migration(g_db, "005_profile_analytics", KZ_MIGRATION_005_PATH)) {
        sqlite3_close(g_db);
        g_db = NULL;
        pthread_mutex_unlock(&g_db_mutex);
        return false;
    }

    pthread_mutex_unlock(&g_db_mutex);
    return true;
}

void kz_db_close(void) {
    pthread_mutex_lock(&g_db_mutex);
    if (g_db != NULL) {
        sqlite3_close(g_db);
        g_db = NULL;
    }
    pthread_mutex_unlock(&g_db_mutex);
}

sqlite3 *kz_db_lock(void) {
    pthread_mutex_lock(&g_db_mutex);
    return g_db;
}

void kz_db_unlock(void) {
    pthread_mutex_unlock(&g_db_mutex);
}
