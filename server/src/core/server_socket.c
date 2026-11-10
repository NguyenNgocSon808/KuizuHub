#include "server_socket.h"
#include "auth.h"
#include "config.h"
#include "log.h"
#include "protocol.h"

#include <errno.h>
#include <pthread.h>
#include <signal.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

static volatile sig_atomic_t g_running = 1;
static kz_socket_t g_listening_socket = KZ_INVALID_SOCKET;

typedef struct {
    kz_socket_t socket_fd;
    char peer_ip[64];
    int peer_port;
} client_accept_info;

void kz_server_stop(void) {
    g_running = 0;
    if (g_listening_socket != KZ_INVALID_SOCKET) {
        KZ_CLOSE_SOCKET(g_listening_socket);
        g_listening_socket = KZ_INVALID_SOCKET;
    }
}

void handle_message(kz_connection *conn, const char *line) {
    char request_id[KZ_REQUEST_ID_BYTES];
    char type[KZ_TYPE_BYTES];
    char token[KZ_TOKEN_BYTES];
    char *payload_json = NULL;

    if (!is_json_object(line)) {
        kz_log_event(0, "PROTOCOL_ERROR", "connection", conn->peer_ip,
                     "{\"reason\":\"invalid_json_object\"}");
        send_error(conn->socket_fd, NULL, "BAD_REQUEST", "Message must be a JSON object");
        return;
    }
    if (!find_json_string_member(line, "request_id", request_id, sizeof(request_id))) {
        kz_log_event(0, "PROTOCOL_ERROR", "connection", conn->peer_ip,
                     "{\"reason\":\"missing_request_id\"}");
        send_error(conn->socket_fd, NULL, "BAD_REQUEST", "request_id must be a JSON string");
        return;
    }
    if (!find_json_string_member(line, "type", type, sizeof(type))) {
        kz_log_event(0, "PROTOCOL_ERROR", "connection", conn->peer_ip,
                     "{\"reason\":\"missing_type\"}");
        send_error(conn->socket_fd, request_id, "BAD_REQUEST", "type must be a JSON string");
        return;
    }

    token[0] = '\0';
    (void)find_json_string_member(line, "token", token, sizeof(token));

    payload_json = (char *)malloc(KZ_MAX_NDJSON_LINE_BYTES);
    if (payload_json == NULL) {
        send_error(conn->socket_fd, request_id, "INTERNAL_ERROR", "Out of memory");
        return;
    }
    if (!find_json_object_member(line, "payload", payload_json, KZ_MAX_NDJSON_LINE_BYTES)) {
        strcpy(payload_json, "{}");
    }

    if (strcmp(type, "PING") == 0) {
        (void)send_ok_data(conn->socket_fd, request_id, "{\"message\":\"pong\"}");
    } else if (strcmp(type, "REGISTER") == 0) {
        handle_register(conn, request_id, payload_json);
    } else if (strcmp(type, "LOGIN") == 0) {
        handle_login(conn, request_id, payload_json);
    } else if (strcmp(type, "LOGOUT") == 0) {
        handle_logout(conn, request_id, token);
    } else if (strcmp(type, "GET_MY_PROFILE") == 0) {
        handle_get_my_profile(conn, request_id, token);
    } else if (strcmp(type, "LIST_ROOMS") == 0) {
        handle_list_rooms(conn, request_id, token);
    } else if (strcmp(type, "START_ROOM") == 0) {
        handle_start_room_guard(conn, request_id, token, payload_json);
    } else if (strcmp(type, "END_ROOM") == 0) {
        handle_end_room_guard(conn, request_id, token, payload_json);
    } else {
        send_error(conn->socket_fd, request_id, "NOT_FOUND", "Unsupported request type");
    }

    free(payload_json);
}

