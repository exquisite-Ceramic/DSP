"""仓库级 pytest 导入引导。

部分窄 CI lane 直接调用 ``pytest`` console script，而不是 ``python -m pytest``，
此时仓库根目录不一定出现在 ``sys.path`` 的最前部。测试之间复用的
``tests.*`` 辅助模块因此可能被第三方同名包遮蔽或完全无法解析。

这里仅在测试进程内把仓库根目录前置，统一各 CI lane 的测试辅助模块解析；
不改变任何产品模块的导入路径或运行时行为。
"""

import pathlib
import sys


REPOSITORY_ROOT = pathlib.Path(__file__).resolve().parents[1]
repository_root_text = str(REPOSITORY_ROOT)

if repository_root_text not in sys.path:
    sys.path.insert(0, repository_root_text)
