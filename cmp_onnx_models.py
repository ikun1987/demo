# -*- coding: utf-8 -*-
"""对比三个 ONNX LaMa 模型的输出质量（同一张图、同一掩膜）。"""
from __future__ import annotations

import os
import sys
import time

import numpy as np
import cv2
import onnxruntime as ort

sys.path.insert(0, r"C:\Users\26235\Desktop\probe_sub\yuwater\app")
from core import lama_inpaint as LI          # noqa: E402

MDL = r"C:\Users\26235\Desktop\probe_sub\yuwater\web_model"
LAB = os.path.join(os.environ["TEMP"], "doubao_real")
OUT = os.path.join(os.environ["TEMP"], "onnx_cmp")
os.makedirs(OUT, exist_ok=True)
SIZE = 512


def make_input(bgr, mask):
    """返回 (拼接式输入, 分离式 image, 分离式 mask, 原尺寸, 缩放后尺寸)。"""
    h, w = bgr.shape[:2]
    scale = SIZE / max(h, w)
    nw, nh = max(8, int(round(w * scale))), max(8, int(round(h * scale)))
    small = cv2.resize(bgr, (nw, nh), interpolation=cv2.INTER_AREA)
    smask = cv2.resize(mask, (nw, nh), interpolation=cv2.INTER_NEAREST)
    canvas = cv2.copyMakeBorder(small, 0, SIZE - nh, 0, SIZE - nw, cv2.BORDER_REPLICATE)
    mcan = cv2.copyMakeBorder(smask, 0, SIZE - nh, 0, SIZE - nw, cv2.BORDER_CONSTANT, value=0)
    rgb = cv2.cvtColor(canvas, cv2.COLOR_BGR2RGB).astype(np.float32) / 255.0
    m = (mcan > 0).astype(np.float32)
    cat = np.concatenate([rgb, m[..., None]], axis=2).transpose(2, 0, 1)[None]
    img4 = rgb.transpose(2, 0, 1)[None]
    m4 = m[None, None]
    return cat, img4, m4, (h, w), (nh, nw)


def run(sess, bgr, mask, kind):
    cat, img4, m4, (h, w), (nh, nw) = make_input(bgr, mask)
    t0 = time.time()
    if kind == "cat":
        out = sess.run(["output"], {"input": cat})[0]
    else:
        out = sess.run(["output"], {"image": img4, "mask": m4})[0]
    dt = time.time() - t0
    res = np.clip(out[0].transpose(1, 2, 0) * 255.0, 0, 255).astype(np.uint8)
    res = cv2.cvtColor(res, cv2.COLOR_RGB2BGR)[:nh, :nw]
    res = cv2.resize(res, (w, h), interpolation=cv2.INTER_LANCZOS4)
    mk = mask > 0
    wf = np.clip(cv2.GaussianBlur(mk.astype(np.float32), (0, 0), 1.0), 0, 1)[..., None] * mk[..., None]
    merged = bgr.astype(np.float32) * (1 - wf) + res.astype(np.float32) * wf
    return np.clip(merged, 0, 255).astype(np.uint8), dt, res


def main():
    models = [
        ("fp16_512", "lama_512_fp16.onnx", "cat"),
        ("int8_512", "lama_512_int8.onnx", "cat"),
        ("fp32", "lama_fp32.onnx", "split"),
    ]
    # 用两张代表性图：一张纯平背景、一张复杂背景
    test_files = ["1_点赞.jpg", "5_极客.jpg"]
    sess_list = []
    for tag, fn, kind in models:
        p = os.path.join(MDL, fn)
        if not os.path.exists(p):
            print(f"跳过 {tag}（文件不存在）")
            continue
        sess_list.append((tag, ort.InferenceSession(p, providers=["CPUExecutionProvider"]), kind))

    for nm in test_files:
        p = os.path.join(LAB, "in", nm)
        bgr = cv2.imdecode(np.fromfile(p, np.uint8), cv2.IMREAD_COLOR)
        mask, info = LI.build_mask(bgr, strength=4)
        if mask is None:
            continue
        print(f"\n=== {nm}  掩膜 {info['mask_px']}px ===")
        h, w = bgr.shape[:2]
        x0, y0 = max(0, w - 420), max(0, h - 125)
        panels = [bgr[y0:h, x0:w]]
        for tag, sess, kind in sess_list:
            out, dt, raw = run(sess, bgr, mask, kind)
            # 检查"未掩膜区域"是否被破坏（模型输出里掩膜外的部分不该有异常亮块）
            mk = mask > 0
            ext = np.abs(out.astype(np.float32) - bgr.astype(np.float32)).mean(axis=2)
            bad = int((ext[~mk] > 6).sum())
            print(f"  {tag:<10} 耗时 {dt:5.2f}s  掩膜外异常改动>6 的像素={bad}")
            panels.append(out[y0:h, x0:w])
        sep = np.full((panels[0].shape[0], 10, 3), 40, np.uint8)
        row = panels[0]
        for pa in panels[1:]:
            row = np.hstack([row, sep, pa])
        W = row.shape[1]
        tag_row = np.full((22, W, 3), 12, np.uint8)
        cv2.putText(tag_row, f"{nm}  [orig | " + " | ".join(t for t, _, _ in sess_list) + "]",
                    (8, 16), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (230, 230, 230), 1, cv2.LINE_AA)
        cv2.imencode(".png", np.vstack([tag_row, row]))[1].tofile(
            os.path.join(OUT, f"cmp_{nm.replace('.jpg','')}.png"))
    print("\n输出:", OUT)


if __name__ == "__main__":
    main()
