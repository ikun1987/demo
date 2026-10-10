/**
 * 轻量快修引擎（无需联网、无需下模型、瞬间出结果）。
 *
 * 为什么需要它：
 *   LaMa 模型有 59MB，移动端在国内网络下载很容易失败，一旦失败用户就
 *   什么都拿不到 —— 体验是"这软件不能用"。所以先给一条**必定可用**的通道：
 *     · 对"水印压在平坦背景"的图（豆包大多数图都是），效果已经足够好；
 *     · 复杂背景（纹理、硬边）会被轻微模糊，这时再提示用户升级 AI 深度修复。
 *
 * 算法：Fast Marching 风格的**由外向内传播 + 方向自适应加权**
 *   · 结构张量（Sobel 梯度）估计每个边界方向的"局部走向"；
 *   · 从掩膜边界开始一圈圈往里填，每个待填像素取已知邻居的加权平均，
 *     权重偏向与局部走向一致的方向 —— 这样直线/渐变能自然延续；
 *   · 再做一次保边平滑，避免出现同心圆条纹。
 * 纯 JS + 类型化数组，1280² 图上约 0.3~0.6 秒。
 */

/** Sobel 梯度（灰度），用于估计局部走向 */
function gradients(gray, W, H) {
  const gx = new Float32Array(W * H);
  const gy = new Float32Array(W * H);
  const at = (x, y) => gray[Math.min(H - 1, Math.max(0, y)) * W + Math.min(W - 1, Math.max(0, x))];
  for (let y = 0; y < H; y++) {
    for (let x = 0; x < W; x++) {
      const gxv = (at(x + 1, y - 1) + 2 * at(x + 1, y) + at(x + 1, y + 1))
                 - (at(x - 1, y - 1) + 2 * at(x - 1, y) + at(x - 1, y + 1));
      const gyv = (at(x - 1, y + 1) + 2 * at(x, y + 1) + at(x + 1, y + 1))
                 - (at(x - 1, y - 1) + 2 * at(x, y - 1) + at(x + 1, y - 1));
      gx[y * W + x] = gxv * 0.25;
      gy[y * W + x] = gyv * 0.25;
    }
  }
  return { gx, gy };
}

/**
 * 快修：把掩膜内的像素用边界传播填掉。
 * @param {{width:number,height:number}} dims
 * @param {Float32Array} rgb 原图 RGB（0..255）
 * @param {Uint8Array} mask 1=要修
 * @returns {{rgb:Float32Array, ms:number}}
 */
