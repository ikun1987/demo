import sys, numpy as np, cv2
sys.path.insert(0, r"C:\Users\26235\Desktop\probe_sub\yuwater\app")
from core import watermark as W
import selftest as ST

rng = np.random.default_rng(7)

def base(kind, h, w):
    if kind == "flat":
        return np.full((h, w, 3), 250, np.uint8)
    if kind == "gradient":
        g = np.linspace(180, 255, w, dtype=np.float32)[None, :].repeat(h, 0)
        return cv2.merge([g, g*0.98, g*0.95]).astype(np.uint8)
    if kind == "noise":
        g = np.clip(245 + rng.normal(0, 1.2, (h, w)), 0, 255).astype(np.uint8)
        return cv2.cvtColor(g, cv2.COLOR_GRAY2BGR)
    if kind == "texture":
        g = np.clip(235 + rng.normal(0, 6, (h, w)), 0, 255).astype(np.uint8)
        g = cv2.GaussianBlur(g, (0,0), 1.2)
        return cv2.cvtColor(g, cv2.COLOR_GRAY2BGR)
    if kind == "portrait":
        img = np.full((h, w, 3), 250, np.uint8)
        cv2.circle(img, (w//2, int(h*0.35)), int(min(h,w)*0.22), (90, 80, 70), -1)
        cv2.rectangle(img, (int(w*0.2), int(h*0.55)), (int(w*0.8), h), (40, 36, 32), -1)
        return img
    raise ValueError

print(f"{'底图':<10}{'尺寸':>11}{'α':>6}{'位置':>6}{'检出':>6}{'置信':>7}{'掩膜px':>8}{'掩膜内平均误差':>15}{'掩膜内最大':>11}{'全图PSNR':>10}")
rows=[]
for kind in ("flat", "gradient", "noise", "texture", "portrait"):
    for (h, w) in ((1024, 1024), (768, 1365), (1600, 900)):
        for alpha in (0.10, 0.25):
            for corner in ("br", "bl"):
                clean = base(kind, h, w)
                wm, truth = ST.inject(clean, alpha=alpha, gray=170, corner=corner)
                got, det, rep = W.remove(wm, strength=4, preset="corner_" + corner)
                d = np.abs(got.astype(np.float32) - clean.astype(np.float32)).mean(axis=2)
                m = truth > 0
                mse = float((d**2).mean()); psnr = 10*np.log10(255**2/max(mse,1e-12))
                rows.append((kind, h, w, alpha, corner, det.found, det.conf, rep.mask_pixels,
                             float(d[m].mean()) if m.sum() else 0, float(d.max()), psnr))
                print(f"{kind:<10}{w}x{h:<7}{alpha:>6.2f}{corner:>6}{int(det.found):>6}{det.conf:>7.2f}"
                      f"{rep.mask_pixels:>8}{rows[-1][8]:>15.3f}{rows[-1][9]:>11.2f}{psnr:>10.2f}")
bad = [r for r in rows if r[5] and r[8] > 2.0]
print(f"\n检出率 {sum(1 for r in rows if r[5])}/{len(rows)}；掩膜内平均误差>2 的用例数: {len(bad)}")
print(f"最大掩膜内平均误差: {max(r[8] for r in rows):.3f}  最大单点误差: {max(r[9] for r in rows):.2f}")
