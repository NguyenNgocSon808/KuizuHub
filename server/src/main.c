#include "config.h"

#include <ctype.h>
#include <errno.h>
#include <pthread.h>
#include <signal.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#ifdef _WIN32
#include <winsock2.h>
#include <ws2tcpip.h>
typedef SOCKET socket_handle;
#define INVALID_SOCKET_HANDLE INVALID_SOCKET
#define CLOSE_SOCKET(socket_fd) closesocket(socket_fd)
#else
#include <arpa/inet.h>
#include <netinet/in.h>
#include <sys/socket.h>
#include <sys/types.h>
#include <unistd.h>
typedef int socket_handle;
#define INVALID_SOCKET_HANDLE (-1)
#define CLOSE_SOCKET(socket_fd) close(socket_fd)
#endif

#define RECEIVE_BUFFER_BYTES 4096U
#define REQUEST_ID_BYTES 128U
#define TYPE_BYTES 64U
#define RESPONSE_BYTES 512U

static volatile sig_atomic_t running = 1;
static socket_handle listening_socket = INVALID_SOCKET_HANDLE;

static void stop_server(int signal_number) {
    (void)signal_number;
    running = 0;
    if (listening_socket != INVALID_SOCKET_HANDLE) {
        CLOSE_SOCKET(listening_socket);
        listening_socket = INVALID_SOCKET_HANDLE;
    }
}

static int send_all(socket_handle socket_fd, const char *buffer, size_t length) {
    size_t sent = 0;

    while (sent < length) {
        int result = send(socket_fd, buffer + sent, (int)(length - sent), 0);
#ifdef _WIN32
        if (result == SOCKET_ERROR) {
            return -1;
        }
#else
        if (result < 0) {
            if (errno == EINTR) {
                continue;
            }
            return -1;
        }
#endif
        if (result == 0) {
            return -1;
        }
        sent += (size_t)result;
    }
    return 0;
}

static const char *skip_whitespace(const char *value) {
    while (*value != '\0' && isspace((unsigned char)*value)) {
        value++;
    }
    return value;
}

static bool skip_json_value(const char **value, unsigned int depth);

static bool skip_json_string(const char **value) {
    const char *cursor = *value;

    if (*cursor++ != '"') {
        return false;
    }
    while (*cursor != '\0') {
        if (*cursor == '"') {
            *value = cursor + 1;
            return true;
        }
        if ((unsigned char)*cursor < 0x20U) {
            return false;
        }
        if (*cursor++ != '\\') {
            continue;
        }
        if (strchr("\"\\/bfnrt", *cursor) != NULL) {
            cursor++;
        } else if (*cursor == 'u') {
            cursor++;
            for (unsigned int index = 0; index < 4U; index++, cursor++) {
                if (!isxdigit((unsigned char)*cursor)) {
                    return false;
                }
            }
        } else {
            return false;
        }
    }
    return false;
}

static bool skip_json_number(const char **value) {
    const char *cursor = *value;

    if (*cursor == '-') {
        cursor++;
    }
    if (*cursor == '0') {
        cursor++;
    } else if (isdigit((unsigned char)*cursor)) {
        do {
            cursor++;
        } while (isdigit((unsigned char)*cursor));
    } else {
        return false;
    }
    if (*cursor == '.') {
        cursor++;
        if (!isdigit((unsigned char)*cursor)) {
            return false;
        }
        do {
            cursor++;
        } while (isdigit((unsigned char)*cursor));
    }
    if (*cursor == 'e' || *cursor == 'E') {
        cursor++;
        if (*cursor == '+' || *cursor == '-') {
            cursor++;
        }
        if (!isdigit((unsigned char)*cursor)) {
            return false;
        }
        do {
            cursor++;
        } while (isdigit((unsigned char)*cursor));
    }
    *value = cursor;
    return true;
}

