CFLAGS  := -m32 -fno-stack-protector -fno-builtin -nostdinc -O -g -Wall -I.
LDFLAGS := -nostdlib -Wl,-N -Wl,-T -Wl,kernel.lds

all: cpuid_dump_kernel.bin

cpuid_dump_kernel.bin: boot.S main.c test.c
	$(CC) -o $@ $(CFLAGS) $^ $(LDFLAGS)

clean:
	rm -f *.o *.bin
