/*
 * stress.c
 *
 *  Created on: Nov 29, 2011
 *      Author: jzupka
 */

#include "tests.h"
#include <sys/time.h>
#include <sys/select.h>

typedef float vector_type;

#define STOUS 1000*1000

long long timeval_subtract(struct timeval  *end, struct timeval  *start){
    //return time difference in u_second.
    long long msec_end = end->tv_sec * STOUS + end->tv_usec;
    long long msec_start = start->tv_sec * STOUS + start->tv_usec;
    return msec_end - msec_start;
}

void stressmem(unsigned int sizeMB, unsigned int fillMB){
	unsigned int size = sizeMB * 1024*1024;
	unsigned int subsize = (size / sizeof(vector_type));
	struct timeval starttime, endtime;
	long long time_diff = 0;

	unsigned int fill_rounds = fillMB / sizeMB;

	unsigned int rest_size = fillMB - (sizeMB * fill_rounds);
	unsigned int rest_subsize = (rest_size / sizeof(vector_type));

	long long round_time = STOUS / (fill_rounds + (rest_size > 0 ? 1 : 0));

	vector_type *a = malloc(size);
	struct timeval tsleep;
	tsleep.tv_sec = 0;

	printf("size %lld, subsize %lld", size, subsize);
	vector_type __attribute__ ((aligned(32))) v[256] = {0};
	while (1){
	    for (unsigned int r = 0; r < fill_rounds; r++){
	        gettimeofday(&starttime,0x0);
            #pragma omp parallel for private(v)
            for (unsigned int q = 0; q < subsize; q += 256) {
                for (unsigned int i = 0; i < 256; i++){
                    v[i] += 1;
                }
                for (unsigned int i = 0; i < 256; i++) {
                    a[q+i] += v[i];
                }
            }
            gettimeofday(&endtime,0x0);
            time_diff = timeval_subtract(&endtime,&starttime);
            if (time_diff < round_time){
                tsleep.tv_usec= round_time - time_diff;
                select(0, NULL, NULL, NULL, &tsleep);
            }
	    }
        #pragma omp parallel for private(v)
        for (unsigned int q = 0; q < rest_subsize; q += 256) {
            for (unsigned int i = 0; i < 256; i++){
                v[i] += 1;
            }
            for (unsigned int i = 0; i < 256; i++) {
                a[q+i] += v[i];
            }
        }

	}
	printf("Stress round.\n");
	free(a);
}
