# Build the LD_PRELOAD library that masks host CPU count in containers
#
# Usage:
#     make              # Build libnukelab_cpu.so
#     make clean        # Remove compiled binary
#     make install      # Copy to system location (optional)

CC = gcc
CFLAGS = -shared -fPIC
LDFLAGS = -ldl
TARGET = libnukelab_cpu.so
SRC = libnukelab_cpu.c

.PHONY: all clean install

all: $(TARGET)

$(TARGET): $(SRC)
	$(CC) $(CFLAGS) -o $@ $< $(LDFLAGS)

clean:
	rm -f $(TARGET)

install: $(TARGET)
	mkdir -p /usr/local/lib/nukelab
	cp $(TARGET) /usr/local/lib/nukelab/
