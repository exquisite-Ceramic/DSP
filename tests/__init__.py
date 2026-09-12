"""DSP 测试包。

将仓库内 tests 目录声明为显式 Python 包，避免本机环境中第三方同名
``tests`` 包抢占导入解析，确保 Phase I live helper 能稳定复用测试侧构造器。
"""
