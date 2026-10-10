/**
 * 在 Node 里用**网页版完全相同的算法**跑一遍，排除浏览器因素。
 * 目标：确认幽灵残影是算法问题还是浏览器环境问题。
 *
 * 用法：node node-infer.mjs [图片名]
 */
import fs from 'node:fs';
import path from 'node:path';
import { createCanvas, loadImage, ImageData as NodeImageData, registerFont } from 'canvas';
import * as ort from 'onnxruntime-node';
import { createCanvasFactory, buildMask, setFontFamily } from '../web/src/lib/detect.js';

registerFont('C:\\Windows\\Fonts\\msyhbd.ttc', { family: 'YT' });
setFontFamily('YT');
createCanvasFactory((w, h) => createCanvas(w, h));
globalThis.ImageData = NodeImageData;

const SIZE = 512;
const MDL = 'C:/Users/26235/Desktop/probe_sub/yuwater/web_model/lama_512_int8.onnx';
const name = process.argv[2] || '5_极客.jpg';

const sess = await ort.InferenceSession.create(MDL);

/** 与 web/src/lib/lama.js 的 cropTo512 保持一致 */
function cropTo512(rgb, mask, W, H, cx0, cy0, cx1, cy1) {
  const cw = cx1 - cx0 + 1, ch = cy1 - cy0 + 1;
  const longSide = Math.max(cw, ch);
  const scale = Math.min(SIZE / longSide, 8);
  const nw = Math.max(8, Math.min(SIZE, Math.round(cw * scale)));
  const nh = Math.max(8, Math.min(SIZE, Math.round(ch * scale)));
  const small = new Float32Array(SIZE * SIZE * 3);
  const smask = new Uint8Array(SIZE * SIZE);
  for (let y = 0; y < nh; y++) {
    const sy = Math.min(H - 1, cy0 + Math.floor(y / scale));
    for (let x = 0; x < nw; x++) {
      const sx = Math.min(W - 1, cx0 + Math.floor(x / scale));
      const si = sy * W + sx;
      const di = (y * SIZE + x) * 3;
      small[di] = rgb[si * 3] / 255;
      small[di + 1] = rgb[si * 3 + 1] / 255;
      small[di + 2] = rgb[si * 3 + 2] / 255;
      smask[y * SIZE + x] = mask[si] ? 1 : 0;
    }
  }
  for (let y = 0; y < SIZE; y++) {
    const sy = Math.min(nh - 1, y);
    for (let x = nw; x < SIZE; x++) {
      const di = (y * SIZE + x) * 3;
      const si = (sy * SIZE + (nw - 1)) * 3;
      small[di] = small[si]; small[di + 1] = small[si + 1]; small[di + 2] = small[si + 2];
    }
  }
  for (let y = nh; y < SIZE; y++) {
    for (let x = 0; x < SIZE; x++) {
      const di = (y * SIZE + x) * 3;
      const si = ((nh - 1) * SIZE + x) * 3;
      small[di] = small[si]; small[di + 1] = small[si + 1]; small[di + 2] = small[si + 2];
    }
  }
  return { small, smask, nw, nh, scale };
}

const img = await loadImage(fs.readFileSync(path.join('C:/Users/26235/Desktop/probe_sub/yuwater/testimages', name)));
const W = img.width, H = img.height;
const cv = createCanvas(W, H);
const ctx = cv.getContext('2d', { willReadFrequently: true });
ctx.drawImage(img, 0, 0);
const data = ctx.getImageData(0, 0, W, H);

const r = buildMask(data, { strength: 4 });
console.log('掩膜', r.info.maskPx, 'px  模板框', JSON.stringify(r.info.templateBox), ' 掩膜框', JSON.stringify(r.box));

// 提取 rgb
const rgb = new Float32Array(W * H * 3);
for (let i = 0, p = 0; i < W * H; i++, p += 4) {
  rgb[i * 3] = data.data[p]; rgb[i * 3 + 1] = data.data[p + 1]; rgb[i * 3 + 2] = data.data[p + 2];
}