static bool skip_json_array(const char **value, unsigned int depth) {
    const char *cursor = skip_whitespace(*value + 1);

    if (*cursor == ']') {
        *value = cursor + 1;
        return true;
    }
    while (true) {
        if (!skip_json_value(&cursor, depth + 1U)) {
            return false;
        }
        cursor = skip_whitespace(cursor);
        if (*cursor == ']') {
            *value = cursor + 1;
            return true;
        }
        if (*cursor++ != ',') {
            return false;
        }
        cursor = skip_whitespace(cursor);
    }
}

static bool skip_json_object(const char **value, unsigned int depth) {
    const char *cursor = skip_whitespace(*value + 1);

    if (*cursor == '}') {
        *value = cursor + 1;
        return true;
    }
    while (true) {
        if (!skip_json_string(&cursor)) {
            return false;
        }
        cursor = skip_whitespace(cursor);
        if (*cursor++ != ':') {
            return false;
        }
        cursor = skip_whitespace(cursor);
        if (!skip_json_value(&cursor, depth + 1U)) {
            return false;
        }
        cursor = skip_whitespace(cursor);
        if (*cursor == '}') {
            *value = cursor + 1;
            return true;
        }
        if (*cursor++ != ',') {
            return false;
        }
        cursor = skip_whitespace(cursor);
    }
}

static bool skip_json_value(const char **value, unsigned int depth) {
    const char *cursor = skip_whitespace(*value);

    if (depth > 64U) {
        return false;
    }
    if (*cursor == '"') {
        if (!skip_json_string(&cursor)) {
            return false;
        }
    } else if (*cursor == '{') {
        if (!skip_json_object(&cursor, depth)) {
            return false;
        }
    } else if (*cursor == '[') {
        if (!skip_json_array(&cursor, depth)) {
            return false;
        }
    } else if (*cursor == '-' || isdigit((unsigned char)*cursor)) {
        if (!skip_json_number(&cursor)) {
            return false;
        }
    } else if (strncmp(cursor, "true", 4U) == 0) {
        cursor += 4;
    } else if (strncmp(cursor, "false", 5U) == 0) {
        cursor += 5;
    } else if (strncmp(cursor, "null", 4U) == 0) {
        cursor += 4;
    } else {
        return false;
    }
    *value = cursor;
    return true;
}

static bool is_json_object(const char *line) {
    const char *cursor = skip_whitespace(line);

    if (*cursor != '{' || !skip_json_value(&cursor, 0U)) {
        return false;
    }
    return *skip_whitespace(cursor) == '\0';
}

static bool read_json_string(const char *value, char *output, size_t output_size) {
    size_t written = 0;

    if (*value != '"' || output_size == 0U) {
        return false;
    }
    value++;
    while (*value != '\0' && *value != '"') {
        char character = *value++;
        if (character == '\\') {
            character = *value++;
            switch (character) {
            case '"':
            case '\\':
            case '/':
                break;
            case 'b':
                character = '\b';
                break;
            case 'f':
                character = '\f';
                break;
            case 'n':
                character = '\n';
                break;
            case 'r':
                character = '\r';
                break;
            case 't':
                character = '\t';
                break;
            default:
                return false;
            }
        }
        if ((unsigned char)character < 0x20U || written + 1U >= output_size) {
            return false;
        }
        output[written++] = character;
    }
    if (*value != '"') {
        return false;
    }
    output[written] = '\0';
    return true;
}

static bool find_json_string_member(const char *json, const char *member,
                                    char *output, size_t output_size) {
    const char *cursor = skip_whitespace(json);

    if (*cursor++ != '{') {
        return false;
    }
    cursor = skip_whitespace(cursor);
    while (*cursor != '}') {
        const char *key_start = cursor;
        char key[TYPE_BYTES];
        bool readable_key = read_json_string(key_start, key, sizeof(key));

        if (!skip_json_string(&cursor)) {
            return false;
        }
        cursor = skip_whitespace(cursor);
        if (*cursor++ != ':') {
            return false;
        }
        cursor = skip_whitespace(cursor);
        if (readable_key && strcmp(key, member) == 0) {
            return read_json_string(cursor, output, output_size);
        }
        if (!skip_json_value(&cursor, 1U)) {
            return false;
        }
        cursor = skip_whitespace(cursor);
        if (*cursor == '}') {
            break;
        }
        if (*cursor++ != ',') {
            return false;
        }
        cursor = skip_whitespace(cursor);
    }
    return false;
}

