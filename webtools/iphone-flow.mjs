import { chromium, devices } from 'playwright';
const b = await chromium.launch({ headless: true });
const ctx = await b.newContext(devices['iPhone 13']);
const p = await ctx.newPage();
p.on('pageerror', e => console.log('  [pageerror]', String(e.message).slice(0,150)));
await p.goto('https://ikun1987.github.io/demo/', { waitUntil: 'domcontentloaded', timeout: 60000 });
await p.waitForSelector('text=玉用去水印');
console.log('  1) 页面已加载');

// 选图
await p.setInputFiles('input[type=file]', 'C:/Users/26235/Desktop/probe_sub/yuwater/testimages/7_selfie.jpg');
await p.waitForTimeout(1500);
const badge = await p.textContent('.badge.right').catch(()=>'');
console.log('  2) 已选图，识别到', badge);

// 开始处理
await p.click('.bottombar .btn.primary');
console.log('  3) 已点开始，等待模型下载 + 推理…');
await p.waitForSelector('img.result-img', { timeout: 240000 });
await p.waitForTimeout(1500);
console.log('  4) 结果已生成');

// 验证长按保存所需的一切
const info = await p.evaluate(() => {
  const img = document.querySelector('img.result-img');
  const cv  = document.querySelector('canvas.overlay');
  const cs  = getComputedStyle(img);
  const rect = img.getBoundingClientRect();
  // img 与 canvas 谁在上层
  const cx = rect.left + rect.width/2, cy = rect.top + rect.height/2;
  const topEl = document.elementFromPoint(cx, cy);
  return {
    imgTag: img.tagName,
    imgZ: cs.zIndex,
    canvasZ: cv ? getComputedStyle(cv).zIndex : null,
    topElementAtCenter: topEl?.tagName + (topEl?.className ? '.'+String(topEl.className).split(' ')[0] : ''),
    imgSize: `${img.naturalWidth}x${img.naturalHeight}`,
    touchCallout: cs.webkitTouchCallout,
    userSelect: cs.userSelect,
    imgSrcPrefix: img.src.slice(0, 22),
    saveBtn: !!document.querySelector('.bottombar, .btn'),
  };
});
console.log('  5) 长按保存检查:', JSON.stringify(info, null, 0));
await p.screenshot({ path: 'e2e-online/iphone_结果.png' });
// 测滑块拖动
const box = await p.locator('.preview-wrap').boundingBox();
await p.mouse.move(box.x + box.width*0.5, box.y + box.height*0.5);
await p.mouse.down();
await p.mouse.move(box.x + box.width*0.8, box.y + box.height*0.5, { steps: 8 });
await p.mouse.up();
await p.waitForTimeout(400);
const split = await p.evaluate(() => document.querySelector('.cmp .divider')?.style.left);
console.log('  6) 对比滑块拖动后位置:', split);
await p.screenshot({ path: 'e2e-online/iphone_滑块.png' });
await b.close();
