#ifndef KUIZUHUB_DB_H
#define KUIZUHUB_DB_H

#include <stdbool.h>
#include <sqlite3.h>

/**
 * Initialize the shared SQLite database connection, enable WAL mode,
 * foreign keys, busy timeout, and ensure the schema exists.
 */
bool kz_db_init(const char *db_path, const char *migration_path);

/**
 * Close the shared SQLite database connection.
 */
void kz_db_close(void);

/**
 * Acquire the global database mutex and return the active sqlite3 handle.
 * Caller MUST call kz_db_unlock() after finishing its database operation.
 */
sqlite3 *kz_db_lock(void);

/**
 * Release the global database mutex.
 */
void kz_db_unlock(void);

#endif
