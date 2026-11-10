CC := gcc
CFLAGS := -std=c99 -Wall -Wextra -Werror -pedantic -O2 -pthread -Iinclude
LDFLAGS := -pthread

PORT ?= 5050
BUILD_DIR := build
EXE :=
ifeq ($(OS),Windows_NT)
EXE := .exe
CFLAGS += -isystem C:/msys64/mingw64/include
LDFLAGS += -LC:/msys64/mingw64/lib -Wl,-Bstatic -lsqlite3 -lcrypto -Wl,-Bdynamic -lws2_32 -lcrypt32
PYTHON ?= python
RUN_SERVER = ./$(TARGET) $(PORT)
else
CFLAGS += -D_POSIX_C_SOURCE=200809L
LDFLAGS += -lsqlite3 -lcrypto
PYTHON ?= python3
RUN_SERVER = ./$(TARGET) $(PORT)
endif

MAKE_BUILD_DIR = $(PYTHON) -c "import pathlib; pathlib.Path('$(BUILD_DIR)').mkdir(parents=True, exist_ok=True)"
REMOVE_BUILD_DIR = $(PYTHON) -c "import shutil; shutil.rmtree('$(BUILD_DIR)', ignore_errors=True)"

TARGET := $(BUILD_DIR)/kuizuhub-server$(EXE)
SOURCES := src/main.c \
           src/core/db.c \
           src/core/server_socket.c \
           src/protocol/ndjson.c \
           src/auth/auth.c \
           src/log/logger.c
HEADERS := include/config.h \
           include/db.h \
           include/log.h \
           include/protocol.h \
           include/auth.h \
           include/server_socket.h

.DEFAULT_GOAL := all

all: $(TARGET)

$(BUILD_DIR):
	$(MAKE_BUILD_DIR)

$(TARGET): $(SOURCES) $(HEADERS) | $(BUILD_DIR)
	$(CC) $(CFLAGS) $(SOURCES) -o $@ $(LDFLAGS)

run: $(TARGET)
	$(RUN_SERVER)

test: $(TARGET)
	$(PYTHON) -m unittest discover -s tests -p "test_*.py" -v

clean:
	$(REMOVE_BUILD_DIR)

.PHONY: all run test clean