export function fastInpaint(dims, rgb, mask) {
  const t0 = (typeof performance !== 'undefined' ? performance.now() : Date.now());
  const W = dims.width, H = dims.height;
  const N = W * H;

  // 灰度（用于结构张量）
  const gray = new Float32Array(N);
  for (let i = 0; i < N; i++) {
    gray[i] = rgb[i * 3] * 0.299 + rgb[i * 3 + 1] * 0.587 + rgb[i * 3 + 2] * 0.114;
  }
  const { gx, gy } = gradients(gray, W, H);

  const out = Float32Array.from(rgb);
  const known = new Uint8Array(N);          // 1 = 已有确定值
  for (let i = 0; i < N; i++) known[i] = mask[i] ? 0 : 1;

  // 逐层从边界向内推进
  let frontier = [];
  for (let y = 0; y < H; y++) {
    for (let x = 0; x < W; x++) {
      const i = y * W + x;
      if (known[i]) continue;
      // 是否紧邻已知像素
      if ((x > 0 && known[i - 1]) || (x < W - 1 && known[i + 1])
        || (y > 0 && known[i - W]) || (y < H - 1 && known[i + W])) {
        frontier.push(i);
      }
    }
  }

  const DIRS = [[-1, 0], [1, 0], [0, -1], [0, 1], [-1, -1], [1, -1], [-1, 1], [1, 1]];
  let guard = 0;
  while (frontier.length && guard++ < 100000) {
    const next = [];
    const touched = new Uint8Array(N);
    for (const i of frontier) {
      if (known[i]) continue;
      const x = i % W, y = (i - x) / W;
      // 局部走向：等照度线方向 = 梯度旋转 90°
      const a = gx[i], b = gy[i];
      const mag = Math.hypot(a, b) || 1e-6;
      // 单位等照度线方向（沿边缘走向）
      const tx = -b / mag, ty = a / mag;
      const coh = mag / 64;                       // 连贯度：越大越该沿走向取
      const wIso = Math.min(1, coh);              // 走向权重
      const wIsoX = tx * tx * wIso, wIsoY = ty * ty * wIso;

      let sr = 0, sg = 0, sb = 0, sw = 0;
      for (const [dx, dy] of DIRS) {
        const xx = x + dx, yy = y + dy;
        if (xx < 0 || xx >= W || yy < 0 || yy >= H) continue;
        const j = yy * W + xx;
        if (!known[j]) continue;
        // 方向权重：与局部走向一致 → 权重更大；再乘距离衰减
        const ax = Math.abs(dx), ay = Math.abs(dy);
        const iso = (dx * dx * wIsoX + dy * dy * wIsoY);
        const dist = Math.SQRT1_2 * (ax + ay);      // 对角略远
        let w = (0.35 + iso) / (0.6 + dist);
        const jp = j * 3;
        sr += out[jp] * w; sg += out[jp + 1] * w; sb += out[jp + 2] * w;
        sw += w;
      }
      if (sw <= 0) { next.push(i); continue; }
      const p = i * 3;
      out[p] = sr / sw; out[p + 1] = sg / sw; out[p + 2] = sb / sw;
      known[i] = 1;
      touched[i] = 1;
      gray[i] = out[p] * 0.299 + out[p + 1] * 0.587 + out[p + 2] * 0.114;
    }
    // 下一层 = 本层填过的像素周围的未知像素
    for (const i of frontier) {
      if (!touched[i]) continue;
      const x = i % W, y = (i - x) / W;
      for (const [dx, dy] of [[-1, 0], [1, 0], [0, -1], [0, 1]]) {
        const xx = x + dx, yy = y + dy;
        if (xx < 0 || xx >= W || yy < 0 || yy >= H) continue;
        const j = yy * W + xx;
        if (!known[j]) next.push(j);
      }
    }
    frontier = [...new Set(next)];
  }

  // 保边平滑：只在掩膜内、沿走向做一次轻度平均，压掉同心条纹
  const smooth = Float32Array.from(out);
  for (let y = 1; y < H - 1; y++) {
    for (let x = 1; x < W - 1; x++) {
      const i = y * W + x;
      if (!mask[i]) continue;
      const a = gx[i], b = gy[i];
      const mag = Math.hypot(a, b) || 1e-6;
      const tx = -b / mag, ty = a / mag;
      const rx = Math.round(tx), ry = Math.round(ty);
      const samples = [[rx, ry], [-rx, -ry], [0, 0]];
      let sr = 0, sg = 0, sb = 0;
      for (const [dx, dy] of samples) {
        const j = (y + dy) * W + (x + dx);
        sr += out[j * 3]; sg += out[j * 3 + 1]; sb += out[j * 3 + 2];
      }
      const p = i * 3;
      smooth[p] = sr / samples.length;
      smooth[p + 1] = sg / samples.length;
      smooth[p + 2] = sb / samples.length;
    }
  }
  // 平滑只作用在掩膜内，且与原值各半，避免把梯度抹平
  for (let i = 0; i < N; i++) {
    if (!mask[i]) continue;
    const p = i * 3;
    out[p] = out[p] * 0.5 + smooth[p] * 0.5;
    out[p + 1] = out[p + 1] * 0.5 + smooth[p + 1] * 0.5;
    out[p + 2] = out[p + 2] * 0.5 + smooth[p + 2] * 0.5;
  }

  const t1 = (typeof performance !== 'undefined' ? performance.now() : Date.now());
  return { rgb: out, ms: t1 - t0 };
}
