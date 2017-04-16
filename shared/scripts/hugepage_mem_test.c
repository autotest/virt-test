#include<stdio.h>
#include<malloc.h>
#include<string.h>
#include<unistd.h>
#define MAX 1024*1024*1024/2

int main(){
    int *a;
    a = (int*)malloc(MAX);
    int *b;
    b = (int*)malloc(MAX);
    while(1){
        memcpy(b, a, MAX);
        memcpy(a, b, MAX);
        sleep(2);
    }
    return 0;
}
