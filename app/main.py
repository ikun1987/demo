# -*- coding: utf-8 -*-
"""玉用去水印 —— 程序入口。

单独放一个入口文件，好处是：
  1. PyInstaller 以它作为入口，不用把 gui.py 当脚本运行；
  2. 源码模式下的"开机自启"可以直接指向这个文件；
  3. 需要 DPI / 兼容性参数时只改这一处。
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

# 支持从任意工作目录启动
sys.path.insert(0, str(Path(__file__).resolve().parent))

# ---- torch 冻结环境加固（必须在任何 torch 导入之前设置）----
# 打包后源码不是文件，torch 的 Dynamo/JIT 会 inspect 源码而崩溃；
# 同时避免 OpenMP 重复加载导致的栈缓冲溢出。
os.environ.setdefault("TORCH_COMPILE_DISABLE", "1")
os.environ.setdefault("TORCHDYNAMO_DISABLE", "1")
# 注意：不要设 PYTORCH_JIT=0 —— LaMa 权重是 TorchScript 归档，关掉 JIT 会加载失败
os.environ.setdefault("KMP_DUPLICATE_LIB_OK", "TRUE")
os.environ.setdefault("OMP_NUM_THREADS", str(min(8, (os.cpu_count() or 4))))

# ---- torch 冻结环境修补：必须在任何 import torch 之前执行 ----
# 冻结后 torch 会因 inspect.getsource() 找不到源码而无法 import，
# 这里提前把那个只用于扫描注释的函数替换掉（语义安全）。
try:
    from core import torch_fix as _torch_fix
    _torch_fix.apply()
except Exception:
    pass

from gui import main  # noqa: E402

if __name__ == "__main__":
    # Qt6 默认已启用高 DPI 缩放，这里只保证混合 DPI 显示器上不乱
    os.environ.setdefault("QT_ENABLE_HIGHDPI_SCALING", "1")
    main()
