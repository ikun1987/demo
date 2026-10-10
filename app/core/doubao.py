# -*- coding: utf-8 -*-
"""豆包水印清理 v2 —— 位置先验 + 字模能量打分 + 归一化反演。

为什么不用 cv2.matchTemplate(TM_CCOEFF_NORMED)：
    它在纹理底图（头发、桌面）上会给出 0.88 的假高分（实测 4_正面 误匹配到头发），
    而在淡描边字上只有 0.22（漏检）。原因是相关度会减掉均值、
    且对"绝对对比度"不敏感——淡字和强纹理都可能拿高分。

改用**能量打分**：把字模贴到候选位置，量"字模笔画处比字模空处暗/亮多少"，
    用局部标准差归一化。淡字在平坦底图上也能拿到高分，而在纹理上因为
    "空处"本身也乱，分母变大、分数被压下来。
"""
from __future__ import annotations

import os
from typing import Optional

import cv2
import numpy as np

FONT_CANDIDATES = [
    r"C:\Windows\Fonts\msyhbd.ttc",
    r"C:\Windows\Fonts\Deng.ttf",
    r"C:\Windows\Fonts\simhei.ttf",
    r"C:\Windows\Fonts\msyh.ttc",
]
WM_TEXT = "豆包AI生成"
_cache: dict = {}


def render_template(px: int) -> Optional[np.ndarray]:
    """渲染「豆包AI生成」字模，返回 0..1 覆盖度（裁剪到字形范围）。"""
    if px in _cache:
        return _cache[px]
    try:
        from PIL import Image, ImageDraw, ImageFont
    except Exception:
        return None
    path = next((f for f in FONT_CANDIDATES if os.path.exists(f)), None)
    if path is None:
        return None
    try:
        font = ImageFont.truetype(path, px)
    except Exception:
        return None
    probe = Image.new("L", (px * (len(WM_TEXT) + 4), px * 3), 0)
    ImageDraw.Draw(probe).text((px, px), WM_TEXT, fill=255, font=font, stroke_width=1)
    a = np.asarray(probe).astype(np.float32)
    ys, xs = np.nonzero(a > 8)
    if len(xs) == 0:
        return None
    t = a[ys.min():ys.max() + 1, xs.min():xs.max() + 1] / 255.0
    _cache[px] = t
    return t


def _deviation_map(bgr: np.ndarray, k: int):
    """返回 (归一化偏离图, 灰度, 局部背景)。偏离与极性无关（亮/暗都算）。"""
    gray = bgr.mean(axis=2).astype(np.float32)
    bg = cv2.medianBlur(gray.astype(np.uint8), int(k) | 1).astype(np.float32)
    dev = np.abs(gray - bg)
    return dev, gray, bg


