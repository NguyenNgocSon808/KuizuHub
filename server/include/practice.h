#ifndef KUIZUHUB_PRACTICE_H
#define KUIZUHUB_PRACTICE_H

#include "protocol.h"

void handle_start_practice(kz_connection *conn, const char *request_id,
                           const char *token, const char *payload_json);
void handle_save_practice_answer(kz_connection *conn, const char *request_id,
                                 const char *token, const char *payload_json);
void handle_submit_practice(kz_connection *conn, const char *request_id,
                            const char *token, const char *payload_json);
void process_expired_practice(void);

#endif /* KUIZUHUB_PRACTICE_H */
