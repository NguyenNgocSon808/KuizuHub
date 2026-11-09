SERVER_DIR := server
PORT ?= 5050

.DEFAULT_GOAL := all

all:
	$(MAKE) -C $(SERVER_DIR) all

run:
	$(MAKE) -C $(SERVER_DIR) run PORT=$(PORT)

test:
	$(MAKE) -C $(SERVER_DIR) test

clean:
	$(MAKE) -C $(SERVER_DIR) clean

.PHONY: all run test clean
