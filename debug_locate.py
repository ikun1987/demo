# -*- coding: utf-8 -*-
"""调试水印定位的打分公式。

问题：原公式 score = 覆盖率×0.75 + 强度×0.25 中，
"覆盖率 = 笔画能量/窗口总能量" 会被背景里任何高对比纹理（猫毛、条纹）
骗到 —— 小字模随机落在几条毛边上就能拿高分，于是选错字号、
掩膜盖不住水印，修补后留下纹理残影。

这里对比多种打分，找在七张真实图上都稳定选对字号的方案。
"""
from __future__ import annotations

import os
import sys

import numpy as np
import cv2

sys.path.insert(0, r"C:\Users\26235\Desktop\probe_sub\yuwater\app")
from core import doubao as D          # noqa: E402

IMGDIR = r"C:\Users\26235\Desktop\probe_sub\yuwater\testimages"


def gray_of(bgr):
    return bgr.mean(axis=2).astype(np.float32)


def devmap(gray):
    bg = cv2.medianBlur(gray.astype(np.uint8), 41).astype(np.float32)
    return np.abs(gray - bg)


def template_masks():
    """各字号的字模（0/1），从 doubao.render_template 取。"""
    out = {}
    for px in range(20, 62):
        t = D.render_template(px)
        if t is None:
            continue
        arr = np.asarray(t, np.float32)
        if arr.ndim == 3:
            arr = arr[..., 0]
        if arr.max() > 1.5:
            arr = arr / 255.0
        out[px] = arr > 0.45
    return out


def main():
    tm = template_masks()
    print(f"可用字模字号: {min(tm)}~{max(tm)}，共 {len(tm)} 个\n")

    files = sorted(f for f in os.listdir(IMGDIR) if f.lower().endswith(".jpg"))
    print(f"{'文件':<15}{'旧公式':>8}{'新A(峰值)':>11}{'新B(笔画均值)':>14}{'新C(A*覆盖)':>13}")
    results = {}
    for f in files:
        bgr = cv2.imdecode(np.fromfile(os.path.join(IMGDIR, f), np.uint8), cv2.IMREAD_COLOR)
        g = gray_of(bgr)
        dev = devmap(g)
        H, W = g.shape
        s = min(W, H)
        base = max(9, round(s * 0.030))
        margin = max(4, round(s * 0.019))
        scales = [base + d for d in (-4, -2, -1, 0, 1, 2, 4) if base + d >= 9]

        rows = []
        for px in scales:
            if px not in tm:
                continue
            t = tm[px]
            th, tw = t.shape
            bx, by = W - margin - tw, H - margin - th
            if bx < 0 or by < 0:
                continue
            best = None
            for oy in range(max(0, by - 24), min(H - th, by + 24) + 1, 2):
                for ox in range(max(0, bx - 24), min(W - tw, bx + 24) + 1, 2):
                    win = dev[oy:oy + th, ox:ox + tw]
                    stroke = win[t]
                    total = float(win.sum())
                    if total <= 0 or stroke.size == 0:
                        continue
                    cover = float(stroke.sum()) / total
                    peak = float(stroke.mean())
                    cover_ratio = min(1.0, stroke.sum() / (total * 0.35))
                    cands = {
                        "old": cover * 0.75 + min(1.0, (stroke.mean()) / 30) * 0.25,
                        "peak": peak,
                        "stroke_mean": peak * cover_ratio,
                        "A_cover": (peak / 40.0) * cover_ratio,
                    }
                    if best is None or cands["peak"] > best[1]["peak"]:
                        best = ((ox, oy), cands)
            if best:
                rows.append((px, best[0], best[1]))

        def pick(key):
            return max(rows, key=lambda r: r[2][key])[0] if rows else None

        old_px, peak_px = pick("old"), pick("peak")
        sm_px, ac_px = pick("stroke_mean"), pick("A_cover")
        results[f] = (old_px, peak_px, sm_px, ac_px)
        print(f"{f:<15}{str(old_px):>8}{str(peak_px):>11}{str(sm_px):>14}{str(ac_px):>13}")

    print("\n参考：Python 生产版（doubao.locate_by_template）选的字号")
    for f in files:
        bgr = cv2.imdecode(np.fromfile(os.path.join(IMGDIR, f), np.uint8), cv2.IMREAD_COLOR)
        try:
            bb, sc, px = D.locate_by_template(bgr)
            print(f"  {f:<15} 字号={px} 分={sc:.3f} 框={bb}")
        except Exception as e:
            print(f"  {f:<15} 失败 {e}")


if __name__ == "__main__":
    main()
