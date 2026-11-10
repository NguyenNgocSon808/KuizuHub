#ifndef KUIZUHUB_PROTOCOL_H
#define KUIZUHUB_PROTOCOL_H

#include "config.h"

#include <stdbool.h>
#include <stddef.h>

#ifdef _WIN32
#include <winsock2.h>
#include <ws2tcpip.h>
typedef SOCKET kz_socket_t;
#define KZ_INVALID_SOCKET INVALID_SOCKET
#define KZ_CLOSE_SOCKET(s) closesocket(s)
#else
#include <arpa/inet.h>
#include <netinet/in.h>
#include <sys/socket.h>
#include <sys/types.h>
#include <unistd.h>
typedef int kz_socket_t;
#define KZ_INVALID_SOCKET (-1)
#define KZ_CLOSE_SOCKET(s) close(s)
#endif

#define KZ_REQUEST_ID_BYTES 128U
#define KZ_TYPE_BYTES 64U
#define KZ_TOKEN_BYTES 128U

typedef struct {
    kz_socket_t socket_fd;
    char peer_ip[64];
    int peer_port;
    char line_buffer[KZ_MAX_NDJSON_LINE_BYTES + 1U];
    size_t used;
    bool overflowing;
} kz_connection;

typedef void (*kz_line_handler_fn)(kz_connection *conn, const char *line);

void connection_init(kz_connection *conn, kz_socket_t socket_fd,
                     const char *peer_ip, int peer_port);

/**
 * Read bytes from the client socket into its dedicated per-connection buffer,
 * split complete NDJSON lines on '\n', and invoke `handler` for each line.
 */
void connection_read_lines(kz_connection *conn, kz_line_handler_fn handler);

/**
 * Send all `length` bytes of `buffer` over `socket_fd`.
 * Returns 0 on success, -1 on error.
 */
int send_all(kz_socket_t socket_fd, const char *buffer, size_t length);

/**
 * Send a standard OK envelope:
 * {"type":"OK","request_id":"...","data":<data_json>}\n
 */
int send_ok_data(kz_socket_t socket_fd, const char *request_id, const char *data_json);

/**
 * Send a standard ERROR envelope:
 * {"type":"ERROR","request_id":...,"error":{"code":"...","message":"..."}}\n
 */
void send_error(kz_socket_t socket_fd, const char *request_id,
                const char *code, const char *message);

/* JSON validation & extraction helpers */
bool is_json_object(const char *line);
bool find_json_string_member(const char *json, const char *member,
                             char *output, size_t output_size);
bool find_json_int_member(const char *json, const char *member, int *output);
bool find_json_object_member(const char *json, const char *member,
                             char *output, size_t output_size);
void json_escape(const char *input, char *output, size_t output_size);

#endif