def locate_by_template(bgr: np.ndarray, height_ratio: float = 0.030,
                       margin_ratio: float = 0.019, dy_range=(-34, 34),
                       dx_range=(-34, 34), px_list=None):
    """用"覆盖率分数"定位水印：字模必须吃掉窗口内大部分偏离能量。

    打分 = Σ偏离(字模笔画处) / Σ偏离(窗口全部)
      · 小字模只覆盖一小部分 → 分数低（修掉之前"偏爱小字号"的毛病）；
      · 错位的字模覆盖不到笔画 → 分数低；
      · 纹理区因为偏离分散在整窗，任何单一字模都覆盖不全 → 分数低。

    位置先验：贴右下角，边距约为短边的 1.9%（实测 1280 图为 24px）。
    返回 (bbox, score, px) 或 (None, 0, 0)。
    """
    h, w = bgr.shape[:2]
    s = min(h, w)
    gray = bgr.mean(axis=2).astype(np.float32)
    base = max(9, int(round(s * height_ratio)))
    k = int(max(21, base * 1.9)) | 1
    bg = cv2.medianBlur(gray.astype(np.uint8), k).astype(np.float32)
    dev = np.abs(gray - bg)
    margin = max(5, int(round(s * margin_ratio)))

    if px_list is None:
        px_list = [base + d for d in (-6, -4, -2, 0, 2, 4, 6)]
    best = None
    for px in px_list:
        if px < 8:
            continue
        t = render_template(px)
        if t is None:
            continue
        th, tw = t.shape
        # 让字模高度贴近目标字高：宽度允许压缩（豆包用的是窄体）
        inner = t > 0.45
        if inner.sum() < 20:
            continue
        bx0 = w - margin - tw
        by0 = h - margin - th
        for dy in range(dy_range[0], dy_range[1] + 1, 2):
            for dx in range(dx_range[0], dx_range[1] + 1, 2):
                xx, yy = bx0 + dx, by0 + dy
                if xx < 0 or yy < 0 or xx + tw > w or yy + th > h:
                    continue
                win = dev[yy:yy + th, xx:xx + tw]
                tot = float(win.sum())
                if tot <= 1e-6:
                    continue
                cov = float(win[inner].sum()) / tot
                # 覆盖率为主 + 笔画处平均偏离为辅，避免在纯黑区靠噪声取胜
                strong = float(win[inner].mean())
                score = cov * 0.75 + min(strong / 30.0, 1.0) * 0.25
                if best is None or score > best[0]:
                    best = (score, px, xx, yy, tw, th, cov, strong)
    if best is None:
        return None, 0.0, 0
    score, px, x0, y0, tw, th, cov, strong = best
    return (x0, y0, x0 + tw, y0 + th), float(np.clip(score, 0, 1)), px


