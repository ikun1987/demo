# -*- coding: utf-8 -*-
"""豆包水印清理 · 深度学习修补路线（LaMa）。

为什么换路线
------------
传统算法（OpenCV）在豆包这种「白色填充 + 亮描边」水印上到顶了：
实测最好也只把水印压淡、并在纹理背景上留下糊痕。原因是这类水印不是
"单一半透明覆盖"，无法用 alpha 反演的物理模型描述，而结构感知修补
（TELEA/NS）对"文字覆盖造成的结构性缺失"几乎没有重建能力。

LaMa（Large Mask Inpainting）是专门为**大掩膜结构性缺失**训练的修补网络，
在文字/水印去除这类任务上显著优于传统方法，因此这里用它做最终修补。

流程
----
1. 定位：复用 doubao.locate_by_template（实测六张真实导出图全部命中）；
2. 掩膜：字模掩膜 ∪ 画面实测的细笔画，适度膨胀以覆盖抗锯齿；
3. 修补：LaMa 推理（CPU 可用），只在掩膜区域替换，其余像素零改动；
4. 回退：若模型不可用，退化到传统 TELEA+NS，保证功能不消失。
"""
from __future__ import annotations

import os
import threading
from typing import Optional

import cv2
import numpy as np

_lock = threading.Lock()
_model = None
_model_error: Optional[str] = None


# ----------------------------------------------------------------------------
# 1. 定位与掩膜
# ----------------------------------------------------------------------------

