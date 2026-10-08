"""位置参数解析 —— 只取「开头连续的非选项段」。

★为什么不能用 `[a for a in sys.argv[1:] if not a.startswith("--")]`
  它会把**选项的值**一并算成位置参数：

    python tools/herorecut.py images/a.jpg --mask-npy _work/x.npy
        → `_work/x.npy` 不以 `--` 开头 → 被判成位置参数 → 落到 `dst` 上
        → **把掩膜缓存当输出文件覆盖掉**（PNG 写进 .npy）

    python tools/herorecut.py images/a.jpg --check --fit-touch "L=48,R=40,T=33,B=100"
        → `L=48,...` 顶掉 dst → 工具打印出的「复现命令」照着抄必然报错

    python tools/reffit.py --out pages/x.png
        → `pages/x.png` 以 "page" 开头，被当成页面筛选器 → 匹配不到任何页
        → **判据静默空过**（最坏的一种：不报错、也没查）

本项目的调用惯例是 `script.py <位置参数…> --选项…`（位置参数永远在最前），
所以「扫到第一个选项即停」既简单又无歧义，也不需要在各脚本里维护选项白名单。
"""

import sys


def positionals(argv=None):
    """返回开头的连续位置参数；遇到第一个 `-` 开头的 token 立即停止。"""
    a = list(sys.argv[1:] if argv is None else argv)
    out = []
    for t in a:
        if t.startswith("-"):
            break
        out.append(t)
    return out
