/**
 * 真实浏览器端到端测试（Playwright + Chromium）。
 *
 * 验证链路：加载页面 → 注入测试图 → 跑到「开始去水印」→ 等结果出现
 *          → 把结果图导出成 PNG 落盘，人工/程序比对。
 *
 * 用法：
 *   node scripts/e2e.mjs [测试图目录] [输出目录]
 */
import fs from 'node:fs';
import path from 'node:path';
import { chromium } from 'playwright';

const ROOT = path.resolve(import.meta.dirname, '..', 'web');
const SAMPLE_ARG = process.argv[2] || path.join(ROOT, '..', 'testimages');
const OUTDIR = process.argv[3] || path.join(ROOT, 'e2e-out');
const BASE = process.env.E2E_BASE || 'http://127.0.0.1:4173';

fs.mkdirSync(OUTDIR, { recursive: true });

// 支持传目录或单个文件；也支持只跑前 N 张（E2E_LIMIT）
let files = [];
if (fs.existsSync(SAMPLE_ARG)) {
  const st = fs.statSync(SAMPLE_ARG);
  if (st.isDirectory()) {
    files = fs.readdirSync(SAMPLE_ARG).filter((f) => /\.(jpe?g|png)$/i.test(f)).sort();
  } else {
    files = [path.basename(SAMPLE_ARG)];
  }
}
const LIMIT = Number(process.env.E2E_LIMIT || 0);
if (LIMIT > 0) files = files.slice(0, LIMIT);
const SAMPLES = fs.statSync(SAMPLE_ARG).isDirectory() ? SAMPLE_ARG : path.dirname(SAMPLE_ARG);
if (!files.length) { console.error('没有测试图:', SAMPLE_ARG); process.exit(1); }

const browser = await chromium.launch({ headless: true });
const ctx = await browser.newContext({
  viewport: { width: 412, height: 900 },
  deviceScaleFactor: 2,
  isMobile: true,
  hasTouch: true,
  userAgent: 'Mozilla/5.0 (Linux; Android 13; Pixel 7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Mobile Safari/537.36',
});
const page = await ctx.newPage();
page.on('console', (m) => {
  const t = m.text();
  if (/\[lama\]|error|fail|Error|warn/i.test(t)) console.log('  [console]', t.slice(0, 800));
});
page.on('pageerror', (e) => {
  console.log('  [pageerror]', e?.message || String(e));
  if (e?.stack) console.log('  [stack]', e.stack.split('\n').slice(0, 8).join('\n           '));
});

console.log(`打开 ${BASE} …`);
await page.goto(BASE, { waitUntil: 'domcontentloaded', timeout: 60000 });
await page.waitForSelector('text=玉用去水印', { timeout: 30000 });

let ok = 0, fail = 0;
for (const f of files) {
  const p = path.join(SAMPLES, f);
  const t0 = Date.now();
  try {
    // 通过隐藏的 file input 注入（比拖拽稳）
    await page.setInputFiles('input[type=file]', p);
    await page.waitForTimeout(1200);       // 等读图 + 初步检测

    const maskInfo = await page.textContent('.badge.right').catch(() => '');
    // 点「开始去水印」
    await page.click('.bottombar button.btn.primary');
    // 等结果图出现（最多 180s：首次要下 60MB 模型）
    await page.waitForSelector('img.result-img', { timeout: 180000 });
    await page.waitForTimeout(500);

    // 把结果 dataURL 落盘
    const dataUrl = await page.getAttribute('img.result-img', 'src');
    if (dataUrl && dataUrl.startsWith('data:image/png;base64,')) {
      const buf = Buffer.from(dataUrl.split(',')[1], 'base64');
      fs.writeFileSync(path.join(OUTDIR, f.replace(/\.[^.]+$/, '_out.png')), buf);
    }
    const dt = ((Date.now() - t0) / 1000).toFixed(1);
    console.log(`  ✓ ${f}  用时 ${dt}s  ${maskInfo}`);
    ok++;
    // 复位，准备下一张
    await page.click('text=选另一张');
    await page.waitForTimeout(400);
  } catch (e) {
    console.log(`  ✗ ${f}  ${String(e).slice(0, 200)}`);
    fail++;
    await page.goto(BASE, { waitUntil: 'domcontentloaded' });
    await page.waitForTimeout(500);
  }
}

console.log(`\n完成：成功 ${ok} / ${files.length}，失败 ${fail}`);
console.log('输出目录:', OUTDIR);
await browser.close();
process.exit(fail ? 1 : 0);