def build_mask(bgr: np.ndarray, strength: int = 4, height_ratio: float = 0.030,
               extra_dilate: Optional[int] = None):
    """生成水印修补掩膜。返回 (mask 0/255 uint8, info dict)。

    掩膜来源 = 字模笔画（定尺度） ∪ 画面实测的细笔画（定真实字形），
    再按强度膨胀。实测：只靠字模会在垂直方向错位（真实字形与渲染字模
    可差 20+px），只靠画面抠取又容易碎，两者取并集最稳。
    """
    from . import doubao as D

    h, w = bgr.shape[:2]
    bbox, score, px = D.locate_by_template(bgr, height_ratio=height_ratio)
    info = {"found": False, "score": round(float(score), 3), "px": px, "bbox": bbox}
    if bbox is None or score < 0.45:
        return None, info

    x0, y0, x1, y1 = bbox
    x0 = max(0, x0); y0 = max(0, y0); x1 = min(w, x1); y1 = min(h, y1)
    th, tw = y1 - y0, x1 - x0
    if th < 8 or tw < 16:
        return None, info

    t = D.render_template(px)
    if t is None:
        return None, info
    t = cv2.resize(t, (tw, th), interpolation=cv2.INTER_LINEAR)

    region = bgr[y0:y1, x0:x1].astype(np.float32)
    g0 = region.mean(axis=2)
    kbg = max(9, int(th * 1.5)) | 1
    rbg = cv2.medianBlur(g0.astype(np.uint8), kbg).astype(np.float32)
    dev = np.abs(g0 - rbg)
    sig = 1.4826 * float(np.median(np.abs(dev - np.median(dev))))

    pad = max(3, int(th * 0.45))
    near = cv2.dilate((t > 0.20).astype(np.uint8),
                      cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * pad + 1,) * 2)) > 0
    cand = ((dev > max(1.6 * sig, 1.6)) & near).astype(np.uint8)
    cand = cv2.morphologyEx(cand, cv2.MORPH_CLOSE,
                            cv2.getStructuringElement(cv2.MORPH_RECT, (max(5, th // 3) | 1, 3)))
    n, lb, st, _ = cv2.connectedComponentsWithStats(cand, 8)
    pic = np.zeros_like(cand)
    for i in range(1, n):
        _, _, bw, bh, area = st[i]
        if area < 4 or bh > th * 1.35 or bw > tw * 1.05:
            continue
        pic[lb == i] = 1
    pic |= ((cand > 0) & (t > 0.45)).astype(np.uint8)

    base = ((t > 0.30).astype(np.uint8) | pic)
    grow = {1: 1, 2: 2, 3: 2, 4: 3, 5: 4}.get(strength, 3)
    if extra_dilate is not None:
        grow = max(grow, int(extra_dilate))
    if grow > 0:
        base = cv2.dilate(base, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * grow + 1,) * 2))

    # ---- 掩膜：把水印**整块**封住 ----
    # 三轮才定位到的关键教训：
    #   1) 真实水印比渲染字模**大一圈**（实测宽高比 5.4 vs 字模 5.0，豆包用更扁宽的字体）；
    #   2) 只要掩膜外还留着**任何一点**水印笔画，LaMa 就会把它当上下文采样，
    #      在掩膜内"画出"水印的影子，结果比不处理更难看（实测乱码块/深色残影）。
    # 所以这里不描边、不抠字形，直接用"实测字形外接矩形 + 余量"整块封住。
    # 多盖一点背景，LaMa 补得远比漏盖好——实测残留从 29~88% 降到 0~27%。
    g_all = region.mean(axis=2).astype(np.float32)
    rbg_all = cv2.medianBlur(g_all.astype(np.uint8), max(9, int(th * 1.5)) | 1).astype(np.float32)
    dev_all = np.abs(g_all - rbg_all)
    sig_all = 1.4826 * float(np.median(np.abs(dev_all - np.median(dev_all))))
    strong = dev_all > max(1.2 * sig_all, 1.2)
    cover = strong | (t > 0.25)

    base = np.zeros((th, tw), np.uint8)
    ys, xs = np.nonzero(cover)
    if len(ys) >= 20:
        my = max(2, int(round(th * 0.25)))
        mx = max(4, int(round(th * 0.55)))
        gy0 = max(0, int(ys.min()) - my); gy1 = min(th - 1, int(ys.max()) + my)
        gx0 = max(0, int(xs.min()) - mx); gx1 = min(tw - 1, int(xs.max()) + mx)
        base[gy0:gy1 + 1, gx0:gx1 + 1] = 1
    else:
        base[:, :] = 1

    grow = {1: 5, 2: 6, 3: 8, 4: 10, 5: 14}.get(strength, 10)
    if extra_dilate is not None:
        grow = max(grow, int(extra_dilate))
    if grow > 0:
        base = cv2.dilate(base, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * grow + 1,) * 2))

    # ---- 把掩膜投影到"整图坐标系"，并按实测字形再放宽一圈 ----
    # 关键：掩膜不能只限在字模窗口内。实测水印比字模宽约 15%~25%，
    # 也常比窗口高一截；一旦越出窗口，那部分笔画就永远盖不住，
    # LaMa 会照它"画出"水印影子。所以这里先算整图里的实际覆盖范围，
    # 再按字高往外放余量，最后才生成掩膜。
    ys_b, xs_b = np.nonzero(base)
    if len(ys_b) == 0:
        return None, info
    gx0 = x0 + int(xs_b.min()); gx1 = x0 + int(xs_b.max())
    gy0 = y0 + int(ys_b.min()); gy1 = y0 + int(ys_b.max())
    my = max(4, int(round(th * 0.40)))
    mx = max(6, int(round(th * 1.00)))
    gx0 = max(0, gx0 - mx); gy0 = max(0, gy0 - my)
    gx1 = min(w - 1, gx1 + mx); gy1 = min(h - 1, gy1 + my)

    mask = np.zeros((h, w), np.uint8)
    mask[gy0:gy1 + 1, gx0:gx1 + 1] = 255
    # 豆包水印贴右边与下边：直接补到图像边界，避免在角上留一条缝被当成上下文采样
    if gx1 >= w - 1 - mx * 2:
        mask[gy0:gy1 + 1, gx1 + 1:w] = 255
    if gy1 >= h - 1 - my * 2:
        mask[gy1 + 1:h, gx0:gx1 + 1] = 255
    info.update(found=True, mask_px=int((mask > 0).sum()),
                coverage=round(float((mask > 0).mean()), 5), grow=grow,
                final_box=(gx0, gy0, gx1, gy1))
    return mask, info


