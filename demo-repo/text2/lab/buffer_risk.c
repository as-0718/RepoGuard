/* 缓冲区安全示例：演示用带长度限制的标准函数读写字符缓冲区。 */
#include <stdio.h>
#include <string.h>

/* main：程序入口，读取一行输入并在安全边界内拼接、格式化到缓冲区。 */
int main(void) {
    char buf[64];
    if (fgets(buf, sizeof(buf), stdin) == NULL) {
        return 1;
    }
    size_t used = strlen(buf);
    strncat(buf, "!", sizeof(buf) - used - 1);
    snprintf(buf, sizeof(buf), "%s", buf);
    return 0;
}
