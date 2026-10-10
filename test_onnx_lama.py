# -*- coding: utf-8 -*-
"""用 ONNX 版 LaMa（int8, 512）在真实豆包图上测效果。

输入规格：input [1,4,512,512] float32，前 3 通道 RGB、第 4 通道 mask（0/1）；
输出 output [1,3,512,512] float32。

流程：原图缩到 512 → 掩膜同步缩放 → 推理 → 输出贴回原图掩膜区。
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
OUT = os.path.join(os.environ["TEMP"], "onnx_test")
os.makedirs(OUT, exist_ok=True)

sess = ort.InferenceSession(MODEL, providers=["CPUExecutionProvider"])
SIZE = 512


def inpaint_onnx(bgr: np.ndarray, mask: np.ndarray):
    """用 ONNX LaMa 修补。返回 (结果图, 耗时)。"""
    h, w = bgr.shape[:2]
    t0 = time.time()
    # 缩放到 512（保持比例），再用**边缘复制**填到 512x512。
    # 关键：不要用零填充 —— 模型会把黑边当内容，在掩膜附近补出白/黑块（实测踩过）。
    scale = SIZE / max(h, w)
    nw, nh = max(8, int(round(w * scale))), max(8, int(round(h * scale)))
    small = cv2.resize(bgr, (nw, nh), interpolation=cv2.INTER_AREA)
    smask = cv2.resize(mask, (nw, nh), interpolation=cv2.INTER_NEAREST)
    canvas = cv2.copyMakeBorder(small, 0, SIZE - nh, 0, SIZE - nw, cv2.BORDER_REPLICATE)
    mcan = cv2.copyMakeBorder(smask, 0, SIZE - nh, 0, SIZE - nw, cv2.BORDER_CONSTANT, value=0)

    rgb = cv2.cvtColor(canvas, cv2.COLOR_BGR2RGB).astype(np.float32) / 255.0
    m = (mcan > 0).astype(np.float32)
    inp = np.concatenate([rgb, m[..., None]], axis=2).transpose(2, 0, 1)[None]
    out = sess.run(["output"], {"input": inp})[0][0]
    res = np.clip(out.transpose(1, 2, 0) * 255.0, 0, 255).astype(np.uint8)
    res = cv2.cvtColor(res, cv2.COLOR_RGB2BGR)
    res = res[:nh, :nw]
    res = cv2.resize(res, (w, h), interpolation=cv2.INTER_LANCZOS4)
    dt = time.time() - t0

    mk = mask > 0
    wf = np.clip(cv2.GaussianBlur(mk.astype(np.float32), (0, 0), 1.0), 0, 1)[..., None] * mk[..., None]
    merged = bgr.astype(np.float32) * (1 - wf) + res.astype(np.float32) * wf
    return np.clip(merged, 0, 255).astype(np.uint8), dt


def main():
    indir = os.path.join(LAB, "in")
    files = sorted(f for f in os.listdir(indir) if f.lower().endswith(".jpg")) if os.path.isdir(indir) else []
    # 加上用户新发的那张
    extra = os.path.join(os.environ["TEMP"], "test_selfie.jpg")
    rows = []
    print(f"{'文件':<16}{'掩膜px':>9}{'ONNX耗时s':>10}{'真实笔画残留':>13}")
    for nm in files:
        p = os.path.join(LAB, "in", nm)
        bgr = cv2.imdecode(np.fromfile(p, np.uint8), cv2.IMREAD_COLOR)
        mask, info = LI.build_mask(bgr, strength=4)
        if mask is None:
            print(f"{nm:<16}{'定位失败':>9}")
            continue
        out, dt = inpaint_onnx(bgr, mask)
        h, w = bgr.shape[:2]
        x0, y0 = max(0, w - 300), max(0, h - 90)
        ga = bgr[y0:h, x0:w].mean(axis=2).astype(np.float32)
        gb = out[y0:h, x0:w].mean(axis=2).astype(np.float32)
        da = np.abs(ga - cv2.medianBlur(ga.astype(np.uint8), 41))
        db = np.abs(gb - cv2.medianBlur(gb.astype(np.uint8), 41))
        s = da > 5
        resid = 100 * (db[s] > 5).mean() if s.sum() else 0
        print(f"{nm:<16}{info['mask_px']:>9}{dt:>10.1f}{resid:>12.0f}%")
        cv2.imencode(".png", out)[1].tofile(os.path.join(OUT, nm.replace(".jpg", "_onnx.png")))
        rows.append((nm, bgr, out))

    # 用户新图
    if os.path.exists(extra):
        bgr = cv2.imdecode(np.fromfile(extra, np.uint8), cv2.IMREAD_COLOR)
        mask, info = LI.build_mask(bgr, strength=4)
        if mask is not None:
            out, dt = inpaint_onnx(bgr, mask)
            h, w = bgr.shape[:2]
            x0, y0 = max(0, w - 300), max(0, h - 90)
            ga = bgr[y0:h, x0:w].mean(axis=2).astype(np.float32)
            gb = out[y0:h, x0:w].mean(axis=2).astype(np.float32)
            da = np.abs(ga - cv2.medianBlur(ga.astype(np.uint8), 41))
            db = np.abs(gb - cv2.medianBlur(gb.astype(np.uint8), 41))
            s = da > 5
            resid = 100 * (db[s] > 5).mean() if s.sum() else 0
            print(f"{'新图_镜面自拍':<16}{info['mask_px']:>9}{dt:>10.1f}{resid:>12.0f}%")
            cv2.imencode(".png", out)[1].tofile(os.path.join(OUT, "新图_镜面自拍_onnx.png"))
            rows.append(("新图_镜面自拍", bgr, out))

    # 对比大图
    strip = []
    for nm, a, b in rows:
        h, w = a.shape[:2]
        x0, y0 = max(0, w - 420), max(0, h - 125)
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
    cv2.imencode(".png", np.vstack(strip))[1].tofile(os.path.join(OUT, "_ONNX对比.png"))
    print("\n输出:", OUT)


if __name__ == "__main__":
    main()
