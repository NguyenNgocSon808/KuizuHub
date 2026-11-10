#include "protocol.h"
#include "log.h"

#include <ctype.h>
#include <errno.h>
#include <limits.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#define KZ_RESPONSE_MAX_BYTES (64U * 1024U)

int send_all(kz_socket_t socket_fd, const char *buffer, size_t length) {
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
        if (*cursor != '\0' && strchr("\"\\/bfnrt", *cursor) != NULL) {
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

bool is_json_object(const char *line) {
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

static const char *find_json_member_value(const char *json, const char *member) {
    const char *cursor = skip_whitespace(json);

    if (*cursor++ != '{') {
        return NULL;
    }
    cursor = skip_whitespace(cursor);
    while (*cursor != '\0' && *cursor != '}') {
        const char *key_start = cursor;
        char key[KZ_TYPE_BYTES];
        bool readable_key = read_json_string(key_start, key, sizeof(key));

        if (!skip_json_string(&cursor)) {
            return NULL;
        }
        cursor = skip_whitespace(cursor);
        if (*cursor++ != ':') {
            return NULL;
        }
        cursor = skip_whitespace(cursor);
        if (readable_key && strcmp(key, member) == 0) {
            return cursor;
        }
        if (!skip_json_value(&cursor, 1U)) {
            return NULL;
        }
        cursor = skip_whitespace(cursor);
        if (*cursor == '}') {
            break;
        }
        if (*cursor++ != ',') {
            return NULL;
        }
        cursor = skip_whitespace(cursor);
    }
    return NULL;
}

bool find_json_string_member(const char *json, const char *member,
                             char *output, size_t output_size) {
    const char *val = find_json_member_value(json, member);
    if (val == NULL) {
        return false;
    }
    return read_json_string(val, output, output_size);
}

bool find_json_int_member(const char *json, const char *member, int *output) {
    const char *val = find_json_member_value(json, member);
    const char *end_num;
    char num_buf[32];
    size_t len;
    char *end_ptr = NULL;
    long parsed;

    if (val == NULL || output == NULL) {
        return false;
    }
    end_num = val;
    if (!skip_json_number(&end_num)) {
        return false;
    }
    len = (size_t)(end_num - val);
    if (len == 0U || len >= sizeof(num_buf)) {
        return false;
    }
    memcpy(num_buf, val, len);
    num_buf[len] = '\0';
    if (strchr(num_buf, '.') != NULL || strchr(num_buf, 'e') != NULL || strchr(num_buf, 'E') != NULL) {
        return false;
    }
    errno = 0;
    parsed = strtol(num_buf, &end_ptr, 10);
    if (errno != 0 || end_ptr == num_buf || *end_ptr != '\0' || parsed < INT_MIN || parsed > INT_MAX) {
        return false;
    }
    *output = (int)parsed;
    return true;
}

bool find_json_object_member(const char *json, const char *member,
                             char *output, size_t output_size) {
    const char *val = find_json_member_value(json, member);
    const char *end_obj;
    size_t len;

    if (val == NULL || *val != '{' || output == NULL || output_size == 0U) {
        return false;
    }
    end_obj = val;
    if (!skip_json_object(&end_obj, 1U)) {
        return false;
    }
    len = (size_t)(end_obj - val);
    if (len + 1U > output_size) {
        return false;
    }
    memcpy(output, val, len);
    output[len] = '\0';
    return true;
}

void json_escape(const char *input, char *output, size_t output_size) {
    size_t written = 0;

    if (output_size == 0U) {
        return;
    }
    if (input == NULL) {
        output[0] = '\0';
        return;
    }
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

int send_ok_data(kz_socket_t socket_fd, const char *request_id, const char *data_json) {
    char escaped_id[KZ_REQUEST_ID_BYTES * 2U + 1U];
    char *response;
    int response_length;
    int rc;

    response = (char *)malloc(KZ_RESPONSE_MAX_BYTES);
    if (response == NULL) {
        return -1;
    }
    json_escape(request_id ? request_id : "", escaped_id, sizeof(escaped_id));
    response_length = snprintf(response, KZ_RESPONSE_MAX_BYTES,
        "{\"type\":\"OK\",\"request_id\":\"%s\",\"data\":%s}\n",
        escaped_id, (data_json && data_json[0] != '\0') ? data_json : "{}");
    if (response_length <= 0 || (size_t)response_length >= KZ_RESPONSE_MAX_BYTES) {
        free(response);
        return -1;
    }
    rc = send_all(socket_fd, response, (size_t)response_length);
    free(response);
    return rc;
}

void send_error(kz_socket_t socket_fd, const char *request_id,
                const char *code, const char *message) {
    char escaped_id[KZ_REQUEST_ID_BYTES * 2U + 1U];
    char escaped_msg[512];
    char response[1024];
    int response_length;

    json_escape(message ? message : "Error", escaped_msg, sizeof(escaped_msg));
    if (request_id == NULL) {
        response_length = snprintf(response, sizeof(response),
            "{\"type\":\"ERROR\",\"request_id\":null,\"error\":{\"code\":\"%s\",\"message\":\"%s\"}}\n",
            code ? code : "INTERNAL_ERROR", escaped_msg);
    } else {
        json_escape(request_id, escaped_id, sizeof(escaped_id));
        response_length = snprintf(response, sizeof(response),
            "{\"type\":\"ERROR\",\"request_id\":\"%s\",\"error\":{\"code\":\"%s\",\"message\":\"%s\"}}\n",
            escaped_id, code ? code : "INTERNAL_ERROR", escaped_msg);
    }
    if (response_length > 0 && (size_t)response_length < sizeof(response)) {
        (void)send_all(socket_fd, response, (size_t)response_length);
    }
}

void connection_init(kz_connection *conn, kz_socket_t socket_fd,
                     const char *peer_ip, int peer_port) {
    memset(conn, 0, sizeof(*conn));
    conn->socket_fd = socket_fd;
    if (peer_ip != NULL) {
        strncpy(conn->peer_ip, peer_ip, sizeof(conn->peer_ip) - 1U);
    } else {
        strcpy(conn->peer_ip, "unknown");
    }
    conn->peer_port = peer_port;
    conn->used = 0U;
    conn->overflowing = false;
}

void connection_read_lines(kz_connection *conn, kz_line_handler_fn handler) {
    char received[KZ_RECEIVE_BUFFER_BYTES];

    while (true) {
        int count = recv(conn->socket_fd, received, sizeof(received), 0);
        if (count <= 0) {
            break;
        }
        for (int index = 0; index < count; index++) {
            char ch = received[index];
            if (ch == '\n') {
                if (conn->overflowing) {
                    conn->used = 0U;
                    conn->overflowing = false;
                } else {
                    conn->line_buffer[conn->used] = '\0';
                    if (handler != NULL) {
                        handler(conn, conn->line_buffer);
                    }
                    conn->used = 0U;
                }
            } else if (conn->overflowing) {
                /* Discard remaining bytes of the oversized line until '\n' */
                continue;
            } else if (conn->used >= KZ_MAX_NDJSON_LINE_BYTES) {
                conn->overflowing = true;
                conn->used = 0U;
                kz_log_event(0, "PROTOCOL_ERROR", "connection", conn->peer_ip,
                             "{\"reason\":\"line_exceeds_64kb\"}");
                send_error(conn->socket_fd, NULL, "BAD_REQUEST", "Message exceeds 64 KB");
            } else {
                conn->line_buffer[conn->used++] = ch;
            }
        }
    }
}
