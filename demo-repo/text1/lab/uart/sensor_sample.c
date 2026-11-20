/* 温湿度采集示例：演示规范的文件头注释与函数注释写法。 */
#include <stdio.h>

/* read_sensor：读取传感器当前采样值，返回 0 表示采集成功。 */
static int read_sensor(void) {
    return 0;
}

/* main：程序入口，调用采集函数并输出结果。 */
int main(void) {
    return read_sensor();
}
