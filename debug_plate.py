# -*- coding: utf-8 -*-
"""方案验证：用「能量最大的固定长宽比矩形」定位水印，再用字模精修。

思路（比多尺度字模打分鲁棒得多）：
  1. 算偏离图 dev = |灰度 - 局部背景|；
  2. 水印是「固定长宽比、尺寸随图缩放、贴右下角」的高偏离块，
     于是在右下角 ROI 内滑窗，找 **总偏离能量最大** 的矩形；
  3. 真水印的偏离能量比背景强烈得多（实测约 10 倍量级），
     所以这个判据不会被猫毛/条纹这类纹理骗到；
  4. 用字模在该矩形内精修位置，得到精确的字形外接框。
"""
from __future__ import annotations

import os
import sys

import numpy as np
import cv2

sys.path.insert(0, r"C:\Users\26235\Desktop\probe_sub\yuwater\app")
from core import doubao as D          # noqa: E402

IMGDIR = r"C:\Users\26235\Desktop\probe_sub\yuwater\testimages"
ASPECT = 5.0          # 水印字块宽高比（实测 4.3~5.4）


def devmap(gray):
    bg = cv2.medianBlur(gray.astype(np.uint8), 41).astype(np.float32)
    return np.abs(gray - bg)


def integral(a):
    return cv2.integral(a.astype(np.float64))


def rect_sum(I, x0, y0, x1, y1):
    return I[y1 + 1, x1 + 1] - I[y0, x1 + 1] - I[y1 + 1, x0] + I[y0, x0]


def find_plate(dev, W, H):
    """在右下角找能量最大的固定长宽比矩形。"""
    s = min(W, H)
    bh = max(12, int(round(s * 0.032)))          # 字高初值
    bw = int(round(bh * ASPECT))
    I = integral(dev)
    # ROI：右下角，留一点余量让水印完整落在里面
    roi_w = min(W, int(bw * 1.8))
    roi_h = min(H, int(bh * 3.0))
    best = None
    for h in range(max(10, int(bh * 0.75)), int(bh * 1.45) + 1, 2):
        w = int(round(h * ASPECT))
        if w >= W or h >= H:
            continue
        # 贴右下角搜索，允许偏移一个 roi
        for y1 in range(H - 1, max(h - 1, H - roi_h), -2):
            y0 = y1 - h + 1
            if y0 < 0:
                break
            for x1 in range(W - 1, max(w - 1, W - roi_w), -2):
                x0 = x1 - w + 1
                if x0 < 0:
                    break
                tot = rect_sum(I, x0, y0, x1, y1)
                if best is None or tot > best[0]:
                    best = (tot, x0, y0, x1, y1, w, h)
    return best


def main():
    files = sorted(f for f in os.listdir(IMGDIR) if f.lower().endswith(".jpg"))
    print(f"{'文件':<15}{'能量矩形 bbox':>28}{'字模精修 bbox':>28}{'字号':>6}")
    for f in files:
        bgr = cv2.imdecode(np.fromfile(os.path.join(IMGDIR, f), np.uint8), cv2.IMREAD_COLOR)
        g = bgr.mean(axis=2).astype(np.float32)
        H, W = g.shape
        dev = devmap(g)
        e = find_plate(dev, W, H)
        if e is None:
            print(f"{f:<15}{'未找到':>28}")
            continue
        _, px0, py0, px1, py1, pw, ph = e
        try:
            bb, sc, px = D.locate_by_template(bgr)
        except Exception:
            bb, sc, px = None, 0, 0
        print(f"{f:<15}{f'x[{px0},{px1}] y[{py0},{py1}] {pw}x{ph}':>28}"
              f"{str(bb):>28}{str(px):>6}")
        # 覆盖率检查
        print(f"    能量矩形 vs 字模框: {'包含' if bb and px0 <= bb[0] and px1 >= bb[2] and py0 <= bb[1] and py1 >= bb[3] else '不包含/偏差'}")


if __name__ == "__main__":
    main()