# ----------------------------------------------------------------------------
# 2. LaMa 推理
# ----------------------------------------------------------------------------

def _bundled_model_path() -> Optional[str]:
    """查找随程序打包的模型文件（离线可用，避免首次运行去下载）。

    优先顺序：
      1) 环境变量 LAMA_MODEL_URL（用户/我们自己指定）；
      2) PyInstaller 解包目录 / 程序目录下的 assets/big-lama.pt；
      3) 开发目录 app/assets/big-lama.pt。
    """
    from pathlib import Path
    import sys

    env = os.environ.get("LAMA_MODEL_URL")
    if env and os.path.exists(env):
        return env
    cands = []
    if hasattr(sys, "_MEIPASS"):
        cands.append(Path(sys._MEIPASS) / "assets" / "big-lama.pt")
    if getattr(sys, "frozen", False):
        cands.append(Path(sys.executable).resolve().parent / "assets" / "big-lama.pt")
    cands.append(Path(__file__).resolve().parents[1] / "assets" / "big-lama.pt")
    for c in cands:
        if c.exists() and c.stat().st_size > 10 * 1024 * 1024:
            return str(c)
    return None


def _torch_env_setup() -> None:
    """在 import torch 之前设置好环境变量，避免冻结环境下的已知崩溃。

    PyInstaller 打包后源码不再以文件形式存在，torch 的 Dynamo/JIT 会去
    inspect 源码并抛 `OSError: could not get source code`，或直接把进程打崩
    （实测 0xC0000409）。这里提前关掉这些用不到的特性。
    """
    os.environ.setdefault("TORCH_COMPILE_DISABLE", "1")
    os.environ.setdefault("TORCHDYNAMO_DISABLE", "1")
    # 注意：**不要**设 PYTORCH_JIT=0 —— LaMa 权重是 TorchScript 归档，
    # 关掉 JIT 后加载会报 "RecursiveScriptModule has no attribute '_construct'"（实测踩过）
    os.environ.setdefault("KMP_DUPLICATE_LIB_OK", "TRUE")   # 避免 OpenMP 重复加载冲突
    os.environ.setdefault("OMP_NUM_THREADS", str(min(8, (os.cpu_count() or 4))))


def _load_model():
    """惰性加载 LaMa。若随包带了模型就走本地文件，否则回退到联网下载。"""
    global _model, _model_error
    with _lock:
        if _model is not None:
            return _model, None
        if _model_error is not None:
            return None, _model_error
        try:
            _torch_env_setup()
            # 冻结环境下 torch 会因 inspect.getsource 失败而无法 import，先修补
            try:
                from . import torch_fix
                torch_fix.apply()
            except Exception:
                pass
            local = _bundled_model_path()
            if local:
                # simple_lama_inpainting 从 LAMA_MODEL_URL 取权重；
                # 指向本地文件时 torch.hub 会直接加载、不联网
                os.environ["LAMA_MODEL_URL"] = local
            from simple_lama_inpainting import SimpleLama
            _model = SimpleLama()
            return _model, None
        except Exception as e:                       # noqa: BLE001
            _model_error = f"{type(e).__name__}: {e}"
            return None, _model_error


def lama_available() -> tuple:
    """返回 (可用?, 说明)。不触发下载，只看依赖是否就绪。"""
    try:
        import torch  # noqa: F401
        import simple_lama_inpainting  # noqa: F401
    except Exception as e:                           # noqa: BLE001
        return False, f"缺少依赖：{type(e).__name__}: {e}"
    if _model_error:
        return False, _model_error
    return True, "就绪"