// 求掩膜外接框
let x0 = W, y0 = H, x1 = -1, y1 = -1;
for (let y = 0; y < H; y++) for (let x = 0; x < W; x++) if (r.mask[y * W + x]) {
  if (x < x0) x0 = x; if (x > x1) x1 = x; if (y < y0) y0 = y; if (y > y1) y1 = y;
}
const pad = Math.max(16, Math.round(Math.max(x1 - x0 + 1, y1 - y0 + 1) * 0.22));
const cx0 = Math.max(0, x0 - pad), cy0 = Math.max(0, y0 - pad);
const cx1 = Math.min(W - 1, x1 + pad), cy1 = Math.min(H - 1, y1 + pad);
console.log(`掩膜框 x[${x0},${x1}] y[${y0},${y1}]  裁剪框 x[${cx0},${cx1}] y[${cy0},${cy1}]`);

const { small, smask, nw, nh, scale } = cropTo512(rgb, r.mask, W, H, cx0, cy0, cx1, cy1);
console.log(`裁剪 ${cx1 - cx0 + 1}x${cy1 - cy0 + 1} → 模型 ${nw}x${nh} (scale ${scale.toFixed(2)})`);

// 输入张量：掩膜区置零
const N = SIZE * SIZE;
const inp = new Float32Array(4 * N);
let zeroed = 0;
for (let i = 0; i < N; i++) {
  const m = smask[i];
  if (m) zeroed++;
  inp[i] = m ? 0 : small[i * 3];
  inp[N + i] = m ? 0 : small[i * 3 + 1];
  inp[2 * N + i] = m ? 0 : small[i * 3 + 2];
  inp[3 * N + i] = m;
}
console.log(`输入张量: 512² 中置零像素 ${zeroed}（掩膜占比 ${(100 * zeroed / N).toFixed(1)}%）`);

const out = await sess.run({ input: new ort.Tensor('float32', inp, [1, 4, SIZE, SIZE]) });
const od = out.output.data;

// 贴回
const result = new Float32Array(rgb);
for (let y = 0; y < cy1 - cy0 + 1; y++) {
  const sy = Math.min(nh - 1, Math.floor(y * scale));
  for (let x = 0; x < cx1 - cx0 + 1; x++) {
    const sx = Math.min(nw - 1, Math.floor(x * scale));
    const si = sy * SIZE + sx;
    const di = ((cy0 + y) * W + (cx0 + x)) * 3;
    result[di] = od[si] * 255;
    result[di + 1] = od[N + si] * 255;
    result[di + 2] = od[2 * N + si] * 255;
  }
}
// 融合（只动掩膜内）
const merged = Float32Array.from(rgb);
for (let i = 0; i < W * H; i++) {
  if (!r.mask[i]) continue;
  const p = i * 3;
  merged[p] = result[p]; merged[p + 1] = result[p + 1]; merged[p + 2] = result[p + 2];
}

const oc = createCanvas(W, H);
const oimg = oc.getContext('2d').createImageData(W, H);
for (let i = 0, p = 0; i < W * H; i++, p += 4) {
  oimg.data[p] = merged[i * 3]; oimg.data[p + 1] = merged[i * 3 + 1];
  oimg.data[p + 2] = merged[i * 3 + 2]; oimg.data[p + 3] = 255;
}
oc.getContext('2d').putImageData(oimg, 0, 0);
const OUT = 'C:/Users/26235/Desktop/probe_sub/yuwater/web/maskdump';
fs.writeFileSync(path.join(OUT, `node_${name.replace(/\.[^.]+$/, '')}.png`),
  Buffer.from(oc.toDataURL('image/png').split(',')[1], 'base64'));
// 模型原始输出（512）也存一份
const mc = createCanvas(SIZE, SIZE);
const mimg = mc.getContext('2d').createImageData(SIZE, SIZE);
for (let i = 0, p = 0; i < N; i++, p += 4) {
  mimg.data[p] = od[i] * 255; mimg.data[p + 1] = od[N + i] * 255; mimg.data[p + 2] = od[2 * N + i] * 255; mimg.data[p + 3] = 255;
}
mc.getContext('2d').putImageData(mimg, 0, 0);
fs.writeFileSync(path.join(OUT, `node_raw512_${name.replace(/\.[^.]+$/, '')}.png`),
  Buffer.from(mc.toDataURL('image/png').split(',')[1], 'base64'));
console.log('已输出 node_*.png 与 node_raw512_*.png');
