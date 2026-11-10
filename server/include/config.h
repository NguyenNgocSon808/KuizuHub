#ifndef KUIZUHUB_CONFIG_H
#define KUIZUHUB_CONFIG_H

#define KZ_DEFAULT_PORT 5050
#define KZ_BIND_ADDRESS "0.0.0.0"
#define KZ_DATABASE_PATH "data/exam.db"
#define KZ_MIGRATION_PATH "migrations/001_initial.sql"
#define KZ_LOG_DIR "logs"
#define KZ_LOG_FILE_PATH "logs/server.log"
#define KZ_MAX_NDJSON_LINE_BYTES (64U * 1024U)
#define KZ_RECEIVE_BUFFER_BYTES 4096U
#define KZ_SESSION_TTL_HOURS 24
#define KZ_PBKDF2_ITERATIONS 100000

#endif
