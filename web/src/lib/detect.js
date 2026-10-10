/**
 * 豆包水印定位与掩膜生成（从 Python 版移植到浏览器端）。
 *
 * 算法要点（都是实测踩出来的）：
 *  1. 定位：用真实中文字体把「豆包AI生成」渲染成字模，在多尺度上做
 *     「覆盖率打分」——字模笔画处的偏离能量 ÷ 窗口内总能量。
 *     位置先验：贴右下角，边距约为短边的 1.9%（1280 图上实测 24px）。
 *  2. 掩膜：**整块矩形封住**实测字形范围，而不是沿笔画描边。
 *     因为只要掩膜外还留着一点水印笔画，修补网络就会把它当上下文，
 *     在掩膜内「画出」水印影子（越补越糟）。多盖一点背景远好于漏盖。
 */

import {
  toGray, backgroundApprox, madSigma, dilate, emptyMask,
} from './imageops.js';

export const WM_TEXT = '豆包AI生成';
export const FONT_STACK = '"Microsoft YaHei","PingFang SC","Heiti SC","Hiragino Sans GB",sans-serif';

/**
 * 画布工厂。浏览器里用 document.createElement；
 * Node 测试环境可通过 createCanvasFactory 注入 node-canvas，
 * 这样检测算法能在 Node 里直接跑，便于和 Python 版对齐。
 */
let canvasFactory = null;
export function createCanvasFactory(fn) { canvasFactory = fn; }

/** 覆盖字模字体（Node 测试环境需要显式指定已注册的字体名） */
let fontOverride = null;
export function setFontFamily(f) { fontOverride = f; cache.clear(); }

function fontSpec(px) {
  return `700 ${px}px ${fontOverride || FONT_STACK}`;
}

function newCanvas(w, h) {
  if (canvasFactory) return canvasFactory(w, h);
  const cv = document.createElement('canvas');
  cv.width = w; cv.height = h;
  return cv;
}

const cache = new Map();

/**
 * 渲染字模：返回 { mask: Float32Array(0..1), width, height }
 * 用 canvas 画「豆包AI生成」，裁剪到字形包围盒。
 */
export function renderTemplate(px) {
  const key = `t${px}`;
  if (cache.has(key)) return cache.get(key);
  const pad = Math.ceil(px * 0.6);
  const w = Math.ceil(px * (WM_TEXT.length + 1.2));
  const h = Math.ceil(px * 3);
  const cv = newCanvas(w, h);
  const ctx = cv.getContext('2d', { willReadFrequently: true });
  ctx.fillStyle = '#000'; ctx.fillRect(0, 0, w, h);
  ctx.fillStyle = '#fff';
  ctx.font = fontSpec(px);
  ctx.textBaseline = 'top';
  ctx.strokeStyle = '#fff';
  ctx.lineWidth = Math.max(1, px * 0.04);
  ctx.strokeText(WM_TEXT, pad, pad);
  ctx.fillText(WM_TEXT, pad, pad);

  const img = ctx.getImageData(0, 0, w, h);
  // 找字形包围盒
  let x0 = w, y0 = h, x1 = -1, y1 = -1;
  for (let y = 0; y < h; y++) {
    for (let x = 0; x < w; x++) {
      if (img.data[(y * w + x) * 4] > 24) {
        if (x < x0) x0 = x;
        if (x > x1) x1 = x;
        if (y < y0) y0 = y;
        if (y > y1) y1 = y;
      }
    }
  }
  const t = { width: 0, height: 0, mask: new Float32Array(0) };
  if (x1 < 0) { cache.set(key, t); return t; }
  const tw = x1 - x0 + 1, th = y1 - y0 + 1;
  const mask = new Float32Array(tw * th);
  for (let y = 0; y < th; y++) {
    for (let x = 0; x < tw; x++) {
      mask[y * tw + x] = img.data[((y0 + y) * w + (x0 + x)) * 4] / 255;
    }
  }
  const res = { width: tw, height: th, mask };
  cache.set(key, res);
  return res;
}

/**
 * 定位水印。
 *
 * 打分公式与 Python 生产版**逐字对齐**（这套公式在真实豆包图上实测有效）：
 *
 *     score = 覆盖率 × 0.75 + min(笔画处平均偏离 / 30, 1) × 0.25
 *     覆盖率 = Σ偏离(字模笔画处) / Σ偏离(字模窗口全部)
 *
 * 为什么必须以覆盖率为主：
 *   · 覆盖率天然惩罚小字模（小字模只覆盖窗口一小部分能量）；
 *   · 也惩罚错位（字模压不到笔画时覆盖率低）；
 *   · 纹理区因为偏离分散在整窗，任何单一字模都覆盖不全 → 低分。
 * （曾经试过"峰值能量×覆盖率修正"和"能量最大矩形"，都会被猫毛/条纹
 *   这类高对比纹理骗到，或让大框靠面积取胜，**都不能用**。）
 *
 * 性能：偏离图全图只算一次；搜索只在右下角 ROI 内做。
 */
