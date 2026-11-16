#ifndef KUIZUHUB_QUESTION_H
#define KUIZUHUB_QUESTION_H

#include "protocol.h"

/* Request handlers owned by Person 3: question-bank administration. */
void handle_list_questions(kz_connection *conn, const char *request_id,
                           const char *token, const char *payload_json);
void handle_create_question(kz_connection *conn, const char *request_id,
                            const char *token, const char *payload_json);
void handle_update_question(kz_connection *conn, const char *request_id,
                            const char *token, const char *payload_json);
void handle_import_questions(kz_connection *conn, const char *request_id,
                             const char *token, const char *payload_json);

#endif
