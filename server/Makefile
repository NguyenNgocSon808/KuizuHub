# KuizuHub Server — Makefile
#
# Build trên Linux/macOS:   make
# Build trên Windows (MinGW): make (cần cài MinGW + pthreads-win32)
#
# Chạy: ./server <port>
# Ví dụ: ./server 9000

CC      = gcc
CFLAGS  = -Wall -Wextra -std=c11 -g -pthread
LDFLAGS = -pthread

# Thêm -lws2_32 khi build trên Windows (MinGW)
ifeq ($(OS), Windows_NT)
    LDFLAGS += -lws2_32
    EXT = .exe
else
    EXT =
endif

# ---------------------------------------------------------------
#  Nguồn file
# ---------------------------------------------------------------
SRCS = server.c                      \
       network/protocol.c            \
       advanced/reconnect.c          \
       advanced/encrypt.c            \
       sha256.c                      # copy từ tuan5/

TARGET = server$(EXT)

OBJS = $(SRCS:.c=.o)

# ---------------------------------------------------------------
#  Rules
# ---------------------------------------------------------------
all: copy_sha256 $(TARGET)

# Copy sha256.c và sha256.h từ tuan5 vào thư mục server/ để build
copy_sha256:
	@if [ ! -f sha256.c ]; then \
	    echo "[Makefile] Copying sha256 from tuan5..."; \
	    cp ../../../tuan5/sha256.c . && cp ../../../tuan5/sha256.h .; \
	fi

$(TARGET): $(OBJS)
	$(CC) $(OBJS) -o $@ $(LDFLAGS)
	@echo "[Makefile] Build OK: $(TARGET)"

%.o: %.c
	$(CC) $(CFLAGS) -I. -c $< -o $@

clean:
	rm -f $(OBJS) $(TARGET) sha256.c sha256.h

.PHONY: all clean copy_sha256
