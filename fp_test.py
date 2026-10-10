import sys, numpy as np, cv2
sys.path.insert(0, r"C:\Users\26235\Desktop\probe_sub\yuwater\app")
from core import watermark as W
p = r"C:\Users\26235\Desktop\probe_sub\yuwater\sample_doubao.png"
img = cv2.imdecode(np.fromfile(p, np.uint8), cv2.IMREAD_COLOR)
print("=== 干净原图误伤测试（无真实水印的图） ===")
print(f"{'强度':>4}{'检出':>6}{'掩膜px':>8}{'最大改动':>10}{'改动>1px数':>11}{'改动>3px数':>11}{'全图PSNR':>10}")
for s in (1,2,3,4,5):
    out, det, rep = W.remove(img, strength=s, preset="auto")
    d = np.abs(out.astype(np.float32)-img.astype(np.float32)).mean(axis=2)
    mse = float((d**2).mean()); psnr = 10*np.log10(255**2/max(mse,1e-12))
    print(f"{s:>4}{int(det.found):>6}{rep.mask_pixels:>8}{d.max():>10.2f}{(d>1).sum():>11}{(d>3).sum():>11}{psnr:>10.2f}")
