#ifndef KUIZUHUB_HISTORY_H
#define KUIZUHUB_HISTORY_H

#include "protocol.h"

/* Read-only Phase 3 analytics handlers. */
void handle_get_my_history(kz_connection *conn, const char *request_id,
                           const char *token, const char *payload_json);
void handle_get_my_stats(kz_connection *conn, const char *request_id,
                         const char *token, const char *payload_json);
void handle_get_leaderboard(kz_connection *conn, const char *request_id,
                            const char *token, const char *payload_json);

#endif /* KUIZUHUB_HISTORY_H */
