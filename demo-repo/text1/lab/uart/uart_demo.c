/* 串口数据收发示例：演示带长度限制的字符串拷贝与明确退出条件。 */
#include <stdio.h>
#include <string.h>

/* main：程序入口，把来源字符串拷贝到定长缓冲区并打印。 */
int main(void) {
    char buffer[16];
    const char *source = "hello";
    strncpy(buffer, source, sizeof(buffer) - 1);
    buffer[sizeof(buffer) - 1] = '\0';
    printf("%s\n", buffer);
    return 0;
}
