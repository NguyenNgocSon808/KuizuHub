CC := gcc
CFLAGS := -std=c99 -Wall -Wextra -Werror -pedantic -O2 -pthread -Iinclude
LDFLAGS := -pthread

PORT ?= 5050
BUILD_DIR := build
EXE :=
ifeq ($(OS),Windows_NT)
EXE := .exe
LDFLAGS += -lws2_32
MAKE_BUILD_DIR = if not exist $(BUILD_DIR) mkdir $(BUILD_DIR)
REMOVE_BUILD_DIR = if exist $(BUILD_DIR) rmdir /S /Q $(BUILD_DIR)
RUN_SERVER = .\\$(TARGET) $(PORT)
else
MAKE_BUILD_DIR = mkdir -p $(BUILD_DIR)
REMOVE_BUILD_DIR = rm -rf $(BUILD_DIR)
RUN_SERVER = ./$(TARGET) $(PORT)
endif
TARGET := $(BUILD_DIR)/kuizuhub-server$(EXE)
SOURCES := src/main.c

.DEFAULT_GOAL := all

all: $(TARGET)

$(BUILD_DIR):
	$(MAKE_BUILD_DIR)

$(TARGET): $(SOURCES) include/config.h | $(BUILD_DIR)
	$(CC) $(CFLAGS) $(SOURCES) -o $@ $(LDFLAGS)

run: $(TARGET)
	$(RUN_SERVER)

test: $(TARGET)
	python3 -m unittest discover -s tests -p "test_*.py" -v

clean:
	$(REMOVE_BUILD_DIR)

.PHONY: all run test clean