def extract_watermark(bgr: np.ndarray, height_ratio: float = 0.032,
                      corner: str = "br", margin_px: int = 22):
    """直接从图里抠出"白色描边字"掩膜，不依赖模板对齐。

    Returns:
        (mask, bbox, alpha, info) —— mask 为 0/255 全图掩膜；
        bbox = (x0,y0,x1,y1)；alpha 为 0..1 的相对偏离强度（用于反演）。

    判据（全部来自实测的六张真实导出图）：
      1. 位置：贴着右下角，右边距/下边距约短边的 1.7~1.9%；
      2. 极性无关：字比局部背景亮或暗都算（亮底偏亮、暗底偏暗）；
      3. 笔画细：连通域在字高尺度上是细长的；
      4. 成行：多笔画像一行排布。
    """
    h, w = bgr.shape[:2]
    s = min(h, w)
    base = max(9, int(round(s * height_ratio)))
    k = int(max(21, base * 1.9)) | 1
    gray = bgr.mean(axis=2).astype(np.float32)
    bg = cv2.medianBlur(gray.astype(np.uint8), k).astype(np.float32)
    dev = np.abs(gray - bg)

    # 搜索窗：右下角，留足字宽（约 5.2 倍字高）
    win_w = int(base * 6.2)
    win_h = int(base * 2.6)
    x0 = max(0, w - margin_px - win_w)
    y0 = max(0, h - margin_px - win_h)
    win = dev[y0:h, x0:w]
    if win.size == 0:
        return None, None, None, {"found": False, "reason": "窗口为空"}

    sigma = 1.4826 * float(np.median(np.abs(win - np.median(win))))
    thr = max(3.0 * sigma, 2.5)
    m = (win > thr).astype(np.uint8)

    # 去掉粗大块（桌面、猫等），保留细笔画
    open_k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2, 2))
    m = cv2.morphologyEx(m, cv2.MORPH_OPEN, open_k)
    n, lab, stats, _ = cv2.connectedComponentsWithStats(m, 8)
    keep = np.zeros_like(m)
    for i in range(1, n):
        _, _, bw, bh, area = stats[i]
        if area < max(4, base * 0.12):
            continue
        if bh > base * 1.6 or bw > win.shape[1] * 0.9:      # 太大 → 不是笔画
            continue
        # 细长性
        comp = (lab == i).astype(np.uint8)
        cnts, _ = cv2.findContours(comp, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        if not cnts:
            continue
        (_, _), (a1, a2), _ = cv2.minAreaRect(np.vstack(cnts))
        if min(a1, a2) > base * 1.1:
            continue
        keep[lab == i] = 1
    if keep.sum() < 12:
        return None, None, None, {"found": False, "reason": f"笔画过少({int(keep.sum())})", "sigma": round(sigma, 2)}

    # 成行聚类：取像素最多的那条水平带
    rows = keep.sum(axis=1)
    segs, st = [], None
    for yy in range(len(rows)):
        if rows[yy] > 0 and st is None:
            st = yy
        elif rows[yy] == 0 and st is not None:
            segs.append((st, yy - 1)); st = None
    if st is not None:
        segs.append((st, len(rows) - 1))
    if not segs:
        return None, None, None, {"found": False, "reason": "无行带"}
    a, b = max(segs, key=lambda t: keep[t[0]:t[1] + 1].sum())
    band = np.zeros_like(keep)
    band[a:b + 1] = keep[a:b + 1]
    ys, xs = np.nonzero(band)
    if len(ys) < 12:
        return None, None, None, {"found": False, "reason": "行带为空"}

    gx0, gy0 = x0 + int(xs.min()), y0 + int(ys.min())
    gx1, gy1 = x0 + int(xs.max()), y0 + int(ys.max())
    full = np.zeros((h, w), np.uint8)
    full[gy0:gy1 + 1, gx0:gx1 + 1] = band[ys.min():ys.max() + 1, xs.min():xs.max() + 1] * 255

    # 膨胀吞掉抗锯齿边
    grow = max(1, int(base * 0.06))
    full = cv2.dilate(full, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * grow + 1,) * 2))
    # alpha：掩膜内的相对偏离强度（0..1）
    reg = dev[gy0:gy1 + 1, gx0:gx1 + 1]
    peak = float(np.percentile(reg[band[ys.min():ys.max() + 1, xs.min():xs.max() + 1] > 0], 95)) if band.sum() else 1.0
    alpha = np.zeros((h, w), np.float32)
    alpha[gy0:gy1 + 1, gx0:gx1 + 1] = np.clip(dev[gy0:gy1 + 1, gx0:gx1 + 1] / max(peak, 1.0), 0, 1)
    alpha = alpha * (full > 0)

    coverage = float(full.mean() / 255.0)
    info = {
        "found": True,
        "bbox": (gx0, gy0, gx1, gy1),
        "height": gy1 - gy0 + 1,
        "width": gx1 - gx0 + 1,
        "sigma": round(sigma, 2),
        "thr": round(float(thr), 2),
        "peak_dev": round(peak, 2),
        "components": int(n - 1),
        "coverage": round(coverage, 5),
    }
    return full, (gx0, gy0, gx1, gy1), alpha, info
    """定位水印。返回 (bbox, score, px) 或 (None, 0, 0)。

    用**位置强先验**收窄搜索：豆包水印固定在右下角，右边距/下边距在
    1280 图上均为约 24px（实测六张一致）。所以在"贴角位置"附近开一个小窗
    微调即可，避免在整幅右下区域里被纹理骗走。
    """
    h, w = bgr.shape[:2]
    s = min(h, w)
    base = max(9, int(round(s * height_ratio)))
    # 边距按图像短边等比缩放
    margin = max(6, int(round(margin_px * s / 1280.0)))
    k = int(max(21, base * 1.9)) | 1
    dev, gray, bg = _deviation_map(bgr, k)

    # 用"基准位置附近"的稳健尺度归一化
    scales = sorted({max(9, base + d) for d in (-4, -3, -2, -1, 0, 1, 2, 3, 4)})
    best = None
    for px in scales:
        t = render_template(px)
        if t is None:
            continue
        th, tw = t.shape
        if tw >= w - 2 * margin or th >= h - 2 * margin:
            continue
        # 贴角基准位置（右上/左上等仅作对称支持）
        bx = w - margin - tw
        by = h - margin - th
        if bx < 0 or by < 0:
            continue
        inner = t > 0.45
        scale_ref = float(np.percentile(dev[max(0, by - 10):h, max(0, bx - 10):w], 99.0)) if dev.size else 1.0
        scale_ref = max(scale_ref, 1.0)
        nrm = dev / scale_ref
        for dy in range(-search_pad, search_pad + 1, 2):
            for dx in range(-search_pad, search_pad + 1, 2):
                xx, yy = bx + dx, by + dy
                if xx < 0 or yy < 0 or xx + tw > w or yy + th > h:
                    continue
                blk = nrm[yy:yy + th, xx:xx + tw]
                sc = float(np.mean(np.sort(blk[inner])[-max(8, inner.sum() // 5):]))
                if best is None or sc > best[0]:
                    best = (sc, px, xx, yy, tw, th)
    if best is None:
        return None, 0.0, 0
    # 细搜：在粗搜最优位置附近 1px 步长
    sc0, px0, bx0, by0, tw0, th0 = best
    t = render_template(px0)
    scale_ref = float(np.percentile(dev[max(0, by0 - 10):h, max(0, bx0 - 10):w], 99.0)) or 1.0
    nrm = dev / max(scale_ref, 1.0)
    inner = t > 0.45
    for dy in range(-2, 3):
        for dx in range(-2, 3):
            xx, yy = bx0 + dx, by0 + dy
            if xx < 0 or yy < 0 or xx + tw0 > w or yy + th0 > h:
                continue
            blk = nrm[yy:yy + th0, xx:xx + tw0]
            sc = float(np.mean(np.sort(blk[inner])[-max(8, inner.sum() // 5):]))
            if sc > best[0]:
                best = (sc, px0, xx, yy, tw0, th0)
    sc, px, x0, y0, tw, th = best
    return (x0, y0, x0 + tw, y0 + th), float(np.clip(sc, 0.0, 1.0)), px


def clean(bgr: np.ndarray, strength: int = 4, height_ratio: float = 0.030,
          corner: str = "br", min_score: float = 0.45):
    """清理豆包白色描边水印。返回 (结果图, info)。

    流程：覆盖率定位 → 字模形状掩膜 ∩ 实际偏离 → 覆盖率反演 → 满覆盖处 inpaint。
    """
    h, w = bgr.shape[:2]
    bbox, score, px = locate_by_template(bgr, height_ratio=height_ratio)
    info = {"found": False, "score": round(float(score), 3), "px": px, "bbox": bbox}
    if bbox is None or score < min_score:
        return bgr.copy(), info

    x0, y0, x1, y1 = bbox
    t = render_template(px)
    if t is None:
        return bgr.copy(), info
    th, tw = t.shape
    if (y1 - y0) != th or (x1 - x0) != tw:
        t = cv2.resize(t, (max(1, x1 - x0), max(1, y1 - y0)), interpolation=cv2.INTER_LINEAR)

    region = bgr[y0:y1, x0:x1].astype(np.float32)
    if region.size == 0:
        return bgr.copy(), info

    # ---- 掩膜：以"画面实测的字形范围"为准 ----
    # 血泪教训：拿渲染字模直接当掩膜不行 —— 真实字形与字模在**垂直方向可差 20+ px**
    # （实测 2 号偏移 27px），结果掩膜盖在干净区域、真实笔画却漏在外面，
    # 于是既糊了背景又留了字。这里只借字模定"尺度与大致位置"，
    # 真正的掩膜由画面里的偏离像素长出来。
    g0 = region.mean(axis=2).astype(np.float32)
    kbg = max(9, int(th * 1.5)) | 1
    rbg = cv2.medianBlur(g0.astype(np.uint8), kbg).astype(np.float32)
    dev = np.abs(g0 - rbg)
    sig = 1.4826 * float(np.median(np.abs(dev - np.median(dev))))
    seed = dev > max(1.6 * sig, 1.6)
    # 字模的宽松包围范围：只保留"落在文字附近"的结构
    pad = max(3, int(th * 0.45))
    near = cv2.dilate((t > 0.20).astype(np.uint8),
                      cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * pad + 1,) * 2)) > 0
    cand = (seed & near).astype(np.uint8)
    # 横向桥接：把被字距切碎的部件连成一整行，同时避免纵向长高
    cand = cv2.morphologyEx(cand, cv2.MORPH_CLOSE,
                            cv2.getStructuringElement(cv2.MORPH_RECT, (max(5, th // 3) | 1, 3)))
    # 去掉过粗的块（猫毛、桌面纹理的粗结构）
    n, lb, st, _ = cv2.connectedComponentsWithStats(cand, 8)
    shape = np.zeros_like(cand)
    for i in range(1, n):
        x, y, bw, bh, area = st[i]
        if area < 4:
            continue
        if bh > th * 1.35:                      # 太高 → 不是文字行
            continue
        if bw > tw * 1.05:
            continue
        shape[lb == i] = 1
    # 兜底：并入字模笔画，防止淡淡的外缘没被 dev 抓到
    shape |= (cand > 0) & (t > 0.45)
    gg = max(1, int(round(th * 0.06)))
    shape = cv2.dilate(shape.astype(np.uint8),
                       cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * gg + 1,) * 2)) > 0
    shape &= cv2.dilate((t > 0.20).astype(np.uint8),
                        cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * (pad + gg) + 1,) * 2)) > 0
    if shape.sum() < 20:
        info["found"] = False
        info["reason"] = "形状掩膜过小"
        return bgr.copy(), info

    # ---- 填充：归一化卷积（Normalized Convolution）----
    # 只从**掩膜外**的像素做加权平均来估背景：
    #   背景(x) = Σ w·原图 / Σ w ，其中 w = 高斯核 × (1 - 掩膜)
    # 这是"缺失数据填充"的标准做法，平坦区精确、纹理区保结构，
    # 而且绝不会把掩膜内的水印值算进背景（中值/均值法的致命伤就在这）。
    r_blur = max(3.0, th * 0.45)
    valid = (~shape).astype(np.float32)
    wsum = cv2.GaussianBlur(valid, (0, 0), r_blur)
    wsum = np.maximum(wsum, 1e-3)

    fill = np.empty_like(region)
    for c in range(3):
        num = cv2.GaussianBlur(region[:, :, c] * valid, (0, 0), r_blur)
        fill[:, :, c] = num / wsum
    # 掩膜内若完全没有有效邻居（罕见），退回全图均值
    bad = (~np.isfinite(fill)).any(axis=2) | (wsum < 1e-2)
    if bad.any():
        for c in range(3):
            fill[:, :, c] = np.where(bad, float(region[:, :, c].mean()), fill[:, :, c])

    # 羽化只在掩膜内部收边，掩膜外一个像素都不动
    wfe = np.clip(cv2.GaussianBlur(shape.astype(np.float32), (0, 0), 0.7), 0, 1)[..., None]
    wfe = wfe * shape[..., None]
    rec = region * (1 - wfe) + fill * wfe

    work = bgr.copy()
    work[y0:y1, x0:x1] = np.clip(rec, 0, 255).astype(np.uint8)

    d = np.abs(work.astype(np.float32) - bgr.astype(np.float32)).mean(axis=2)
    info.update(found=True, mask_px=int(shape.sum()),
                changed_px=int((d > 0.5).sum()),
                mean_change=round(float(d[d > 0.5].mean()) if (d > 0.5).any() else 0.0, 3),
                max_change=round(float(d.max()), 2), strength=strength)
    return work, info

    d = np.abs(work.astype(np.float32) - bgr.astype(np.float32)).mean(axis=2)
    info.update(found=True, mask_px=int(shape.sum()), hard_px=int((hard > 0).sum()),
                changed_px=int((d > 0.5).sum()),
                mean_change=round(float(d[d > 0.5].mean()) if (d > 0.5).any() else 0.0, 3),
                max_change=round(float(d.max()), 2), strength=strength)
    return work, info