static void json_escape(const char *input, char *output, size_t output_size) {
    size_t written = 0;

    for (; *input != '\0' && written + 1U < output_size; input++) {
        const char *replacement = NULL;
        switch (*input) {
        case '"': replacement = "\\\""; break;
        case '\\': replacement = "\\\\"; break;
        case '\n': replacement = "\\n"; break;
        case '\r': replacement = "\\r"; break;
        case '\t': replacement = "\\t"; break;
        default: break;
        }
        if (replacement != NULL) {
            while (*replacement != '\0' && written + 1U < output_size) {
                output[written++] = *replacement++;
            }
        } else if ((unsigned char)*input >= 0x20U) {
            output[written++] = *input;
        }
    }
    output[written] = '\0';
}

static void send_error(socket_handle socket_fd, const char *request_id,
                       const char *code, const char *message) {
    char escaped_id[REQUEST_ID_BYTES * 2U + 1U];
    char response[RESPONSE_BYTES];
    int response_length;

    if (request_id == NULL) {
        response_length = snprintf(response, sizeof(response),
            "{\"type\":\"ERROR\",\"request_id\":null,\"error\":{\"code\":\"%s\",\"message\":\"%s\"}}\n",
            code, message);
    } else {
        json_escape(request_id, escaped_id, sizeof(escaped_id));
        response_length = snprintf(response, sizeof(response),
            "{\"type\":\"ERROR\",\"request_id\":\"%s\",\"error\":{\"code\":\"%s\",\"message\":\"%s\"}}\n",
            escaped_id, code, message);
    }
    if (response_length > 0 && (size_t)response_length < sizeof(response)) {
        (void)send_all(socket_fd, response, (size_t)response_length);
    }
}

static void handle_line(socket_handle socket_fd, const char *line) {
    char request_id[REQUEST_ID_BYTES];
    char type[TYPE_BYTES];
    char escaped_id[REQUEST_ID_BYTES * 2U + 1U];
    char response[RESPONSE_BYTES];
    int response_length;

    if (!is_json_object(line)) {
        send_error(socket_fd, NULL, "BAD_REQUEST", "Message must be a JSON object");
        return;
    }
    if (!find_json_string_member(line, "request_id", request_id, sizeof(request_id))) {
        send_error(socket_fd, NULL, "BAD_REQUEST", "request_id must be a JSON string");
        return;
    }
    if (!find_json_string_member(line, "type", type, sizeof(type))) {
        send_error(socket_fd, request_id, "BAD_REQUEST", "type must be a JSON string");
        return;
    }
    if (strcmp(type, "PING") != 0) {
        send_error(socket_fd, request_id, "NOT_FOUND", "Unsupported request type");
        return;
    }

    json_escape(request_id, escaped_id, sizeof(escaped_id));
    response_length = snprintf(response, sizeof(response),
        "{\"type\":\"OK\",\"request_id\":\"%s\",\"data\":{\"message\":\"pong\"}}\n",
        escaped_id);
    if (response_length > 0 && (size_t)response_length < sizeof(response)) {
        (void)send_all(socket_fd, response, (size_t)response_length);
    }
}

static void *client_worker(void *argument) {
    socket_handle socket_fd = *(socket_handle *)argument;
    char line[KZ_MAX_NDJSON_LINE_BYTES + 1U];
    char received[RECEIVE_BUFFER_BYTES];
    size_t used = 0;

    free(argument);
    while (running) {
        int count = recv(socket_fd, received, sizeof(received), 0);
        if (count <= 0) {
            break;
        }
        for (int index = 0; index < count; index++) {
            if (received[index] == '\n') {
                line[used] = '\0';
                handle_line(socket_fd, line);
                used = 0;
            } else if (used >= KZ_MAX_NDJSON_LINE_BYTES) {
                send_error(socket_fd, NULL, "BAD_REQUEST", "Message exceeds 64 KB");
                CLOSE_SOCKET(socket_fd);
                return NULL;
            } else {
                line[used++] = received[index];
            }
        }
    }
    CLOSE_SOCKET(socket_fd);
    return NULL;
}

