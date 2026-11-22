#ifndef KUIZUHUB_ROOM_H
#define KUIZUHUB_ROOM_H

#include "protocol.h"

void handle_create_room(kz_connection *conn, const char *request_id,
                        const char *token, const char *payload_json);
void handle_join_room(kz_connection *conn, const char *request_id,
                      const char *token, const char *payload_json);
void handle_start_room(kz_connection *conn, const char *request_id,
                       const char *token, const char *payload_json);
void handle_get_exam(kz_connection *conn, const char *request_id,
                     const char *token, const char *payload_json);
void handle_save_answer(kz_connection *conn, const char *request_id,
                        const char *token, const char *payload_json);
void handle_submit_exam(kz_connection *conn, const char *request_id,
                        const char *token, const char *payload_json);

/* Run one or more short transactions to close every room whose ended_at passed. */
void process_expired_rooms(void);

#endif /* KUIZUHUB_ROOM_H */