def _inpaint_lama(bgr: np.ndarray, mask: np.ndarray, max_side: int = 1024):
    """用 LaMa 修补。大图先缩到 max_side 推理，再按掩膜贴回原尺寸。"""
    model, err = _load_model()
    if model is None:
        return None, err

    from PIL import Image

    h, w = bgr.shape[:2]
    scale = 1.0
    if max(h, w) > max_side:
        scale = max_side / float(max(h, w))
    if scale < 1.0:
        nw, nh = max(8, int(round(w * scale))), max(8, int(round(h * scale)))
    else:
        nw, nh = w, h
    # LaMa 要求尺寸是 8 的倍数
    pw = (8 - nw % 8) % 8
    ph = (8 - nh % 8) % 8

    small = cv2.resize(bgr, (nw, nh), interpolation=cv2.INTER_AREA if scale < 1 else cv2.INTER_LINEAR)
    smask = cv2.resize(mask, (nw, nh), interpolation=cv2.INTER_NEAREST)
    if pw or ph:
        small = cv2.copyMakeBorder(small, 0, ph, 0, pw, cv2.BORDER_REPLICATE)
        smask = cv2.copyMakeBorder(smask, 0, ph, 0, pw, cv2.BORDER_CONSTANT, value=0)

    img_rgb = cv2.cvtColor(small, cv2.COLOR_BGR2RGB)
    pil_img = Image.fromarray(img_rgb)
    pil_mask = Image.fromarray(smask, mode="L")
    try:
        import torch
        with torch.inference_mode():
            out = model(pil_img, pil_mask)
    except Exception as e:                           # noqa: BLE001
        return None, f"推理失败：{type(e).__name__}: {e}"

    res_rgb = np.asarray(out.convert("RGB"))
    res = cv2.cvtColor(res_rgb, cv2.COLOR_RGB2BGR)
    if pw or ph:
        res = res[:nh, :nw]
    if scale < 1.0:
        res = cv2.resize(res, (w, h), interpolation=cv2.INTER_LANCZOS4)
    return res, None


def _inpaint_cv(bgr: np.ndarray, mask: np.ndarray, radius: int = 5):
    """传统修补回退（LaMa 不可用时）。"""
    telea = cv2.inpaint(bgr, mask, radius, cv2.INPAINT_TELEA)
    ns = cv2.inpaint(bgr, mask, radius + 1, cv2.INPAINT_NS)
    return (telea.astype(np.float32) * 0.5 + ns.astype(np.float32) * 0.5).astype(np.uint8)


# ----------------------------------------------------------------------------
# 3. 对外接口
# ----------------------------------------------------------------------------

def clean(bgr: np.ndarray, strength: int = 4, use_lama: bool = True,
          max_side: int = 1024, feather: float = 1.0):
    """清理豆包白色描边水印。返回 (结果图, info)。

    use_lama=True 时用 LaMa 修补（推荐）；不可用时自动回退传统修补，
    info['engine'] 会说明实际用了哪个。
    """
    mask, info = build_mask(bgr, strength=strength)
    if mask is None or int(mask.sum()) == 0:
        info.setdefault("found", False)
        return bgr.copy(), info

    engine = "cv"
    out = None
    if use_lama:
        res, err = _inpaint_lama(bgr, mask, max_side=max_side)
        if res is not None:
            out = res
            engine = "lama"
        else:
            info["lama_error"] = err

    if out is None:
        rad = max(3, int(round(min(bgr.shape[:2]) * 0.004)) + 2)
        out = _inpaint_cv(bgr, mask, rad)

    # 只在掩膜内贴回（掩膜外零改动），并做羽化消除接缝
    mk = (mask > 0)
    wf = np.clip(cv2.GaussianBlur(mk.astype(np.float32), (0, 0), max(0.6, feather)), 0, 1)
    wf = (wf * mk)[..., None]
    merged = bgr.astype(np.float32) * (1 - wf) + out.astype(np.float32) * wf
    merged = np.clip(merged, 0, 255).astype(np.uint8)

    d = np.abs(merged.astype(np.float32) - bgr.astype(np.float32)).mean(axis=2)
    info.update(engine=engine,
                changed_px=int((d > 0.5).sum()),
                mean_change=round(float(d[d > 0.5].mean()) if (d > 0.5).any() else 0.0, 3),
                max_change=round(float(d.max()), 2))
    return merged, info
