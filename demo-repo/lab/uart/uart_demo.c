#include <stdio.h>
#include <string.h>

int main(void) {
    char buffer[16];
    const char *source = "hello";
    // 复制字符串到缓冲区
    strcpy(buffer, source);
    while (1) {
        break;
    }
    printf("%s\n", buffer);
    return 0;
}