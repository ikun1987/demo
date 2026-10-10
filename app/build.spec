# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller 打包配置 —— 玉用去水印。

用法（在 app 目录下）：
    python -m PyInstaller --clean --noconfirm build.spec
产出：
    dist/玉用去水印/玉用去水印.exe   （onedir，供 Inno Setup 打安装包）
"""
import os
import sys
from pathlib import Path

APP_DIR = Path(os.path.abspath(SPECPATH))
ICON = APP_DIR / "assets" / "app.ico"
ASSETS = APP_DIR / "assets"

block_cipher = None

datas = []
if ASSETS.exists():
    datas.append((str(ASSETS), "assets"))

# ---- torch 需要"真实源码文件"在磁盘上 ----
# torch/utils/_config_module.py 会调用 inspect.getsource() 读取模块源码。
# PyInstaller 默认把 .py 压进 PYZ 归档，inspect 就取不到源码，
# 于是 import torch 直接抛 OSError: could not get source code（实测崩溃点）。
# 这里把 torch / torchvision / simple_lama_inpainting 的 .py 作为数据文件一并落盘。
from PyInstaller.utils.hooks import collect_data_files as _cdf  # noqa: E402

for _pkg in ("torch", "torchvision", "simple_lama_inpainting"):
    try:
        datas += _cdf(_pkg, include_py_files=True)
    except Exception as _e:                                   # noqa: BLE001
        print(f"[打包] collect_data_files({_pkg}) 跳过: {_e}")

hiddenimports = [
    "PySide6.QtCore", "PySide6.QtGui", "PySide6.QtWidgets",
    "numpy", "cv2", "PIL.Image", "PIL.ImageFont",
    "PIL.ImageDraw", "PIL.ImageOps",
    # 深度修补路线（LaMa）
    # 实测 LaMa 只依赖 torch；torchvision 整体可省（约 50MB）
    "torch", "torch.nn", "torch.nn.functional",
    "simple_lama_inpainting",
    "simple_lama_inpainting.models", "simple_lama_inpainting.models.model",
    "simple_lama_inpainting.utils", "simple_lama_inpainting.utils.util",
]

# 砍掉用不到的大块依赖。注意：sympy 是 torch 的依赖，不能排掉；
# torch 自带的分布式 / 测试 / 编译工具也一并剔除，能省几百 MB。
excludes = [
    "pandas", "matplotlib", "numba", "llvmlite", "scipy",
    "PySide6.QtWebEngineCore", "PySide6.QtWebEngineWidgets", "PySide6.QtWebEngineQuick",
    "PySide6.QtQml", "PySide6.QtQuick", "PySide6.QtQuick3D", "PySide6.QtQuickWidgets",
    "PySide6.Qt3DCore", "PySide6.Qt3DRender", "PySide6.Qt3DAnimation", "PySide6.Qt3DExtras",
    "PySide6.QtMultimedia", "PySide6.QtMultimediaWidgets", "PySide6.QtCharts",
    "PySide6.QtDataVisualization", "PySide6.QtBluetooth", "PySide6.QtNfc",
    "PySide6.QtPositioning", "PySide6.QtSerialPort", "PySide6.QtSql", "PySide6.QtTest",
    "PySide6.QtDesigner", "PySide6.QtHelp", "PySide6.QtOpenGL", "PySide6.QtOpenGLWidgets",
    "PySide6.QtPdf", "PySide6.QtPdfWidgets", "PySide6.QtRemoteObjects", "PySide6.QtScxml",
    "PySide6.QtSensors", "PySide6.QtSpatialAudio", "PySide6.QtStateMachine",
    "PySide6.QtSvg", "PySide6.QtSvgWidgets", "PySide6.QtTextToSpeech", "PySide6.QtUiTools",
    "PySide6.QtWebChannel", "PySide6.QtNetwork",
    "tkinter", "pydoc", "doctest", "pytest",
    "IPython", "notebook", "pip", "setuptools",
    # torch 的大型可选组件。
    # 注意：**不要**排除 torch.distributed / unittest / sympy —— torch 顶层会 import 它们，
    # 排掉会让打包后的程序直接崩溃或 LaMa 不可用（这两个坑都实测踩过）。
    "torch.utils.tensorboard", "torch.utils.benchmark",
    "torchvision.datasets", "torchvision.io", "torchvision.models",
    "torchvision.ops", "torchvision.transforms", "torchvision.utils",
    "tensorboard", "google.protobuf", "onnx", "onnxruntime",
]

a = Analysis(
    [str(APP_DIR / "main.py")],
    pathex=[str(APP_DIR)],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=excludes,
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)
pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="玉用去水印",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=str(ICON) if ICON.exists() else None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="玉用去水印",
)

# ---------------------------------------------------------------------------
# 瘦身：删掉运行时根本用不到的巨型二进制
#   opencv_videoio_ffmpeg*.dll  只服务视频读写，本软件纯图片处理
#   opengl32sw.dll              Qt 的软件 OpenGL 兜底，桌面渲染用不到
#   _avif / _webp 之外的 PIL 编解码器按需保留（AVIF 仅解码用，砍掉省 7MB）
# ---------------------------------------------------------------------------
import glob as _glob
import shutil as _shutil

_dist = Path(DISTPATH) / "玉用去水印" / "_internal"
_patterns = [
    "cv2/opencv_videoio_ffmpeg*.dll",
    "PySide6/opengl32sw.dll",
    "PySide6/d3dcompiler_47.dll",
    "PIL/_avif*.pyd",
    "PIL/_imagingcms*.pyd",
    # torch 的测试 / 编译期组件。
    # 注意：**不要**删 torch/distributed/** —— torch 顶层会 import 它，
    # 删掉后打包版会报 "No module named 'torch.distributed'"（实测踩过）。
    "torch/include/**",
    "torch/test/**",
    "torch/testing/**",
    "torch/_inductor/**",
    "torch/_dynamo/**",
    "torch/onnx/**",
    "torch/utils/tensorboard/**",
    "torchvision/datasets/**",
    "torchvision/io/**",
    "torchvision/models/**",
    "torchvision/ops/**",
]
removed = 0
for pat in _patterns:
    for f in _glob.glob(str(_dist / pat), recursive=True):
        try:
            if os.path.isdir(f):
                _shutil.rmtree(f, ignore_errors=True)
                print(f"[瘦身] 删除目录 {os.path.relpath(f, _dist)}")
            else:
                size = os.path.getsize(f)
                os.remove(f)
                removed += size
                print(f"[瘦身] 删除 {os.path.relpath(f, _dist)}  ({size/1048576:.1f} MB)")
        except OSError:
            pass
print(f"[瘦身] 共释放 {removed/1048576:.1f} MB")

