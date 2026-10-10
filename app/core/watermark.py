# -*- coding: utf-8 -*-
"""玉用去水印 —— 水印检测 / 去除 / 渲染修复 核心引擎。

设计目标
--------
1. 针对豆包（Doubao）导出图右下角的浅灰半透明「豆包AI生成」字样；
2. 水印浓度跨度极大（从几乎不可见的 1 灰阶到明显可见的 120 灰阶）都能处理；
3. 先把文字区域还原成"没被覆盖时应该长什么样"，而不是简单涂抹，
   因此对文字压在内容（头发、衣褶、纹理）上的情况也尽量保住原图意愿；
4. 全程可量化：`selftest.py` 用合成水印回环比对 PSNR / 最大误差。

算法链路
--------
检测:
    R1 亮背景残差法 —— 局部中值背景 - 原图，抓"比背景暗"的文字笔画；
    R2 形状先验法 —— 在候选区域寻找符合"文字行"尺寸/密度的连通域；
    R3 阈值自适应 —— 阈值由 ROI 噪声的 MAD 估计动态给出，避免硬编码。
修复:
    Step1 半透明反混合（alpha-unmix）—— 已知水印为低饱和灰，估算覆盖比例 a，
          在 a<1 处直接解出原像素；
    Step2 背景引导修复（inpaint）—— 对完全被覆盖或反混合不可靠的像素，
          用 INPAINT_TELEA / NS 做结构感知填充；
    Step3 渲染修复（render repair）—— 用引导滤波把修复区的高频纹理从原图
          邻域重新注入，保证"保留原图意愿"，不出现糊块或色差。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Sequence, Tuple

import cv2
import numpy as np

# ----------------------------------------------------------------------------
# 常量
# ----------------------------------------------------------------------------

STRENGTH_NAMES = {1: "保守", 2: "轻柔", 3: "标准", 4: "强力", 5: "极致"}

# 每个强度档：(检测阈值系数, 掩膜膨胀次数, 反混合门控, 修复半径)
# 检测阈值统一取 3.0 sigma（够保守，不会把照片纹理当水印）；
# 强度只控制"反混合门控"与掩膜膨胀 —— 强度越高越肯剥极淡的水印。
STRENGTH_TABLE = {
    1: (3.0, 0, 1.10, 2),
    2: (3.0, 1, 0.75, 2),
    3: (3.0, 1, 0.45, 3),
    4: (3.0, 2, 0.25, 3),
    5: (3.0, 2, 0.05, 4),
}
DETECT_SIGMA = 3.0

# "有可去除水印"的实际改动门槛（掩膜内平均改动灰阶）。
# 实测分离度：干净照片误检掩膜内平均改动 0.40~0.50；最淡的真水印（α=0.12/灰200）
# 为 2.95，明显水印 4~19。取 1.5 落在 6 倍空档中央。
SIGNIFICANT_CHANGE = 1.5

# 豆包水印的已知先验：位于右下角，文字行高约为图像短边的 1.2%~2.4%
PRESET_ANCHORS = {
    "corner_br": (1.0, 1.0),
    "corner_bl": (0.0, 1.0),
    "corner_tr": (1.0, 0.0),
    "corner_tl": (0.0, 0.0),
}


@dataclass
class DetectResult:
    found: bool
    mask: np.ndarray            # uint8 0/255，与原图同尺寸
    coverage: float             # 掩膜占全图比例
    bbox: Optional[Tuple[int, int, int, int]]  # x0,y0,x1,y1
    peak: float                 # 最强残差
    threshold: float
    method: str
    conf: float                 # 0~1 置信度


@dataclass
class RemoveReport:
    mask_pixels: int
    unmixed_pixels: int
    inpainted_pixels: int
    coverage: float
    peak_before: float
    peak_after: float
    method: str
    conf: float
    change_mean: float = 0.0      # 掩膜内实际改动均值（灰阶），用于判定"有没有可去的东西"
    significant: bool = True      # False = 判定为"无可去除水印"，输出与输入保持一致


# ----------------------------------------------------------------------------
# 基础工具
# ----------------------------------------------------------------------------

def _to_gray(img: np.ndarray) -> np.ndarray:
    if img.ndim == 2:
        return img.astype(np.float32)
    return cv2.cvtColor(img, cv2.COLOR_BGR2GRAY).astype(np.float32)


def _noise_sigma(gray: np.ndarray, region: np.ndarray) -> float:
    """用 MAD 稳健估计噪声标准差。"""
    med = float(np.median(region))
    mad = float(np.median(np.abs(region - med)))
    sigma = 1.4826 * mad
    return max(sigma, 0.6)


def _median_u8(a: np.ndarray, k: int) -> np.ndarray:
    """8 位中值滤波（cv2.medianBlur 只吃 8U，故统一在此做类型转换）。"""
    return cv2.medianBlur(np.clip(a, 0, 255).astype(np.uint8), int(k) | 1).astype(np.float32)


def local_background(gray: np.ndarray, ksize: int) -> np.ndarray:
    """多方向中值 + 稳健上包络的背景估计。

    只对被"变暗"的水印有效，因此背景取"上包络"；但**单一大核膨胀**在缓慢渐变
    的底图上会把背景估到邻域最亮处（等于把渐变斜率当成残差），在噪声/纹理底图上
    膨胀的极值统计又会引入 ±3~5 灰阶的随机偏置，两者都会毁掉阈值判定。

    这里改为多方向、多尺度取稳健值：
      1. 横向 / 纵向 / 对角三个方向各做一次大核中值 -- 中值不会被细笔画拉低，
         也不像极值那样放大噪声，且能贴着渐变走；
      2. 三方向取**逐像素中位数**，进一步压掉单一方向上的噪声尖峰；
      3. 再叠一层小核上包络（dilate）把包络抬到笔画之上，最后轻度平滑。

    得到的是"贴合渐变、不受暗笔画污染、且几乎不引入自身方差"的背景。
    """
    p = gray.astype(np.float32)
    r = max(3, int(ksize) // 2) | 1
    # 多方向大核中值（旋转后再转回来，等价于沿该方向的中值）
    med_h = _median_u8(p, r)
    med_v = _median_u8(np.ascontiguousarray(p.T), r).T
    rot = np.ascontiguousarray(np.rot90(p, 1))
    med_d = np.rot90(_median_u8(rot, r), -1)
    med = np.median(np.stack([med_h, med_v, med_d]), axis=0)

    # 小核上包络：把背景抬到笔画之上，避免笔画把背景拉低（中值本身已足够稳）
    k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (max(3, int(ksize) // 6) | 1,) * 2)
    top = cv2.dilate(med, k)
    return _median_u8(top, max(3, int(ksize) // 8))


def _bg_excluding(gray: np.ndarray, exclude: np.ndarray, ksize: int) -> np.ndarray:
    """剔除水印像素后的背景重建。

    直接把水印像素挖掉，再用形态学闭运算 + 中值从邻域"长"回来。
    这一步决定了反混合能有多准：背景不许被水印自己拉低。
    """
    g = gray.copy()
    g[exclude] = np.nan
    # 用行/列方向的邻域插值填充 NaN（水印是细笔画，同行的邻域总能给出好估计）
    mask = exclude.astype(np.uint8)
    # inpaint 对 NaN 无效，改用距离变换最近邻填充作为初值
    if mask.any():
        inv = (1 - mask).astype(np.uint8)
        dist, labels = cv2.distanceTransformWithLabels(
            inv, cv2.DIST_L2, 3, labelType=cv2.DIST_LABEL_PIXEL)
        # labels 给出最近的非水印像素标签，用它把灰度搬过来
        flat_idx = np.zeros(labels.max() + 1, dtype=np.int32)
        ys, xs = np.nonzero(inv)
        flat_idx[labels[ys, xs]] = ys.astype(np.int32) * gray.shape[1] + xs.astype(np.int32)
        idx = flat_idx[labels]
        filled = gray.reshape(-1)[idx].reshape(gray.shape)
    else:
        filled = gray
    k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (ksize, ksize))
    top = cv2.dilate(filled.astype(np.float32), k)
    bg = cv2.medianBlur(top.astype(np.uint8), max(3, ksize // 3 | 1)).astype(np.float32)
    return bg


def estimate_watermark_gray(img: np.ndarray, mask: np.ndarray,
                            core: Optional[np.ndarray] = None,
                            peak_frac: float = 0.20) -> Optional[np.ndarray]:
    """估计水印自身的颜色（BGR）。低饱和灰是豆包水印的稳定特征。

    不对掩膜内所有像素取中值：掩膜里抗锯齿边缘远多于笔画主体，中值会跑到
    "几乎没被覆盖"的浅色上（实测深色水印把 128 估成 237），于是落差被压到个位数，
    反混合只剥掉一小部分，留下明显残字。真正的"水印色"只体现在压得最暗的那一小撮
    像素上：先用 core 缩小到笔画主体，再取其中最暗的 peak_frac 求中值。
    """
    sel = mask > 0
    if core is not None:
        sel = sel & (core > 0)
    if not sel.any():
        sel = mask > 0
    if not sel.any():
        return None
    px = img[sel].astype(np.float32)
    lum = px.mean(axis=1)
    thr = float(np.percentile(lum, max(1.0, min(60.0, peak_frac * 100.0))))
    darkest = lum <= thr
    if not darkest.any():
        darkest = np.ones_like(lum, bool)
    return np.median(px[darkest], axis=0)


def _candidate_roi(shape, preset: str, margin_ratio: float, custom=None):
    h, w = shape[:2]
    if custom is not None:
        x0, y0, x1, y1 = custom
        return max(0, int(x0)), max(0, int(y0)), min(w, int(x1)), min(h, int(y1))
    if preset in PRESET_ANCHORS:
        fx, fy = PRESET_ANCHORS[preset]
    else:
        fx, fy = 1.0, 1.0
    band_w = max(160, int(w * 0.30))
    band_h = max(48, int(h * 0.085))
    x1 = w if fx > 0.5 else band_w
    x0 = x1 - band_w
    y1 = h if fy > 0.5 else band_h
    y0 = y1 - band_h
    return max(0, x0), max(0, y0), min(w, x1), min(h, y1)


# ----------------------------------------------------------------------------
# 检测
# ----------------------------------------------------------------------------

def detect(img: np.ndarray,
           strength: int = 3,
           preset: str = "auto",
           custom_roi=None,
           margin_ratio: float = 0.028) -> DetectResult:
    """检测水印掩膜。

    判定链：噪声自适应阈值 -> 细长笔画连通域 -> 成行排布 -> 低对比度（水印本质）校验。
    只有同时满足才认为是水印，避免把照片内容（头发丝、衣褶）当成水印抹掉。
    """
    gray = _to_gray(img)
    h, w = gray.shape[:2]
    _k_sigma, grow, gate, _rad = STRENGTH_TABLE.get(strength, STRENGTH_TABLE[3])

    presets = ["corner_br", "corner_bl", "corner_tr", "corner_tl"] if preset == "auto" else [preset]
    best: Optional[DetectResult] = None

    for ps in presets:
        roi = _candidate_roi(gray.shape, ps, margin_ratio, custom_roi)
        x0, y0, x1, y1 = roi
        if x1 - x0 < 16 or y1 - y0 < 12:
            continue
        patch = gray[y0:y1, x0:x1]
        rh, rw = patch.shape

        ksize = int(max(15, min(patch.shape) * 0.55)) | 1
        bg = local_background(patch, ksize)
        resid = bg - patch                     # >0 表示比背景暗

        sigma = _noise_sigma(patch, resid)
        thr = max(sigma * DETECT_SIGMA, 1.2)

        raw = (resid > thr).astype(np.uint8)
        raw = cv2.morphologyEx(raw, cv2.MORPH_CLOSE,
                               cv2.getStructuringElement(cv2.MORPH_RECT, (3, 3)))
        raw = cv2.morphologyEx(raw, cv2.MORPH_OPEN,
                               cv2.getStructuringElement(cv2.MORPH_RECT, (2, 1)))

        n, lab, stats, cent = cv2.connectedComponentsWithStats(raw, 8)
        keep = np.zeros_like(raw)
        kept_stats = []
        paper_ref = float(np.percentile(bg, 92))          # 亮纸面参考亮度
        bright_floor = max(0.62 * paper_ref, 140.0)       # 内容保护门槛
        # 水印笔画在 ROI 内的相对尺寸上限
        h_lim = max(8.0, rh * 0.55)
        for i in range(1, n):
            x, y, bw, bh, area = stats[i]
            if area < 3 or bh > h_lim or bw > rw * 0.98:
                continue
            # 细长性：笔画应细（minAreaRect 短边小）
            comp = (lab[y:y + bh, x:x + bw] == i).astype(np.uint8)
            cnts, _ = cv2.findContours(comp, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
            if not cnts:
                continue
            (_, _), (rw_, rh_), _ = cv2.minAreaRect(np.vstack(cnts))
            thin = min(rw_, rh_) / max(max(rw_, rh_), 1e-6)
            if thin > 0.62 and max(rw_, rh_) > 4:
                continue
            # 内容保护：水印是**压在亮背景上**的浅灰字。
            # 深色内容（黑衣服的褶皱、头发丝）虽然也细长、残差也大，但它们的
            # 局部背景很暗。不设这条，算法就会去"剥衣服"而不碰水印。
            breg = bg[y:y + bh, x:x + bw][comp > 0]
            if breg.size and float(np.median(breg)) < bright_floor:
                continue
            # 笔画主体必须有真实对比度：平坦底图上的 1~2 灰阶纹理波动也能凑出细长连通域
            reg = resid[y:y + bh, x:x + bw][comp > 0]
            med_seg = float(np.median(reg)) if reg.size else 0.0
            if med_seg < max(1.6 * sigma, 1.5):
                continue
            # 低对比度校验：水印是浅灰，残差不会太夸张
            seg = resid[y:y + bh, x:x + bw][comp > 0]
            if seg.size and float(np.percentile(seg, 90)) > 110:
                continue
            keep[lab == i] = 1
            kept_stats.append((x, y, bw, bh, area, float(np.median(seg)) if seg.size else 0.0))

        if keep.sum() < 6:
            continue

        # ---- 文字行聚类：水印是"一行字"，只保留最像文字行的那个水平带 ----
        rows = keep.sum(axis=1)
        try:
            thr_row = max(2.0, rh * 0.002)
            band_rows = (rows > thr_row).astype(np.uint8)
            band_rows = cv2.morphologyEx(band_rows.reshape(-1, 1), cv2.MORPH_CLOSE,
                                         np.ones((7, 1), np.uint8)).reshape(-1)
            segs = []
            s = None
            for yy in range(rh):
                if band_rows[yy] and s is None:
                    s = yy
                elif not band_rows[yy] and s is not None:
                    segs.append((s, yy - 1)); s = None
            if s is not None:
                segs.append((s, rh - 1))
            if not segs:
                continue
            # 选"行内像素最多"的那一段作为水印行
            best_seg, best_score = None, -1.0
            for a, b in segs:
                if b - a + 1 > rh * 0.6:
                    continue
                band = keep[a:b + 1, :]
                score = float(band.sum()) / max(1.0, (b - a + 1))
                if score > best_score:
                    best_seg, best_score = (a, b), score
            if best_seg is None:
                continue
            a, b = best_seg
            row_keep = np.zeros_like(keep)
            row_keep[a:b + 1, :] = keep[a:b + 1, :]
            keep = row_keep
        except Exception:
            pass

        cols = keep.sum(axis=0)
        nzc = np.nonzero(cols)[0]
        col_span = int(nzc.max() - nzc.min() + 1) if len(nzc) else 0
        nz = np.nonzero(keep.sum(axis=1))[0]
        if len(nz) < 1:
            continue
        band_h = int(nz.max() - nz.min() + 1)
        aspect = col_span / max(1, band_h)
        row_conc = keep.sum() / max(1, band_h * rw)
        # 参与像素的对比度应集中在"浅灰"区间
        vals = resid[keep > 0]
        med_res = float(np.median(vals)) if vals.size else 0.0
        peak = float(resid.max())

        # ---- 分布形态门控：真水印是"整条笔画都稳定偏暗"，照片细节是"少数像素极暗" ----
        # 头发/衣褶等高对比边缘也能凑出细长连通域且局部残差很大，但笔画本体上大面积
        # 稳定偏暗的像素很少，压暗程度的 75 分位会明显掉下去；实测干净原图约 1.9、
        # 真水印 6~20，是可分的判据（干净图误伤"改动>3 灰阶"因此保持为 0）。
        band_px = resid[keep > 0]
        q75 = float(np.percentile(band_px, 75)) if band_px.size else 0.0
        if q75 < 1.15 * max(sigma * DETECT_SIGMA, 1.2):
            continue

        conf = 0.0
        conf += min(1.0, med_res / max(thr * 2.0, 1e-6)) * 0.35
        conf += min(1.0, row_conc * 2.2) * 0.20
        conf += min(1.0, aspect / 3.5) * 0.25
        conf += min(1.0, len(kept_stats) / 6.0) * 0.20
        conf = float(np.clip(conf, 0.0, 1.0))

        full = np.zeros((h, w), np.uint8)
        full[y0:y1, x0:x1] = keep * 255
        ys, xs = np.nonzero(full)
        bbox = (int(xs.min()), int(ys.min()), int(xs.max()), int(ys.max())) if len(xs) else None

        res = DetectResult(
            found=conf >= 0.35, mask=full, coverage=float(full.mean() / 255.0),
            bbox=bbox, peak=peak, threshold=float(thr),
            method=f"residual+shape({ps})", conf=conf,
        )
        if best is None or res.conf > best.conf:
            best = res

    if best is None or not best.found:
        empty = np.zeros((h, w), np.uint8)
        conf = best.conf if best else 0.0
        return DetectResult(False, empty, 0.0, None, best.peak if best else 0.0,
                            best.threshold if best else 0.0, best.method if best else "none", conf)

    if grow > 0:
        k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * grow + 1, 2 * grow + 1))
        best.mask = cv2.dilate(best.mask, k)
    return best


# ----------------------------------------------------------------------------
# 修复
# ----------------------------------------------------------------------------

def _nearest_fill(gray: np.ndarray, exclude: np.ndarray) -> np.ndarray:
    """把 exclude 区域的灰度用"最近的有效像素"填回（距离变换最近邻）。"""
    h, w = gray.shape
    ex = exclude.astype(np.uint8)
    valid = (1 - ex).astype(np.uint8)
    if valid.sum() == 0:
        return gray.copy()
    _, labels = cv2.distanceTransformWithLabels(valid, cv2.DIST_L2, 5,
                                                labelType=cv2.DIST_LABEL_PIXEL)
    ys, xs = np.nonzero(valid)
    lut = np.zeros(int(labels.max()) + 1, np.int32)
    lut[labels[ys, xs]] = ys.astype(np.int32) * w + xs.astype(np.int32)
    idx = lut[labels]
    out = gray.reshape(-1)[idx].reshape(h, w)
    return out.astype(np.float32)


def _masked_mean(gray: np.ndarray, valid: np.ndarray, ksize: int) -> np.ndarray:
    """"未覆盖像素"的局部均值背景（valid=True 的像素才参与平均）。

    用有效性加权的盒滤波实现：挖掉的区域由周围**干净**像素的平均值"长"回来。
    与最近邻填充相比，它的估计方差随窗口内有效像素数下降（1280 图上约
    1/sqrt(300)），因此在噪声/纹理底图上不会把 ±1 灰阶的背景误差放大成
    反混合里的 ±10 灰阶。
    """
    v = valid.astype(np.float32)
    k = (int(ksize) | 1, int(ksize) | 1)
    num = cv2.boxFilter(gray.astype(np.float32) * v, -1, k, normalize=False,
                        borderType=cv2.BORDER_REPLICATE)
    den = cv2.boxFilter(v, -1, k, normalize=False, borderType=cv2.BORDER_REPLICATE)
    return num / np.maximum(den, 1e-3)


def _bg_fill_from(gray: np.ndarray, exclude: np.ndarray, ksize: int) -> np.ndarray:
    """挖掉水印像素后重建背景（反混合精度的决定环节）。

    被挖掉的像素由周围**干净像素的局部均值**外推得到，而不是由某一个最近的像素
    决定。这一步很关键 -- 最近邻填充在笔画拐角处会取到"漏排除"的笔画核心
    （比真背景高十几灰阶），反混合会把这个偏差当成覆盖度放大 1/(1-a) 倍；
    改成局部均值后偏差被邻域平均掉。
    """
    g = gray.astype(np.float32)
    ex = cv2.dilate(exclude.astype(np.uint8), np.ones((3, 3), np.uint8)) > 0
    if not ex.any():
        return g.copy()
    bg = _masked_mean(g, ~ex, max(9, (ksize * 4) | 1))
    # 只对掩膜区域做轻度平滑，避免掩膜边界出现硬接缝
    smooth = cv2.medianBlur(np.clip(bg, 0, 255).astype(np.uint8),
                            max(3, ksize | 1)).astype(np.float32)
    return np.where(ex, 0.7 * bg + 0.3 * smooth, g)


def _guided_filter(guide: np.ndarray, src: np.ndarray, radius: int, eps: float = 1e-4) -> np.ndarray:
    """自实现引导滤波（cv2.ximgproc 在 headless 版不可用）。

    保边平滑：字形边缘处平滑弱、笔画内部平滑强，正好适合 alpha 场去噪。
    """
    g = guide.astype(np.float32) / 255.0
    p = src.astype(np.float32)
    r = int(max(2, radius))
    k = (2 * r + 1, 2 * r + 1)
    mean_g = cv2.boxFilter(g, -1, k, normalize=True, borderType=cv2.BORDER_REFLECT)
    mean_p = cv2.boxFilter(p, -1, k, normalize=True, borderType=cv2.BORDER_REFLECT)
    corr_g = cv2.boxFilter(g * g, -1, k, normalize=True, borderType=cv2.BORDER_REFLECT)
    corr_gp = cv2.boxFilter(g * p, -1, k, normalize=True, borderType=cv2.BORDER_REFLECT)
    var_g = corr_g - mean_g * mean_g
    cov_gp = corr_gp - mean_g * mean_p
    a = cov_gp / (var_g + eps)
    b = mean_p - a * mean_g
    mean_a = cv2.boxFilter(a, -1, k, normalize=True, borderType=cv2.BORDER_REFLECT)
    mean_b = cv2.boxFilter(b, -1, k, normalize=True, borderType=cv2.BORDER_REFLECT)
    return mean_a * g + mean_b


def _alpha_unmix(img: np.ndarray, mask: np.ndarray, wm_color: np.ndarray,
                 radius: int = 3, gate: float = 0.45, strength: int = 3):
    """半透明反混合（观测幅度反演 + 分段线性覆盖度）。

    模型: 观测 = (1-a)*原图 + a*水印色。

    为什么不用教科书式的 (obs - a·wm) / (1 - a)：该式是**病态**的，a 只要有
    1 灰阶估计误差就被 1/(1-a) 放大，a 接近 1 时直接把底图的纹理/噪声当成水印
    覆盖剥掉（旧版"幽灵字"的根因）。而且水印色 wm 只有在背景有明显变化时才可
    辨识，实测同一幅图不同笔画会把 wm 估成 170~250，落差被压到个位数后误差
    被放大得更厉害。

    这里改用一个对上述病态性免疫的等价形式：
      d  = 背景 - 观测                       （观测被压暗了多少）
      A  = 该连通域的满覆盖压暗幅度（域内最深像素的稳健上分位）
      rec = 观测 + clip(d / A, 0, 1) · A
    即"按该像素的相对覆盖度把压暗的部分加回去"：
      · 满覆盖像素 (d=A) 精确抬回背景；
      · 抗锯齿边缘 (d<A) 只抬 d，正好抹平覆盖量，不会剥成硬边；
      · d 被高估时 clip 到 1，最多抬到背景，绝不会过度剥离；
      · 幅度 A 直接来自观测，不需要可靠的水印色，浅水印也不会被放大。
    只有**满覆盖**像素（观测里已无原图信息）才交给 inpaint。

    返回 (反混合图, 已解出像素数, 需 inpaint 掩膜)。
    """
    gray = _to_gray(img).astype(np.float32)
    h, w = gray.shape
    mt = mask > 0
    ksize = max(9, int(min(h, w) * 0.012)) | 1

    # 1) 排除域 = 检测掩膜外扩 5px（最可靠的"这里是水印"证据），再并上残差候选。
    #    宁可多挖也不能漏挖：漏掉一个笔画核心，它就会进入背景重建并把背景拉低到
    #    "观测"上，覆盖度随即被判成 0，该笔画会被整条放弃。
    bg0 = local_background(gray, max(15, int(min(h, w) * 0.03)) | 1)
    thr0 = max(_noise_sigma(gray, bg0 - gray) * DETECT_SIGMA, 1.2)
    rough = cv2.dilate(mt.astype(np.uint8), np.ones((5, 5), np.uint8)) > 0
    rough |= ((bg0 - gray) > 0.5 * thr0) & mt

    wm = np.clip(wm_color.astype(np.float32), 0, 255)
    # 2) 逐通道用干净像素重建背景
    ch_bg = np.empty((h, w, 3), np.float32)
    for c in range(3):
        ch_bg[:, :, c] = _bg_fill_from(img[:, :, c].astype(np.float32), rough, ksize)
    bg_gray = cv2.cvtColor(np.clip(ch_bg, 0, 255).astype(np.uint8),
                           cv2.COLOR_BGR2GRAY).astype(np.float32)

    # 3) 压暗程度（观测相对背景暗了多少）
    dk = np.clip(bg_gray - gray, 0.0, None) * mt

    # 4) 按连通域求"满覆盖压暗幅度"：域内压得最深的那一半取中值，既避开单像素
    #    噪声尖峰，又贴合满覆盖水平。归一化必须**按连通域**：整幅图的最深像素来自
    #    最粗的笔画，用它归一化会让细笔画只被抬起一小部分，留下残字。
    n_comp, lab = cv2.connectedComponents(mt.astype(np.uint8), 8)
    amp = np.zeros_like(dk)
    for i in range(1, n_comp):
        sel_c = lab == i
        vals = dk[sel_c]
        if vals.size == 0:
            continue
        vmax = float(vals.max())
        hi = vals[vals >= 0.5 * vmax] if vmax > 0 else vals
        med_hi = float(np.median(hi)) if hi.size else 0.0
        # 均匀性门控：真水印是"同一条笔画整体一起变暗"，压得最深的那一半像素
        # 强度高度一致（实测 中位/90分位 ≈ 0.85~1.0）；照片细节（头发、衣褶）是
        # "少数像素极暗"，比值只有 0.37 左右。这一判据把干净原图的误伤从
        # "改动>3 灰阶若干像素"压到 0，同时不牺牲任何合成用例。
        p90 = float(np.percentile(vals, 90))
        uniform = (med_hi / p90) if p90 > 1e-6 else 0.0
        amp[sel_c] = med_hi if uniform >= 0.6 else 0.0

    # 5) 按相对覆盖度把压暗的部分加回去
    gain = np.clip(dk / np.maximum(amp, 1e-3), 0.0, 1.0) * amp
    out = img.astype(np.float32).copy()
    obs = img.astype(np.float32)
    cap = np.minimum(ch_bg + 2.0, 255.0)
    rec = np.clip(obs + gain[..., None], 0, cap)

    # 压暗太弱（几乎全是原图信息）或该笔画整体幅度不足（其实只是纹理起伏）时不动，
    # 避免无谓地改到干净像素。幅度门控必须明显低于常见水印的压暗量：噪声底图的
    # 阈值 thr0 本身就有 4.45，若按 1.6*thr0 设门（约 7.1）会把 α=0.10 的真水印
    # （压暗仅 7 灰阶）整条挡掉，反混合等于完全不工作。
    amp_floor = max(1.25 * max(thr0, 1.2), 1.5)
    sel = mt & (amp > amp_floor) & (dk > gate * max(thr0, 1.2))
    out[sel] = rec[sel]

    # 满覆盖像素（观测里已无原图信息，抬起来等于凭空造数）交给 inpaint
    need = mt & (dk >= 0.92 * np.maximum(amp, 1e-3)) & (amp > amp_floor)
    solved = int((sel & ~need).sum())
    return out, max(solved, 0), need


def seal_clean(img: np.ndarray, rect: tuple, strength: int = 3) -> tuple:
    """强制清理指定矩形区域里的极淡水印（"图章压平"）。

    适用场景：水印淡到只有 1~3 个灰阶、常规检测达不到信噪比下限，
    但用户肉眼能看到、并愿意手动框出位置。

    原理与安全边界：
      · 取"局部纸面基准" = 大核灰度膨胀（局部上包络）再重度平滑；
      · 只在**已经接近纸白**的像素上，把低于基准的部分抬回基准；
      · 亮度低于阈值的像素（深色内容：衣服、头发）在数学上就**抬不动**，
        因此不会像常规反混合那样把内容当水印剥掉。
    换句话说：它只抹平"纸上那层薄薄的灰"，动不了画面内容。

    返回 (结果图, 改动像素数, 平均改动灰阶)。
    """
    x0, y0, x1, y1 = [int(round(v)) for v in rect]
    h, w = img.shape[:2]
    x0 = max(0, min(w - 1, x0)); x1 = max(x0 + 1, min(w, x1))
    y0 = max(0, min(h - 1, y0)); y1 = max(y0 + 1, min(h, y1))

    # 外扩一圈供背景估计使用，避免边界效应
    pad = max(10, int(min(x1 - x0, y1 - y0) * 0.35))
    px0, py0 = max(0, x0 - pad), max(0, y0 - pad)
    px1, py1 = min(w, x1 + pad), min(h, y1 + pad)
    region = img[py0:py1, px0:px1].astype(np.float32)
    gray = _to_gray(region)

    k = int(max(9, min(region.shape[:2]) * 0.45)) | 1
    kern = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (k, k))
    bg = cv2.dilate(gray, kern)
    bg = cv2.GaussianBlur(bg, (0, 0), max(2.0, k / 4.0))

    floor = _paper_floor(gray)
    deficit = np.clip(bg - gray, 0.0, None)
    # 内容保护：只抬"本身就接近纸白"的像素；深色像素权重为 0
    t = float(np.clip((strength - 1) / 4.0, 0.0, 1.0))
    lo = floor - 24.0 + 14.0 * t          # 越强，允许抬的起点越低
    hi = floor - 6.0 + 4.0 * t
    wgt = np.clip((gray - lo) / max(hi - lo, 1e-6), 0.0, 1.0)

    out = region.copy()
    gain = (deficit * wgt)[..., None]
    out = np.clip(out + gain, 0, 255)

    # 只把结果贴回用户框选的矩形（外扩区仅用于估背景）
    sub = out[y0 - py0:y1 - py0, x0 - px0:x1 - px0]
    res = img.astype(np.float32).copy()
    res[y0:y1, x0:x1] = sub

    changed = np.abs(res.astype(np.float32) - img.astype(np.float32)).mean(axis=2)
    n = int((changed > 0.25).sum())
    mean_change = float(changed[changed > 0].mean()) if n else 0.0
    return np.clip(res, 0, 255).astype(np.uint8), n, round(mean_change, 3)


def _paper_floor(gray: np.ndarray) -> float:
    """稳健估计"纸面白"的亮度水平（避开深色内容）。"""
    hi = gray[gray > np.percentile(gray, 55)]
    return float(np.percentile(hi, 60)) if hi.size else float(np.percentile(gray, 90))


def _guided_render_repair(orig: np.ndarray, repaired: np.ndarray, mask: np.ndarray,
                          radius: int, watermark: np.ndarray | None = None) -> np.ndarray:
    """渲染修复：修复区与原图按羽化权重柔和融合。

    反混合解出的像素本身就是对原图的精确估计（再加"纹理注入"等于往干净图上加噪），
    只有 inpaint 填出来的像素需要与周围自然衔接。因此这里做的是带羽化的融合，
    让修复痕迹不可见、不产生硬边或糊块。
    """
    m2 = (mask > 0).astype(np.float32)
    m = m2[..., None]
    # 掩膜内一律采用修复结果；掩膜外扩一圈做柔和过渡
    grow = int(max(1, radius))
    ring = cv2.dilate(m2, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * grow + 3,) * 2))
    ring = np.clip(ring - m2, 0, 1)
    outer = cv2.GaussianBlur(ring, (0, 0), max(1.0, radius * 0.8))
    alpha = np.clip(m + outer[..., None] * 0.5, 0, 1)

    o = orig.astype(np.float32)
    r = repaired.astype(np.float32)
    out = r * alpha + o * (1 - alpha)
    return np.clip(out, 0, 255).astype(np.uint8)


def _restore_channels(src: np.ndarray, out: np.ndarray) -> np.ndarray:
    """把 BGR 处理结果还原成与输入一致的通道布局（灰度 / BGRA）。"""
    if src.ndim == 2:
        return cv2.cvtColor(out, cv2.COLOR_BGR2GRAY)
    if src.shape[2] == 4:
        bgra = cv2.cvtColor(out, cv2.COLOR_BGR2BGRA)
        bgra[:, :, 3] = src[:, :, 3]
        return bgra
    return out


def remove(img: np.ndarray,
           strength: int = 3,
           preset: str = "auto",
           custom_roi=None,
           mask_override: Optional[np.ndarray] = None,
           render_repair: bool = True,
           margin_ratio: float = 0.028,
           force_clean: bool = False):
    """执行去水印。返回 (结果图, DetectResult, RemoveReport)。

    force_clean=True 时对 custom_roi 指定的区域执行"图章压平"（seal_clean），
    专治淡到常规检测抓不到的极淡水印；该模式只抬接近纸白的像素，不碰深色内容。
    """
    k_sigma, grow, gate, radius = STRENGTH_TABLE.get(strength, STRENGTH_TABLE[3])

    # 输入归一化：灰度 / RGBA 统一走 BGR 链路，返回前再还原通道（与界面端一致）
    src_img = img
    if img.ndim == 2:
        img = cv2.cvtColor(img, cv2.COLOR_GRAY2BGR)
    elif img.shape[2] == 4:
        img = cv2.cvtColor(img, cv2.COLOR_BGRA2BGR)

    # --- 强制清理模式：用户已手动指定区域 ---
    if force_clean and custom_roi is not None:
        res, n_px, mean_change = seal_clean(img, custom_roi, strength=strength)
        x0, y0, x1, y1 = [int(round(v)) for v in custom_roi]
        mask = np.zeros(img.shape[:2], np.uint8)
        mask[max(0, y0):max(0, y1), max(0, x0):max(0, x1)] = 255
        det = DetectResult(True, mask, float((mask > 0).mean()),
                           (x0, y0, x1, y1), 0.0, 0.0, "manual+seal", 1.0)
        rep = RemoveReport(
            mask_pixels=n_px, unmixed_pixels=n_px, inpainted_pixels=0,
            coverage=det.coverage, peak_before=mean_change, peak_after=0.0,
            method="manual+seal", conf=1.0,
            change_mean=round(mean_change, 4), significant=n_px > 0,
        )
        return _restore_channels(src_img, res), det, rep

    if mask_override is not None:
        det = DetectResult(True, (mask_override > 0).astype(np.uint8) * 255,
                           float((mask_override > 0).mean()), None, 0.0, 0.0, "manual", 1.0)
    else:
        det = detect(img, strength=strength, preset=preset,
                     custom_roi=custom_roi, margin_ratio=margin_ratio)

    if not det.found or det.mask.sum() == 0:
        rep = RemoveReport(0, 0, 0, 0.0, 0.0, 0.0, det.method, det.conf)
        return _restore_channels(src_img, img.copy()), det, rep

    gray = _to_gray(img)
    ksize = max(15, int(min(gray.shape) * 0.02)) | 1
    # 用"挖掉水印后重建的背景"衡量残留：它不放大残差，peak_after 因此反映真实残留，
    # 而不会被大核膨胀自身抬高的背景虚增成"水印色"本身。
    bg = _bg_fill_from(gray, (det.mask > 0), ksize)
    peak_before = float((bg - gray)[det.mask > 0].max()) if det.mask.sum() else 0.0

    # --- Step1 反混合 ---
    # 笔画主体（粗残差）作为水印色估计的范围，避免被抗锯齿边缘拉亮
    bg_ref = local_background(gray, max(15, int(min(gray.shape) * 0.03)) | 1)
    thr_ref = max(_noise_sigma(gray, bg_ref - gray) * DETECT_SIGMA, 1.2)
    core_ref = (((bg_ref - gray) > 0.5 * thr_ref) & (det.mask > 0)).astype(np.uint8) * 255
    wm_color = estimate_watermark_gray(img, det.mask, core=core_ref)
    if wm_color is None:
        wm_color = np.array([240.0, 240.0, 240.0], np.float32)
    unmixed, n_unmixed, need_inpaint = _alpha_unmix(img, det.mask, wm_color, radius, gate, strength)

    # --- Step2 背景引导修复 ---
    # 只修"反演不可靠"的像素 + 掩膜边缘（抗锯齿残留），其余保留反混合结果，
    # 这样既去干净，又不会把整条笔画糊掉。
    edge = cv2.morphologyEx((det.mask > 0).astype(np.uint8) * 255, cv2.MORPH_GRADIENT,
                            cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3))) > 0
    inpaint_mask = ((need_inpaint | edge).astype(np.uint8) * 255)
    n_inpaint = int((inpaint_mask > 0).sum())

    work = unmixed.astype(np.uint8)
    if n_inpaint > 0:
        rad = max(2, radius)
        telea = cv2.inpaint(work, inpaint_mask, rad, cv2.INPAINT_TELEA)
        ns = cv2.inpaint(work, inpaint_mask, rad + 1, cv2.INPAINT_NS)
        work = (telea.astype(np.float32) * 0.5 + ns.astype(np.float32) * 0.5).astype(np.uint8)

    # --- Step3 渲染修复 ---
    if render_repair:
        ys, xs = np.nonzero(det.mask)
        pad = int(max(24, radius * 8))
        y0 = max(0, ys.min() - pad); y1 = min(img.shape[0], ys.max() + pad + 1)
        x0 = max(0, xs.min() - pad); x1 = min(img.shape[1], xs.max() + pad + 1)
        sub_o = img[y0:y1, x0:x1]
        sub_w = work[y0:y1, x0:x1]
        sub_m = det.mask[y0:y1, x0:x1]
        work[y0:y1, x0:x1] = _guided_render_repair(sub_o, sub_w, sub_m, radius)

    # 量化后校验
    gray2 = _to_gray(work)
    m = det.mask > 0
    peak_after = float((bg - gray2)[m].max()) if det.mask.sum() else 0.0

    # --- Step4 可见性判定 ---
    # 把"实际改动了多少"量化出来：水印再淡，能去掉的东西也会让掩膜内平均改动
    # 达到 3 个灰阶以上；而干净照片被误检出的那点噪声，平均改动只有 0.4~0.5。
    # 用这个量决定"到底有没有可去掉的东西"，比单纯卡置信度稳得多（两者差 6 倍以上）。
    change_mean = float(np.abs(work.astype(np.float32) - img.astype(np.float32)).mean(axis=2)[m].mean()) if m.sum() else 0.0
    significant = bool(m.sum()) and change_mean >= SIGNIFICANT_CHANGE

    rep = RemoveReport(
        mask_pixels=int(m.sum()),
        unmixed_pixels=int(n_unmixed),
        inpainted_pixels=int(n_inpaint),
        coverage=det.coverage,
        peak_before=peak_before,
        peak_after=peak_after,
        method=det.method,
        conf=det.conf,
        change_mean=round(change_mean, 4),
        significant=significant,
    )
    if not significant:
        # 没有可去掉的东西：原样返回，避免在干净照片上留下无谓的改动
        return _restore_channels(src_img, img.astype(np.uint8).copy()), det, rep
    return _restore_channels(src_img, work), det, rep