export function locateWatermark(img, opts = {}) {
  const {
    heightRatio = 0.030, marginRatio = 0.019,
    dyRange = [-34, 34], dxRange = [-34, 34], pxOffsets = [-6, -4, -2, 0, 2, 4, 6],
  } = opts;
  const { width: W, height: H } = img;
  const s = Math.min(W, H);
  const base = Math.max(9, Math.round(s * heightRatio));
  const gray = toGray(img);

  // 1) 局部背景 + 偏离图（全图只算一次）
  const k = Math.max(21, Math.round(base * 1.9)) | 1;
  const bg = backgroundApprox(gray, W, H, k);
  const dev = new Float32Array(W * H);
  for (let i = 0; i < dev.length; i++) dev[i] = Math.abs(gray[i] - bg[i]);

  const margin = Math.max(5, Math.round(s * marginRatio));
  const pxList = pxOffsets.map((d) => base + d).filter((v) => v >= 8);

  let best = null;
  const evaluate = (px, xx, yy) => {
    const t = renderTemplate(px);
    const tw = t.width, th = t.height;
    if (!tw || tw >= W || th >= H) return;
    if (xx < 0 || yy < 0 || xx + tw > W || yy + th > H) return;
    let stroke = 0, total = 0, nStroke = 0;
    for (let y = 0; y < th; y++) {
      const row = (yy + y) * W + xx;
      const trow = y * tw;
      for (let x = 0; x < tw; x++) {
        const v = dev[row + x];
        total += v;
        if (t.mask[trow + x] > 0.45) { stroke += v; nStroke++; }
      }
    }
    if (nStroke < 20 || total <= 1e-6) return;
    const cov = stroke / total;
    const strong = stroke / nStroke;
    const score = cov * 0.75 + Math.min(strong / 30, 1) * 0.25;
    if (!best || score > best.score) {
      best = { score, px, box: { x0: xx, y0: yy, x1: xx + tw - 1, y1: yy + th - 1 } };
    }
  };

  for (const px of pxList) {
    const t = renderTemplate(px);
    if (!t.width || t.width >= W || t.height >= H) continue;
    const bx0 = W - margin - t.width;
    const by0 = H - margin - t.height;
    for (let dy = dyRange[0]; dy <= dyRange[1]; dy += 2) {
      for (let dx = dxRange[0]; dx <= dxRange[1]; dx += 2) {
        evaluate(px, bx0 + dx, by0 + dy);
      }
    }
  }
  return best;
}

/**
 * 生成修补掩膜（整块矩形，覆盖实测字形范围 + 余量）。
 *
 * 两个必须守住的点（都是实测打出来的）：
 *  1. 掩膜要**整块盖住**字形外接范围，不能沿笔画描边 —— 只要掩膜外还留着
 *     一条水印笔画，修补网络就会拿它当上下文，在掩膜内"画"出水印影子。
 *  2. 豆包水印贴右下角。若掩膜离边界很近，就**一直补到图像边界** ——
 *     否则角上那条缝会被当成上下文采样，补出来一圈脏边。
 *     （注意判断条件要按"离边界的距离"算；曾经的写法在 1280 图上会
 *       把整个右下四分之一（580 万像素）全涂掉，直接毁掉画面。）
 */
export function buildMask(img, opts = {}) {
  const { strength = 4, heightRatio = 0.030 } = opts;
  const { width: W, height: H } = img;
  const loc = locateWatermark(img, { heightRatio });
  if (!loc || loc.score < 0.10) return null;

  const { x0, y0, x1, y1 } = loc.box;
  const th = y1 - y0 + 1;
  // 余量按字高缩放，且**左右/上下不对称**。
  //
  // 为什么不对称：实测豆包水印比渲染出来的字模**右宽下厚**（字模偏窄），
  // 只按"字高×1.0"往两边均摊，右边和下边会各漏掉一段笔画；
  // 漏掉的那部分会被修补网络当上下文，于是原地"重画"出一层浅色残字
  // （实测 5 号图就是这个症状）。往右/下多放一点，宁可多盖一点背景。
  const mxL = Math.max(6, Math.round(th * 1.00));
  const mxR = Math.max(8, Math.round(th * 1.45));
  const myT = Math.max(4, Math.round(th * 0.45));
  const myB = Math.max(6, Math.round(th * 0.70));

  let rx0 = Math.max(0, x0 - mxL);
  let ry0 = Math.max(0, y0 - myT);
  let rx1 = Math.min(W - 1, x1 + mxR);
  let ry1 = Math.min(H - 1, y1 + myB);

  // 贴边补齐：掩膜离边界很近时，把它一直补到图像边界。
  // 否则角上那条缝会被修补网络当作上下文采样，补出来一圈脏边。
  const reachRight = rx1 >= W - 1 - mxR;
  const reachBottom = ry1 >= H - 1 - myB;
  if (reachRight) rx1 = W - 1;
  if (reachBottom) ry1 = H - 1;

  let mask = emptyMask(W, H);
  for (let y = ry0; y <= ry1; y++) {
    for (let x = rx0; x <= rx1; x++) mask[y * W + x] = 1;
  }
  // 按强度适度膨胀（吸收真实字形与字模的细微错位）
  const grow = { 1: 5, 2: 6, 3: 8, 4: 10, 5: 14 }[strength] ?? 10;
  mask = dilate(mask, W, H, grow);

  let count = 0;
  for (let i = 0; i < mask.length; i++) if (mask[i]) count++;
  return {
    mask, px: loc.px, score: loc.score,
    box: { x0: rx0, y0: ry0, x1: rx1, y1: ry1 },
    info: {
      maskPx: count, coverage: count / (W * H),
      templateBox: loc.box, reachRight, reachBottom, grow,
    },
  };
}

/** 在图上画掩膜可视化（调试用） */
export function maskToImageData(mask, W, H) {
  const out = new ImageData(W, H);
  for (let i = 0, p = 0; i < mask.length; i++, p += 4) {
    const on = mask[i] ? 1 : 0;
    out.data[p] = on ? 255 : 0;
    out.data[p + 1] = on ? 60 : 0;
    out.data[p + 2] = on ? 60 : 0;
    out.data[p + 3] = on ? 140 : 0;
  }
  return out;
}