static bool parse_port(const char *value, int *port) {
    char *end = NULL;
    long parsed;

    errno = 0;
    parsed = strtol(value, &end, 10);
    if (errno != 0 || end == value || *end != '\0' || parsed < 1L || parsed > 65535L) {
        return false;
    }
    *port = (int)parsed;
    return true;
}

int main(int argc, char *argv[]) {
    struct sockaddr_in address;
    int option = 1;
    int port = KZ_DEFAULT_PORT;

#ifdef _WIN32
    WSADATA wsa_data;
    if (WSAStartup(MAKEWORD(2, 2), &wsa_data) != 0) {
        fprintf(stderr, "WSAStartup failed\n");
        return EXIT_FAILURE;
    }
#endif

    if (argc == 2 && !parse_port(argv[1], &port)) {
        fprintf(stderr, "Invalid port: %s\n", argv[1]);
        goto cleanup_failure;
    }
    if (argc > 2) {
        fprintf(stderr, "Usage: %s [port]\n", argv[0]);
        goto cleanup_failure;
    }

    signal(SIGINT, stop_server);
    signal(SIGTERM, stop_server);
#ifndef _WIN32
    signal(SIGPIPE, SIG_IGN);
#endif

    listening_socket = socket(AF_INET, SOCK_STREAM, 0);
    if (listening_socket == INVALID_SOCKET_HANDLE) {
        perror("socket");
        goto cleanup_failure;
    }
    if (setsockopt(listening_socket, SOL_SOCKET, SO_REUSEADDR,
                   (const char *)&option, sizeof(option)) < 0) {
        perror("setsockopt");
        CLOSE_SOCKET(listening_socket);
        goto cleanup_failure;
    }

    memset(&address, 0, sizeof(address));
    address.sin_family = AF_INET;
    address.sin_addr.s_addr = htonl(INADDR_ANY);
    address.sin_port = htons((uint16_t)port);
    if (bind(listening_socket, (struct sockaddr *)&address, sizeof(address)) < 0) {
        perror("bind");
        CLOSE_SOCKET(listening_socket);
        goto cleanup_failure;
    }
    if (listen(listening_socket, SOMAXCONN) < 0) {
        perror("listen");
        CLOSE_SOCKET(listening_socket);
        goto cleanup_failure;
    }

    printf("KuizuHub server listening on %s:%d (DB: %s)\n", KZ_BIND_ADDRESS, port,
           KZ_DATABASE_PATH);
    fflush(stdout);

    while (running) {
        socket_handle *client_socket = malloc(sizeof(*client_socket));
        pthread_t worker;

        if (client_socket == NULL) {
            fprintf(stderr, "Out of memory while accepting a client\n");
            break;
        }
        *client_socket = accept(listening_socket, NULL, NULL);
        if (*client_socket == INVALID_SOCKET_HANDLE) {
            free(client_socket);
            if (errno == EINTR || !running) {
                continue;
            }
            perror("accept");
            continue;
        }
        if (pthread_create(&worker, NULL, client_worker, client_socket) != 0) {
            perror("pthread_create");
            CLOSE_SOCKET(*client_socket);
            free(client_socket);
            continue;
        }
        (void)pthread_detach(worker);
    }

    if (listening_socket != INVALID_SOCKET_HANDLE) {
        CLOSE_SOCKET(listening_socket);
    }
#ifdef _WIN32
    WSACleanup();
#endif
    return EXIT_SUCCESS;

cleanup_failure:
#ifdef _WIN32
    WSACleanup();
#endif
    return EXIT_FAILURE;
}
