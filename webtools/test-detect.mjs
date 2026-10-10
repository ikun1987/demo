/**
 * Node 端检测算法自测：把 JS 移植版和 Python 版结果对齐。
 *
 * 用 node-canvas 提供 canvas 工厂与 ImageData，从而让 detect.js 能在 Node 里跑。
 * 需要先 `npm run build` 之前单独跑：
 *   node scripts/test-detect.mjs
 */
import fs from 'node:fs';
import path from 'node:path';
import { createCanvas, loadImage, ImageData as NodeImageData, registerFont } from 'canvas';
import { createCanvasFactory, buildMask, setFontFamily } from '../web/src/lib/detect.js';

// Node 端要显式注册中文字体，否则字模渲染出来和浏览器不一致
// （字模不准 → 字号选错 → 掩膜盖不住水印）
for (const f of ['msyhbd.ttc', 'msyh.ttc', 'Dengb.ttf', 'simhei.ttf']) {
  const p = path.join('C:\\Windows\\Fonts', f);
  if (fs.existsSync(p)) {
    try { registerFont(p, { family: 'YuyongTestFont' }); setFontFamily('YuyongTestFont'); break; } catch (e) { /* next */ }
  }
}

// 注入 canvas 工厂与 ImageData
createCanvasFactory((w, h) => createCanvas(w, h));
globalThis.ImageData = NodeImageData;

const SAMPLE_DIR = process.env.SAMPLE_DIR
  || path.join(process.env.TEMP || '/tmp', 'doubao_real', 'in');

function toImageData(canvas, img) {
  const ctx = canvas.getContext('2d');
  ctx.drawImage(img, 0, 0);
  return ctx.getImageData(0, 0, canvas.width, canvas.height);
}

const files = fs.existsSync(SAMPLE_DIR)
  ? fs.readdirSync(SAMPLE_DIR).filter((f) => /\.(jpe?g|png)$/i.test(f)).sort()
  : [];

if (!files.length) {
  console.error(`找不到测试图目录: ${SAMPLE_DIR}`);
  process.exit(1);
}

console.log(`测试图目录: ${SAMPLE_DIR}`);
console.log(`${'文件'.padEnd(18)}${'定位分'.padStart(8)}${'字号'.padStart(6)}${'掩膜px'.padStart(10)}${'耗时ms'.padStart(9)}`);

for (const f of files) {
  const p = path.join(SAMPLE_DIR, f);
  // node-canvas 的 loadImage 不支持非 ASCII 路径，先读成 Buffer 再喂进去
  const img = await loadImage(fs.readFileSync(p));
  // 与浏览器一致：超大图先缩到 MAX=2400
  const MAX = 2400;
  const scale = Math.min(1, MAX / Math.max(img.width, img.height));
  const w = Math.round(img.width * scale);
  const h = Math.round(img.height * scale);
  const cv = createCanvas(w, h);
  const data = toImageData(cv, img);

  const t0 = Date.now();
  const r = buildMask(data, { strength: 4 });
  const dt = Date.now() - t0;

  if (!r) {
    console.log(`${f.padEnd(18)}${'未定位'.padStart(8)}`);
    continue;
  }
  console.log(
    `${f.padEnd(18)}${r.score.toFixed(3).padStart(8)}${String(r.px).padStart(6)}`
    + `${String(r.info.maskPx).padStart(10)}${String(dt).padStart(9)}`,
  );
  console.log(`  模板框: ${JSON.stringify(r.info.templateBox)}  掩膜框: ${JSON.stringify(r.box)}`);
}