static void *client_worker(void *argument) {
    client_accept_info *info = (client_accept_info *)argument;
    kz_connection *conn = (kz_connection *)malloc(sizeof(*conn));
    char detail[128];

    if (conn == NULL) {
        KZ_CLOSE_SOCKET(info->socket_fd);
        free(info);
        return NULL;
    }

    connection_init(conn, info->socket_fd, info->peer_ip, info->peer_port);
    free(info);

    snprintf(detail, sizeof(detail), "{\"ip\":\"%s\",\"port\":%d}",
             conn->peer_ip, conn->peer_port);
    kz_log_event(0, "CONNECTION_OPENED", "connection", conn->peer_ip, detail);

    connection_read_lines(conn, handle_message);

    kz_log_event(0, "CONNECTION_CLOSED", "connection", conn->peer_ip, detail);
    KZ_CLOSE_SOCKET(conn->socket_fd);
    free(conn);
    return NULL;
}

int kz_server_run(int port) {
    struct sockaddr_in address;
    int option = 1;

    g_running = 1;
    g_listening_socket = socket(AF_INET, SOCK_STREAM, 0);
    if (g_listening_socket == KZ_INVALID_SOCKET) {
        perror("socket");
        return -1;
    }
    if (setsockopt(g_listening_socket, SOL_SOCKET, SO_REUSEADDR,
                   (const char *)&option, sizeof(option)) < 0) {
        perror("setsockopt");
        KZ_CLOSE_SOCKET(g_listening_socket);
        g_listening_socket = KZ_INVALID_SOCKET;
        return -1;
    }

    memset(&address, 0, sizeof(address));
    address.sin_family = AF_INET;
    address.sin_addr.s_addr = htonl(INADDR_ANY);
    address.sin_port = htons((uint16_t)port);
    if (bind(g_listening_socket, (struct sockaddr *)&address, sizeof(address)) < 0) {
        perror("bind");
        KZ_CLOSE_SOCKET(g_listening_socket);
        g_listening_socket = KZ_INVALID_SOCKET;
        return -1;
    }
    if (listen(g_listening_socket, SOMAXCONN) < 0) {
        perror("listen");
        KZ_CLOSE_SOCKET(g_listening_socket);
        g_listening_socket = KZ_INVALID_SOCKET;
        return -1;
    }

    printf("KuizuHub server listening on %s:%d (DB: %s)\n",
           KZ_BIND_ADDRESS, port, KZ_DATABASE_PATH);
    fflush(stdout);

    while (g_running) {
        struct sockaddr_in peer_addr;
#ifdef _WIN32
        int peer_len = (int)sizeof(peer_addr);
#else
        socklen_t peer_len = sizeof(peer_addr);
#endif
        kz_socket_t client_fd;
        client_accept_info *info;
        pthread_t worker;

        memset(&peer_addr, 0, sizeof(peer_addr));
        client_fd = accept(g_listening_socket, (struct sockaddr *)&peer_addr, &peer_len);
        if (client_fd == KZ_INVALID_SOCKET) {
            if (errno == EINTR || !g_running) {
                continue;
            }
            perror("accept");
            continue;
        }

        info = (client_accept_info *)malloc(sizeof(*info));
        if (info == NULL) {
            KZ_CLOSE_SOCKET(client_fd);
            continue;
        }
        info->socket_fd = client_fd;
        if (inet_ntop(AF_INET, &peer_addr.sin_addr, info->peer_ip, sizeof(info->peer_ip)) == NULL) {
            strcpy(info->peer_ip, "127.0.0.1");
        }
        info->peer_port = (int)ntohs(peer_addr.sin_port);

        if (pthread_create(&worker, NULL, client_worker, info) != 0) {
            perror("pthread_create");
            KZ_CLOSE_SOCKET(client_fd);
            free(info);
            continue;
        }
        (void)pthread_detach(worker);
    }

    if (g_listening_socket != KZ_INVALID_SOCKET) {
        KZ_CLOSE_SOCKET(g_listening_socket);
        g_listening_socket = KZ_INVALID_SOCKET;
    }
    return 0;
}
