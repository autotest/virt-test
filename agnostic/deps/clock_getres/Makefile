CC = gcc
PROG = clock_getres
SRC = clock_getres.c
LIBS = -lrt

all: $(PROG)

$(PROG):
	$(CC) $(LIBS) -o $(PROG) $(SRC)
clean:
	rm -f $(PROG)
