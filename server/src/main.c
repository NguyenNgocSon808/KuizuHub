#include "config.h"
#include "db.h"
#include "log.h"
#include "server_socket.h"

#include <errno.h>
#include <signal.h>
#include <stdbool.h>
#include <stdio.h>
#include <stdlib.h>

static void on_signal(int signal_number) {
    (void)signal_number;
    kz_server_stop();
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
    int port = KZ_DEFAULT_PORT;
    const char *db_path = getenv("KUIZUHUB_DB_PATH");
    int rc;

#ifdef _WIN32
    WSADATA wsa_data;
    if (WSAStartup(MAKEWORD(2, 2), &wsa_data) != 0) {
        fprintf(stderr, "WSAStartup failed\n");
        return EXIT_FAILURE;
    }
#endif

    if (argc == 2 && !parse_port(argv[1], &port)) {
        fprintf(stderr, "Invalid port: %s\n", argv[1]);
#ifdef _WIN32
        WSACleanup();
#endif
        return EXIT_FAILURE;
    }
    if (argc > 2) {
        fprintf(stderr, "Usage: %s [port]\n", argv[0]);
#ifdef _WIN32
        WSACleanup();
#endif
        return EXIT_FAILURE;
    }

    if (db_path == NULL || db_path[0] == '\0') {
        db_path = KZ_DATABASE_PATH;
    }
    if (!kz_db_init(db_path, KZ_MIGRATION_PATH)) {
#ifdef _WIN32
        WSACleanup();
#endif
        return EXIT_FAILURE;
    }

    signal(SIGINT, on_signal);
    signal(SIGTERM, on_signal);
#ifndef _WIN32
    signal(SIGPIPE, SIG_IGN);
#endif

    rc = kz_server_run(port);
    kz_db_close();

#ifdef _WIN32
    WSACleanup();
#endif
    return (rc == 0) ? EXIT_SUCCESS : EXIT_FAILURE;
}
