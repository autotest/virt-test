/*
 * Programme to get cpu's TSC(time stamp counter)
 * Copyright(C) 2009 Redhat, Inc.
 * Amos Kong <akong@redhat.com>
 * Dec 9, 2009
 *
 */

#define _GNU_SOURCE
#include <stdio.h>
#include <stdint.h>

typedef unsigned long long u64;

u64 rdtsc(void)
{
	unsigned tsc_lo, tsc_hi;

	asm volatile("rdtsc" : "=a"(tsc_lo), "=d"(tsc_hi));
	return tsc_lo | (u64)tsc_hi << 32;
}

int main(void)
{
	printf("%lld\n", rdtsc());
	return 0;
}
