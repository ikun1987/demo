# -*- coding: utf-8 -*-
"""修复 torch 在 PyInstaller 冻结环境下的 import 崩溃。

问题
----
`torch/utils/_config_module.py` 的 `install_config_module()` 会执行
    source_code = inspect.getsource(module)
用于扫描源码里的 `@compile_ignored` 注释。冻结后 .py 被压进 PYZ 归档，
`inspect` 找不到源码文件，于是抛 `OSError: could not get source code`，
`import torch` 直接失败（实测还会连带进程崩溃 0xC0000409）。

修法
----
该函数只用于识别"带 @compile_ignored 注释的配置键"（对这些键关闭编译期优化）。
返回空集**语义安全**：仅让少数配置项走通用路径，不影响任何数值结果。
这里在 torch 完成初始化前，把该函数替换成返回空集。

实现要点
--------
用 `importlib.util.spec_from_file_location` **只加载那一个文件**，
不起名为 torch 的包初始化；并且全程吞掉所有异常，
保证"补丁失败"也只是退化为不加补丁，绝不把主程序带崩。
"""
from __future__ import annotations

import importlib.util
import os
import sys

_applied = False
_error = ""


def _find_file() -> str:
    """定位 torch/utils/_config_module.py 的真实路径（不 import torch）。"""
    # 1) 冻结环境：从 PyInstaller 的解包目录直接找
    bases = []
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        bases.append(meipass)
    if getattr(sys, "frozen", False):
        bases.append(os.path.dirname(sys.executable))
    bases.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    # 2) 源码环境：顺着 site-packages 找
    for b in list(bases):
        try:
            for sub in ("torch", os.path.join("_internal", "torch")):
                p = os.path.join(b, sub, "utils", "_config_module.py")
                if os.path.exists(p):
                    return p
        except Exception:
            pass
    try:
        import site
        for sp in list(site.getsitepackages()) + [site.getusersitepackages()]:
            p = os.path.join(sp, "torch", "utils", "_config_module.py")
            if os.path.exists(p):
                return p
    except Exception:
        pass
    return ""


def _install_distributed_stub() -> bool:
    """预置 torch.distributed 占位模块。

    本软件只做单机推理，完全不需要分布式。但 torch 在 import 时会顺带
    初始化 torch.distributed（经 torch.utils.data → dataloader 链路），
    其原生部分在冻结环境下会触发 0xC0000409（栈缓冲溢出）直接崩进程。
    这里在导入 torch 之前，先往 sys.modules 放一个纯 Python 占位模块，
    让 torch 走"已导入"分支。务必在 import torch 之前调用。
    """
    try:
        if "torch.distributed" in sys.modules:
            return True
        import types as _types

        real = None
        try:
            import importlib.util as _ilu
            spec = None
            for finder in sys.meta_path:
                try:
                    spec = finder.find_spec("torch.distributed", None, None)
                except Exception:
                    spec = None
                if spec is not None:
                    break
            if spec is not None and spec.origin and os.path.exists(spec.origin):
                ms = _ilu.spec_from_file_location("torch.distributed", spec.origin,
                                                  submodule_search_locations=[os.path.dirname(spec.origin)])
                if ms and ms.loader:
                    real = _ilu.module_from_spec(ms)
                    ms.loader.exec_module(real)
        except BaseException:
            real = None

        if real is not None and hasattr(real, "is_available"):
            # 能安全加载：直接用真的，但优先保证不崩
            sys.modules.setdefault("torch.distributed", real)
            return True

        stub = _types.ModuleType("torch.distributed")

        def _na(*a, **k):
            raise RuntimeError("本程序为单机推理，未启用 torch.distributed")

        stub.is_available = lambda: False
        stub.is_initialized = lambda: False
        stub.get_rank = lambda *a, **k: 0
        stub.get_world_size = lambda *a, **k: 1
        stub.init_process_group = _na
        stub.destroy_process_group = _na
        stub.all_reduce = _na
        stub.all_gather = _na
        stub.broadcast = _na
        stub.barrier = _na
        stub.ReduceOp = type("ReduceOp", (), {"SUM": 0, "PRODUCT": 1, "MIN": 2, "MAX": 3})
        stub.__path__ = []          # 让它看起来像包，允许子模块导入
        sys.modules["torch.distributed"] = stub
        return True
    except BaseException:                           # noqa: BLE001
        return False


def apply() -> bool:
    """打补丁。返回是否成功；任何异常都吞掉，绝不外抛。"""
    global _applied, _error
    if _applied:
        return True
    try:
        path = _find_file()
        if not path:
            _error = "找不到 _config_module.py"
            return False
        spec = importlib.util.spec_from_file_location("_yuyong_torch_cfg", path)
        if spec is None or spec.loader is None:
            _error = "无法建立模块 spec"
            return False
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        if hasattr(mod, "get_assignments_with_compile_ignored_comments"):
            mod.get_assignments_with_compile_ignored_comments = lambda module: set()
            _applied = True
            return True
        _error = "目标函数不存在"
        return False
    except BaseException as e:                      # noqa: BLE001
        _error = f"{type(e).__name__}: {e}"
        return False


def status() -> str:
    return "已应用" if _applied else f"未应用({_error})"
