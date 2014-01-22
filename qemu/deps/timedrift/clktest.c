#include <time.h>
#include <stdio.h>
#include <errno.h>
#include <string.h>

int main(int argc, char *argv[])
{
struct timespec         cur;
struct timespec         prev;
unsigned int            ticks;
int                     delay;

        if(argc > 1)
        {
                delay = atoi(argv[1]);
        }
        else
        {
                delay = 1;
        }

        printf("Using delay=%u milliseconds between calls.\n", delay);

        if(clock_getres(CLOCK_MONOTONIC, &cur) != 0)
        {
                printf("Failed clock resolution read errno=%d [%s].\n",
                        errno, strerror(errno));
                return(0);
        }

        printf("Clock resolution sec=%lu nsec=%lu\n",
                cur.tv_sec, cur.tv_nsec);

        if(clock_gettime(CLOCK_MONOTONIC, &cur) != 0)
        {
                printf("Failed initial read errno=%d [%s].\n",
                        errno, strerror(errno));
                return(0);
        }

        printf("Initial time sec=%lu nsec=%lu\n",
                cur.tv_sec, cur.tv_nsec);

        ticks = 0;

        while(1)
        {
                prev = cur;

                poll(0, 0, delay);

                if(clock_gettime(CLOCK_MONOTONIC, &cur) != 0)
                {
                        printf("Failed subsequent read errno=%d [%s].\n",
                                errno, strerror(errno));
                        return(0);
                }

                if((cur.tv_sec <= prev.tv_sec) &&
                   (cur.tv_nsec < prev.tv_nsec))
                {
                        printf("Time ran backward:\n\tcur:\t%lu%lu\n\tprev:\t%lu %lu\nInterval is >= %u milliseconds).\n",
                                cur.tv_sec, cur.tv_nsec,
                                prev.tv_sec, prev.tv_nsec,
                                delay);
                }

        }

        return(0);
}
