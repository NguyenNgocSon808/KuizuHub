#ifndef KUIZUHUB_CONFIG_H
#define KUIZUHUB_CONFIG_H

#define KZ_DEFAULT_PORT 5050
#define KZ_BIND_ADDRESS "0.0.0.0"
#define KZ_DATABASE_PATH "data/exam.db"
#define KZ_MIGRATION_PATH "migrations/001_initial.sql"
#define KZ_MIGRATION_002_PATH "migrations/002_question_explanation.sql"
#define KZ_MIGRATION_003_PATH "migrations/003_practice_sessions.sql"
#define KZ_MIGRATION_004_PATH "migrations/004_room_question_options.sql"
#define KZ_MIGRATION_005_PATH "migrations/005_profile_analytics.sql"
#define KZ_LOG_DIR "logs"
#define KZ_LOG_FILE_PATH "logs/server.log"
#define KZ_MAX_NDJSON_LINE_BYTES (64U * 1024U)
/* A room can contain 800 questions with options and review explanations. */
#define KZ_MAX_NDJSON_RESPONSE_BYTES (8U * 1024U * 1024U)
#define KZ_RECEIVE_BUFFER_BYTES 4096U
#define KZ_SESSION_TTL_HOURS 24
#define KZ_PBKDF2_ITERATIONS 100000
#define KZ_SOCKET_IDLE_TIMEOUT_SEC 300
#define KZ_RATE_LIMIT_USER_MAX 5
#define KZ_RATE_LIMIT_IP_MAX 20
#define KZ_RATE_LIMIT_WINDOW_SEC 60

#endif
