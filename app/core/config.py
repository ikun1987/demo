# -*- coding: utf-8 -*-
"""玉用去水印 - 配置、路径与开机自启管理。"""
from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass, asdict, field
from pathlib import Path

APP_NAME = "玉用去水印"
APP_ID = "YuYongQuShuiYin"
APP_VERSION = "1.2.0"
RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"


def app_root() -> Path:
    """安装根目录（用于定位图标等只读资源）。"""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[2]


def resource_path(*parts: str) -> Path:
    if hasattr(sys, "_MEIPASS"):
        return Path(sys._MEIPASS).joinpath(*parts)
    return app_root().joinpath(*parts)


def data_dir() -> Path:
    """用户数据目录：配置与日志。"""
    base = os.environ.get("APPDATA") or str(Path.home())
    d = Path(base) / APP_ID
    d.mkdir(parents=True, exist_ok=True)
    return d


def default_output_dir() -> Path:
    d = Path.home() / "Pictures" / f"{APP_NAME}输出"
    return d


@dataclass
class Settings:
    # 输出
    output_dir: str = field(default_factory=lambda: str(default_output_dir()))
    same_as_source: bool = False
    suffix: str = "_已去水印"
    keep_exif: bool = True
    jpeg_quality: int = 98
    png_compress: int = 6
    # 处理
    strength: int = 4            # 1 保守 / 2 轻柔 / 3 标准 / 4 强力 / 5 极致
    region_preset: str = "auto"  # auto | corner_br | corner_bl | corner_tr | corner_tl | custom
    margin_ratio: float = 0.028  # 距边缘留白比例（用于生成候选区域）
    scale_px: int = 0            # 0 = 按图宽自动推算
    auto_start: bool = False
    close_to_tray: bool = False   # 关闭主窗口时是否收进托盘（首次关闭时询问一次）
    saved_geometry: str = ""
    last_input_dir: str = ""
    bitmap_repair: bool = True
    use_lama: bool = True         # 深度修补（LaMa）：专治「白色描边」水印，效果远好于传统算法
    force_clean: bool = False     # 手动框选区域后"强制清理"（只抬接近纸白的像素，不碰深色内容）
    custom_rect: list = field(default_factory=list)   # 上次手动框选区域 [x, y, w, h]

    # ------------------------------------------------------------------ IO
    @staticmethod
    def path() -> Path:
        return data_dir() / "settings.json"

    @classmethod
    def load(cls) -> "Settings":
        p = cls.path()
        if p.exists():
            try:
                raw = json.loads(p.read_text(encoding="utf-8"))
                known = {f for f in cls.__dataclass_fields__}
                return cls(**{k: v for k, v in raw.items() if k in known})._clamp()
            except Exception:
                pass
        return cls()

    def _clamp(self) -> "Settings":
        """修正越界/损坏的配置值，避免启动时构建界面直接崩溃。"""
        def _int(v, lo, hi, default):
            try:
                v = int(v)
            except (TypeError, ValueError):
                return default
            return min(hi, max(lo, v))

        self.strength = _int(self.strength, 1, 5, 4)          # 强度档位是名称表的键，越界会 KeyError
        self.jpeg_quality = _int(self.jpeg_quality, 60, 100, 98)
        self.png_compress = _int(self.png_compress, 0, 9, 6)
        try:
            self.margin_ratio = float(min(1.0, max(0.0, float(self.margin_ratio))))
        except (TypeError, ValueError):
            self.margin_ratio = 0.028
        if self.region_preset not in ("auto", "corner_br", "corner_bl",
                                      "corner_tr", "corner_tl", "custom"):
            self.region_preset = "auto"
        return self

    def save(self) -> None:
        try:
            self.path().write_text(
                json.dumps(asdict(self), ensure_ascii=False, indent=2), encoding="utf-8"
            )
        except Exception:
            pass


# ------------------------------------------------------------------ 开机自启
def _exe_command() -> str:
    if getattr(sys, "frozen", False):
        return f'"{Path(sys.executable).resolve()}"'
    # 源码运行时：优先用 main.py，没有则退回 gui.py（本项目入口是 gui.py，
    # 之前写死 main.py 会让开机自启指向一个不存在的脚本）。
    app_dir = Path(__file__).resolve().parents[1]
    script = app_dir / "main.py"
    if not script.exists():
        script = app_dir / "gui.py"
    return f'"{sys.executable}" "{script}"'


def auto_start_enabled() -> bool:
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as k:
            winreg.QueryValueEx(k, APP_NAME)
        return True
    except FileNotFoundError:
        return False
    except OSError:
        return False


def set_auto_start(enable: bool) -> bool:
    """写入/移除 HKCU Run 项，返回当前实际状态。"""
    import winreg
    try:
        with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as k:
            if enable:
                winreg.SetValueEx(k, APP_NAME, 0, winreg.REG_SZ, _exe_command())
            else:
                try:
                    winreg.DeleteValue(k, APP_NAME)
                except FileNotFoundError:
                    pass
    except OSError:
        pass
    return auto_start_enabled()
