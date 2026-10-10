# -*- coding: utf-8 -*-
"""把 big-lama.pt（TorchScript）导出为 ONNX，供浏览器 ONNX Runtime Web 使用。

要点
----
· 用 torch.jit.load 直接读 TorchScript 归档（就是 simple_lama_inpainting 用的那个）；
· 输入是 (image, mask) 两张 4 维张量：NCHW，值域 0~1；
· 固定导出尺寸到一个 8 的倍数（LaMa 内部 FFC 要求）；
· 导出后用 onnxruntime 跑一遍，和 torch 输出比对，确认转换无损。
"""
from __future__ import annotations

import os
import sys
import time

import numpy as np
import torch

SRC = os.path.join(os.path.expanduser("~"), ".cache", "torch", "hub", "checkpoints", "big-lama.pt")
if not os.path.exists(SRC):
    SRC = r"C:\Users\26235\Desktop\probe_sub\yuwater\app\assets\big-lama.pt"
OUT_ONNX = r"C:\Users\26235\Desktop\probe_sub\yuwater\web_model\big-lama.onnx"
os.makedirs(os.path.dirname(OUT_ONNX), exist_ok=True)

SIZE = 512          # 导出尺寸（8 的倍数）
print(f"源模型: {SRC} ({os.path.getsize(SRC)/1048576:.1f} MB)")

print("1) 加载 TorchScript 模型…")
t0 = time.time()
model = torch.jit.load(SRC, map_location="cpu")
model.eval()
print(f"   完成 {time.time()-t0:.1f}s")

print(f"2) 导出 ONNX（{SIZE}x{SIZE}）…")
img = torch.rand(1, 3, SIZE, SIZE)
mask = torch.zeros(1, 1, SIZE, SIZE)
mask[:, :, 100:200, 100:200] = 1.0
t0 = time.time()
with torch.inference_mode():
    torch.onnx.export(
        model,
        (img, mask),
        OUT_ONNX,
        input_names=["image", "mask"],
        output_names=["output"],
        opset_version=17,
        do_constant_folding=True,
        dynamo=False,
    )
print(f"   完成 {time.time()-t0:.1f}s  体积 {os.path.getsize(OUT_ONNX)/1048576:.1f} MB")

print("3) 校验：ONNX Runtime vs PyTorch")
import onnxruntime as ort
sess = ort.InferenceSession(OUT_ONNX, providers=["CPUExecutionProvider"])
with torch.inference_mode():
    ref = model(img, mask).numpy()
got = sess.run(None, {"image": img.numpy(), "mask": mask.numpy()})[0]
diff = np.abs(ref - got)
print(f"   输出形状 torch={ref.shape} onnx={got.shape}")
print(f"   最大差异={diff.max():.6f}  平均差异={diff.mean():.6f}")
print("   判定:", "通过（转换无损）" if diff.max() < 1e-3 else "差异偏大，需检查")

# 顺便测推理速度
t0 = time.time()
for _ in range(2):
    sess.run(None, {"image": img.numpy(), "mask": mask.numpy()})
print(f"4) ONNX CPU 推理 {(time.time()-t0)/2*1000:.0f} ms/张（{SIZE}x{SIZE}）")
print("输出:", OUT_ONNX)
