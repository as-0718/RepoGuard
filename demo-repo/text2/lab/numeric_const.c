/* 常量取值示例：演示把函数内长数字提取为具名宏常量。 */
#include <stdio.h>

#define SAMPLE_PERIOD_MS 5000

/* main：程序入口，输出定时参数。 */
int main(void) {
    int period = SAMPLE_PERIOD_MS;
    printf("%d\n", period);
    return 0;
}
