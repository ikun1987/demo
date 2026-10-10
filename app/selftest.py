# -*- coding: utf-8 -*-
"""合成水印回环自测：注入已知水印 -> 去除 -> 与干净原图比对。

用法:
    python selftest.py [干净原图] [--out 报告目录]
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont

sys.path.insert(0, str(Path(__file__).resolve().parent))
from core import watermark as W  # noqa: E402

FONT_CANDIDATES = [
    r"C:\Windows\Fonts\msyhbd.ttc",
    r"C:\Windows\Fonts\msyh.ttc",
    r"C:\Windows\Fonts\simhei.ttf",
    r"C:\Windows\Fonts\Deng.ttf",
]


def pick_font(size: int) -> ImageFont.FreeTypeFont:
    for f in FONT_CANDIDATES:
        if Path(f).exists():
            try:
                return ImageFont.truetype(f, size)
            except Exception:
                continue
    return ImageFont.load_default()


def make_template(text: str, px: int):
    """渲染灰度字模，返回 (alpha 0..1 浮点, 宽, 高)。"""
    font = pick_font(px)
    probe = Image.new("L", (px * (len(text) + 4), px * 3), 0)
    d = ImageDraw.Draw(probe)
    d.text((px, px), text, fill=255, font=font)
    a = np.asarray(probe).astype(np.float32)
    ys, xs = np.nonzero(a > 6)
    if len(xs) == 0:
        raise RuntimeError("字模渲染失败")
    a = a[ys.min():ys.max() + 1, xs.min():xs.max() + 1] / 255.0
    return a


def inject(clean_bgr: np.ndarray, text="豆包AI生成", alpha=0.12, gray=200,
           margin=(48, 40), height_ratio=0.016, corner="br"):
    """在干净图上按半透明方式注入水印，返回 (带水印图, 真值掩膜)。"""
    if clean_bgr.ndim == 2:
        clean_bgr = cv2.cvtColor(clean_bgr, cv2.COLOR_GRAY2BGR)
    if clean_bgr.shape[2] == 4:
        clean_bgr = cv2.cvtColor(clean_bgr, cv2.COLOR_BGRA2BGR)
    h, w = clean_bgr.shape[:2]
    px = max(10, int(round(min(h, w) * height_ratio)))
    tmpl = make_template(text, px)
    th, tw = tmpl.shape
    mx, my = margin
    if corner == "br":
        x0, y0 = w - mx - tw, h - my - th
    elif corner == "bl":
        x0, y0 = mx, h - my - th
    elif corner == "tr":
        x0, y0 = w - mx - tw, my
    else:
        x0, y0 = mx, my
    x0 = max(0, min(w - tw, x0)); y0 = max(0, min(h - th, y0))

    out = clean_bgr.astype(np.float32).copy()
    a = (tmpl * alpha)[..., None]
    region = out[y0:y0 + th, x0:x0 + tw]
    wm = np.full_like(region, float(gray))
    out[y0:y0 + th, x0:x0 + tw] = region * (1 - a) + wm * a

    mask = np.zeros((h, w), np.uint8)
    # 真值掩膜：所有被水印影响超过 0.5 灰阶的像素
    lum = region.mean(axis=2).reshape(th, tw).astype(np.float32)
    delta = tmpl.reshape(th, tw).astype(np.float32) * alpha * np.abs(lum - float(gray))
    mask[y0:y0 + th, x0:x0 + tw] = ((delta > 0.5).astype(np.uint8) * 255)
    return np.clip(out, 0, 255).astype(np.uint8), mask


def metrics(clean, got, mask):
    c = clean.astype(np.float32); g = got.astype(np.float32)
    m = mask > 0
    diff_all = np.abs(c - g).mean(axis=2)
    mse = float((diff_all ** 2).mean())
    psnr = 10 * np.log10(255.0 ** 2 / max(mse, 1e-12))
    return {
        "psnr_all": round(psnr, 3),
        "maxerr_all": round(float(diff_all.max()), 3),
        "meanerr_all": round(float(diff_all.mean()), 4),
        "maxerr_inmask": round(float(diff_all[m].max()), 3) if m.sum() else 0.0,
        "meanerr_inmask": round(float(diff_all[m].mean()), 4) if m.sum() else 0.0,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("clean", nargs="?", default=r"C:\Users\26235\Desktop\probe_sub\yuwater\sample_doubao.png")
    ap.add_argument("--out", default=r"C:\Users\26235\Desktop\probe_sub\yuwater\selftest")
    args = ap.parse_args()

    outdir = Path(args.out); outdir.mkdir(parents=True, exist_ok=True)
    clean = cv2.imdecode(np.fromfile(args.clean, dtype=np.uint8), cv2.IMREAD_COLOR)
    if clean is None:
        raise SystemExit(f"读不到图片: {args.clean}")
    print(f"原图: {args.clean}  {clean.shape[1]}x{clean.shape[0]}")

    cases = []
    for alpha in (0.04, 0.08, 0.12, 0.20, 0.35):
        for gray in (200, 128):
            for corner in ("br",):
                cases.append(dict(alpha=alpha, gray=gray, corner=corner, height_ratio=0.016))
    # 再加一个"水印压在深色内容上"的用例
    cases.append(dict(alpha=0.25, gray=200, corner="br", height_ratio=0.016, tag="压内容"))

    rows = []
    for i, cs in enumerate(cases):
        tag = cs.pop("tag", "")
        wm_img, truth = inject(clean, **cs)
        for strength in (3, 5):
            got, det, rep = W.remove(wm_img, strength=strength, preset="auto")
            mt = metrics(clean, got, truth)
            base = metrics(clean, wm_img, truth)   # 未处理基线
            row = dict(case=i, tag=tag, strength=strength, **{k: cs[k] for k in ("alpha", "gray", "corner")},
                       **mt,
                       detected=int(det.found), conf=round(det.conf, 3),
                       mask_px=rep.mask_pixels, truth_px=int((truth > 0).sum()),
                       peak_before=round(rep.peak_before, 2), peak_after=round(rep.peak_after, 2),
                       baseline_maxerr=base["maxerr_inmask"],
                       baseline_psnr=base["psnr_all"])
            rows.append(row)
            if strength == 3:
                nm = f"case{i:02d}_a{int(cs['alpha']*100):02d}_g{cs['gray']}{'_' + tag if tag else ''}"
                cv2.imencode(".png", wm_img)[1].tofile(str(outdir / f"{nm}_in.png"))
                cv2.imencode(".png", got)[1].tofile(str(outdir / f"{nm}_out.png"))
                cv2.imencode(".png", truth)[1].tofile(str(outdir / f"{nm}_truth.png"))

    print(f"\n{'用例':<26}{'强度':>4}{'检出':>5}{'掩膜px':>7}{'真值px':>7}"
          f"{'PSNR':>7}{'未处理PSNR':>10}{'掩膜内最大误差':>13}{'未处理最大':>10}{'峰残差 前→后':>14}")
    for r in rows:
        name = f"a={r['alpha']:.2f} g={r['gray']}{r['tag']}"
        print(f"{name:<26}{r['strength']:>4}{r['detected']:>5}{r['mask_px']:>7}{r['truth_px']:>7}"
              f"{r['psnr_all']:>7.2f}{r['baseline_psnr']:>10.2f}{r['maxerr_inmask']:>13.2f}"
              f"{r['baseline_maxerr']:>10.2f}{r['peak_before']:>8.1f}→{r['peak_after']:<5.1f}")

    worst = max(rows, key=lambda r: r["maxerr_inmask"])
    print("\n最差用例:", json.dumps(worst, ensure_ascii=False))
    (outdir / "report.json").write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
    print("报告:", outdir / "report.json")


if __name__ == "__main__":
    main()
