#ifndef KUIZUHUB_SERVER_SOCKET_H
#define KUIZUHUB_SERVER_SOCKET_H

#include "protocol.h"

/**
 * Dispatch a single complete NDJSON line received from `conn`.
 */
void handle_message(kz_connection *conn, const char *line);

/**
 * Create a listening TCP socket with SO_REUSEADDR, bind to 0.0.0.0:port,
 * and enter the accept loop spawning a detached pthread per client.
 * Returns 0 on clean shutdown, -1 on startup error.
 */
int kz_server_run(int port);

/**
 * Signal the accept loop to stop and close the listening socket.
 */
void kz_server_stop(void);

#endif
