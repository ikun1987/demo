# -*- coding: utf-8 -*-
"""ONNX LaMa 真图验证（正确的输入约定）。

关键：模型卡明确要求 —— 输入图**掩膜区必须先置零**，第 4 通道放 mask。
不置零的话模型把白色水印当内容，输出一片白（实测踩过）。

模型选择：lama_512_int8.onnx（62MB）—— 官方推荐给移动端 CPU/WASM，
在 CPU 上最快，且输出质量与 fp32 一致（合成用例掩膜内误差 1.22）。
"""
from __future__ import annotations

import os
import sys
import time

import numpy as np
import cv2
import onnxruntime as ort

sys.path.insert(0, r"C:\Users\26235\Desktop\probe_sub\yuwater\app")
from core import lama_inpaint as LI          # noqa: E402

MODEL = r"C:\Users\26235\Desktop\probe_sub\yuwater\web_model\lama_512_int8.onnx"
LAB = os.path.join(os.environ["TEMP"], "doubao_real")
OUT = os.path.join(os.environ["TEMP"], "onnx_final")
os.makedirs(OUT, exist_ok=True)
SIZE = 512
_sess = None


def sess():
    global _sess
    if _sess is None:
        _sess = ort.InferenceSession(MODEL, providers=["CPUExecutionProvider"])
    return _sess


def inpaint(bgr: np.ndarray, mask: np.ndarray):
    """ONNX LaMa 修补。返回 (结果图, 耗时, 原始模型输出)。"""
    h, w = bgr.shape[:2]
    t0 = time.time()
    scale = SIZE / max(h, w)
    nw, nh = max(8, int(round(w * scale))), max(8, int(round(h * scale)))
    small = cv2.resize(bgr, (nw, nh), interpolation=cv2.INTER_AREA)
    smask = cv2.resize(mask, (nw, nh), interpolation=cv2.INTER_NEAREST)
    # 边缘复制填充到 512（不要零填充，否则模型会在边界补出块）
    canvas = cv2.copyMakeBorder(small, 0, SIZE - nh, 0, SIZE - nw, cv2.BORDER_REPLICATE)
    mcan = cv2.copyMakeBorder(smask, 0, SIZE - nh, 0, SIZE - nw, cv2.BORDER_CONSTANT, value=0)

    mk = mcan > 0
    rgb = cv2.cvtColor(canvas, cv2.COLOR_BGR2RGB).astype(np.float32) / 255.0
    rgb[mk] = 0.0                                       # ★ 掩膜区置零（模型约定）
    m = mk.astype(np.float32)
    inp = np.concatenate([rgb, m[..., None]], axis=2).transpose(2, 0, 1)[None]
    out = sess().run(["output"], {"input": inp})[0][0]
    raw = cv2.cvtColor(np.clip(out.transpose(1, 2, 0) * 255, 0, 255).astype(np.uint8),
                       cv2.COLOR_RGB2BGR)[:nh, :nw]
    res = cv2.resize(raw, (w, h), interpolation=cv2.INTER_LANCZOS4)
    dt = time.time() - t0

    full_mk = mask > 0
    wf = np.clip(cv2.GaussianBlur(full_mk.astype(np.float32), (0, 0), 1.0), 0, 1)[..., None] * full_mk[..., None]
    merged = bgr.astype(np.float32) * (1 - wf) + res.astype(np.float32) * wf
    return np.clip(merged, 0, 255).astype(np.uint8), dt, raw


def main():
    indir = os.path.join(LAB, "in")
    files = sorted(f for f in os.listdir(indir) if f.lower().endswith(".jpg")) if os.path.isdir(indir) else []
    extra = os.path.join(os.environ["TEMP"], "test_selfie.jpg")
    rows = []
    print(f"{'文件':<16}{'掩膜px':>9}{'耗时s':>8}{'真实笔画残留>5':>15}{'掩膜外异常':>11}")
    for nm, p in [(f, os.path.join(indir, f)) for f in files] + \
                 ([("新图_镜面自拍.jpg", extra)] if os.path.exists(extra) else []):
        bgr = cv2.imdecode(np.fromfile(p, np.uint8), cv2.IMREAD_COLOR)
        if bgr is None:
            continue
        mask, info = LI.build_mask(bgr, strength=4)
        if mask is None:
            print(f"{nm:<16}{'定位失败':>9}")
            continue
        out, dt, _ = inpaint(bgr, mask)
        h, w = bgr.shape[:2]
        x0, y0 = max(0, w - 300), max(0, h - 90)
        ga = bgr[y0:h, x0:w].mean(axis=2).astype(np.float32)
        gb = out[y0:h, x0:w].mean(axis=2).astype(np.float32)
        da = np.abs(ga - cv2.medianBlur(ga.astype(np.uint8), 41))
        db = np.abs(gb - cv2.medianBlur(gb.astype(np.uint8), 41))
        s = da > 5
        resid = 100 * (db[s] > 5).mean() if s.sum() else 0
        mk = mask > 0
        d = np.abs(out.astype(np.float32) - bgr.astype(np.float32)).mean(axis=2)
        bad = int((d[~mk] > 6).sum())
        print(f"{nm:<16}{info['mask_px']:>9}{dt:>8.2f}{resid:>14.0f}%{bad:>11}")
        cv2.imencode(".jpg", out, [cv2.IMWRITE_JPEG_QUALITY, 98])[1].tofile(
            os.path.join(OUT, nm.replace(".jpg", "_onnx.jpg")))
        rows.append((nm, bgr, out))

    strip = []
    for nm, a, b in rows:
        h, w = a.shape[:2]
        x0, y0 = max(0, w - 430), max(0, h - 125)
        sep = np.full((h - y0, 10, 3), 40, np.uint8)
        st = np.hstack([a[y0:h, x0:w], sep, b[y0:h, x0:w]])
        W = st.shape[1]
        tag = np.full((22, W, 3), 12, np.uint8)
        cv2.putText(tag, nm[:13].encode("ascii", "ignore").decode(), (8, 16),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, (230, 230, 230), 1, cv2.LINE_AA)
        strip.append(np.vstack([tag, st, np.full((8, W, 3), 40, np.uint8)]))
    W = max(s.shape[1] for s in strip)
    strip = [np.hstack([s, np.full((s.shape[0], W - s.shape[1], 3), 12, np.uint8)]) if s.shape[1] < W else s
             for s in strip]
    cv2.imencode(".png", np.vstack(strip))[1].tofile(os.path.join(OUT, "_最终对比.png"))
    print("\n输出:", OUT)


if __name__ == "__main__":
    main()
