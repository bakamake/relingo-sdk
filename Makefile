CC      ?= cc
CFLAGS  ?= -O2 -Wall -Wextra -std=c11
LDFLAGS ?=

# Detect cJSON via pkg-config; fall back to plain -lcjson if unavailable.
CJSON_CFLAGS := $(shell pkg-config --cflags libcjson 2>/dev/null)
CJSON_LIBS   := $(shell pkg-config --libs   libcjson 2>/dev/null)
ifeq ($(CJSON_LIBS),)
CJSON_LIBS := -lcjson
endif

.PHONY: all clean
all: librelingo.a example

librelingo.a: relingo.o
	ar rcs $@ $^

relingo.o: relingo.c relingo.h
	$(CC) $(CFLAGS) $(CJSON_CFLAGS) -c $< -o $@

example: example.o librelingo.a
	$(CC) $(CFLAGS) $(LDFLAGS) -o $@ $^ $(CJSON_LIBS) -lcurl

example.o: example.c relingo.h
	$(CC) $(CFLAGS) $(CJSON_CFLAGS) -c $< -o $@

clean:
	rm -f *.o librelingo.a example
