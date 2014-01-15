/*
 * Test routine
 *
 * Copyright Red Hat, Inc. 2013
 *
 * Authors:
 *  Igor Mammedov <imammedo@redhat.com>
 *
 * This work is licensed under the terms of the GNU GPL, version 2 or later.
 * See the COPYING file in the top-level directory.
 */

#include "main.h"


typedef struct {
    unsigned int eax;
    unsigned int index;
} level_t;

/* array must be sorted by eax field */
static level_t levels[] = {
    { 0, 0 },
    { 1, 0 },
    { 2, 0 },
    { 3, 0 },
    { 4, 0 },
    { 4, 1 },
    { 4, 2 },
    { 4, 3 },
    { 5, 0 },
    { 6, 0 },
    { 7, 0 },
    { 9, 0 },
    { 0xA, 0 },
    { 0xB, 0 },
    { 0xC, 0 },
    { 0xD, 0 },
    { 0xD, 1 },
    { 0xD, 2 },
    { 0xD, 3 },
    { 0xD, 4 },
    { 0xD, 5 },
    { 0xD, 6 },
    { 0xD, 7 },
    { 0x80000000, 0 },
    { 0x80000001, 0 },
    { 0x80000002, 0 },
    { 0x80000003, 0 },
    { 0x80000004, 0 },
    { 0x80000005, 0 },
    { 0x80000006, 0 },
    { 0x80000007, 0 },
    { 0x80000008, 0 },
    { 0x8000000A, 0 },
    { 0xC0000000, 0 },
    { 0xC0000001, 0 },
    { 0xC0000002, 0 },
    { 0xC0000003, 0 },
    { 0xC0000004, 0 },
};

static unsigned int print_leaf(unsigned int leaf, unsigned int idx)
{
    unsigned int eax, ebx, ecx, edx;
    asm("cpuid"
        : "=a" (eax), "=b" (ebx), "=c" (ecx), "=d" (edx)
        : "a" (leaf), "c" (idx));
    printf("   0x%08x 0x%02x: eax=0x%08x ebx=0x%08x"
           " ecx=0x%08x edx=0x%08x\n", leaf, idx,
           eax, ebx, ecx, edx);
    return eax;
}

#define KVM_CPUID_SIGNATURE                     0x40000000
#define KVM_CPUID_FEATURES                      0x40000001
#define HYPERV_CPUID_VENDOR_AND_MAX_FUNCTIONS   0x40000000
#define HYPERV_CPUID_INTERFACE                  0x40000001
#define HYPERV_CPUID_VERSION                    0x40000002
#define HYPERV_CPUID_FEATURES                   0x40000003
#define HYPERV_CPUID_ENLIGHTMENT_INFO           0x40000004
#define HYPERV_CPUID_IMPLEMENT_LIMITS           0x40000005
#define KVM_CPUID_SIGNATURE_NEXT                0x40000100

static void dump_kvm_leafs()
{
    unsigned int eax, ebx, ecx, edx;

    asm("cpuid"
        : "=a" (eax), "=b" (ebx), "=c" (ecx), "=d" (edx)
        : "a" (KVM_CPUID_SIGNATURE));

    /* "KVMKVMKVM\0\0\0" */
    if ((ebx == 0x4b4d564b) && (ecx == 0x564b4d56) && (edx == 0x4d)) {
        print_leaf(KVM_CPUID_SIGNATURE, 0);
        print_leaf(KVM_CPUID_FEATURES, 0);

    /* "Microsoft Hv" */
    } else if ((ebx == 0x7263694d) && (ecx == 0x666f736f) &&
               (edx == 0x76482074)) {
        print_leaf(HYPERV_CPUID_VENDOR_AND_MAX_FUNCTIONS, 0);
        print_leaf(HYPERV_CPUID_INTERFACE, 0);
        print_leaf(HYPERV_CPUID_VERSION, 0);
        print_leaf(HYPERV_CPUID_FEATURES, 0);
        print_leaf(HYPERV_CPUID_ENLIGHTMENT_INFO, 0);
        print_leaf(HYPERV_CPUID_IMPLEMENT_LIMITS, 0);
        print_leaf(KVM_CPUID_SIGNATURE_NEXT, 0);
    }
}

void test()
{
    unsigned int eax, i;
    unsigned int level = 0, xlevel = 0, x2level = 0;

    printf("CPU:\n");
    for (i=0; i < sizeof(levels)/sizeof(*levels); i++) {
        unsigned int leaf = levels[i].eax;


        if ((leaf > level) && (leaf < 0x80000000)) {
            continue;
        } else if ((leaf > xlevel) && (leaf < 0xC0000000) &&
                   (leaf > 0x80000000) ) {
            continue;
        } else if ((leaf > x2level) && (leaf <= 0xFFFFFFFF) &&
                   (leaf > 0xC0000000)) {
            break;
        }

        eax = print_leaf(leaf, levels[i].index);

        if (leaf == 0) {
            level = eax;
        }
        if (leaf == (0x80000000 & eax)) {
            xlevel = eax;
        }
        if (leaf == (0xC0000000 & eax)) {
            x2level = eax;
        }
   }
   dump_kvm_leafs();
}
