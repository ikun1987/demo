import sys, numpy as np, cv2, time
sys.path.insert(0, r"C:\Users\26235\Desktop\probe_sub\yuwater\app")
from core import watermark as W

cases = [(16,16), (40,40), (64,120), (120,64), (200,200), (1280,1280), (6000,400)]
print(f"{'尺寸':>12}{'灰':>5}{'RGBA':>6}{'检出':>6}{'掩膜px':>8}{'耗时s':>8}")
for (w,h) in cases:
    for mode in ("bgr","gray","rgba"):
        if mode=="gray":
            img = np.full((h,w), 250, np.uint8)
        elif mode=="rgba":
            img = np.full((h,w,4), 250, np.uint8); img[...,3]=200
        else:
            img = np.full((h,w,3), 250, np.uint8)
        t0=time.time()
        try:
            out, det, rep = W.remove(img, strength=4)
            ok=True; err=""
        except Exception as e:
            ok=False; err=f"{type(e).__name__}: {e}"; out=None
        dt=time.time()-t0
        shape_ok = (out is not None and out.shape == img.shape)
        print(f"{w}x{h:<8}{mode:>5}{str(shape_ok):>7}{int(det.found) if ok else 'ERR':>6}"
              f"{rep.mask_pixels if ok else 0:>8}{dt:>8.2f}" + ("" if ok else "  " + err))
