/*
 * boot.S - bootstrap the kernel
 *
 * Copyright Red Hat, Inc. 2013
 *
 * Authors:
 *  Igor Mammedov <imammedo@redhat.com>
 *
 * This work is licensed under the terms of the GNU GPL, version 2 or later.
 * See the COPYING file in the top-level directory.
 */


#define ASM     1

#define MULTIBOOT_HEADER_MAGIC          0x1BADB002 /* magic no. for multiboot header */
#define MULTIBOOT_HEADER_FLAGS          0x00000003 /* flags for multiboot header */
#define STACK_SIZE 0x4000                          /* size of our stack (16KB) */

#ifdef HAVE_ASM_USCORE
# define EXT_C(sym)                     _ ## sym
#else
# define EXT_C(sym)                     sym
#endif

       .text
_start: .global _start /* global entry point into kernel */
       /* make sure that the multiboot magic values in the beginning */
       jmp     multiboot_entry

       /* Align the multiboot header at a 32 bits boundary.  */
       .align 4

multiboot_header:
       .long   MULTIBOOT_HEADER_MAGIC
       .long   MULTIBOOT_HEADER_FLAGS
       .long   -(MULTIBOOT_HEADER_MAGIC + MULTIBOOT_HEADER_FLAGS)

multiboot_entry:
       /* Initialize the stack pointer */
       movl    $(stack + STACK_SIZE), %esp

       /* run kernel */
       call    EXT_C(cmain)

loop:   /* Die here when finished */
       hlt
       jmp     loop

       .section ".bss"
       .comm   stack, STACK_SIZE
