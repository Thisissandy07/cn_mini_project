CC = gcc
CFLAGS = -O2 -Wall -Wextra -pthread

all: server client
server: server.c common.h
	$(CC) $(CFLAGS) -o $@ $<
client: client.c common.h
	$(CC) $(CFLAGS) -o $@ $<
clean:
	rm -f server client
