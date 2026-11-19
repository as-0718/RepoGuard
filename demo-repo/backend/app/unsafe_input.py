"""外部输入处理示例（反面样例：演示危险调用与裸异常捕获检测）。"""
import os


def run_command(name: str) -> str:
    """拼接并执行外部命令，存在命令注入风险（反面演示）。"""
    os.system("echo " + name)
    try:
        result = eval(name)
    except:
        result = ""
    return str(result)
