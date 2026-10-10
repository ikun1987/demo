import fs from 'node:fs';
import { chromium } from 'playwright';
const b = await chromium.launch({ headless: true });
const ctx = await b.newContext({ viewport:{width:390,height:844}, deviceScaleFactor:2, isMobile:true, hasTouch:true });
const p = await ctx.newPage();
await p.goto('http://127.0.0.1:4173/', { waitUntil: 'domcontentloaded' });
await p.setInputFiles('input[type=file]', 'C:/Users/26235/Desktop/probe_sub/yuwater/testimages/5_极客.jpg');
await p.waitForTimeout(1500);
await p.click('.bottombar button.btn.primary');
await p.waitForSelector('img.result-img', { timeout: 180000 });
await p.waitForTimeout(1200);
await p.screenshot({ path: 'C:/Users/26235/Desktop/probe_sub/yuwater/web/e2e-out/_手机结果页.png' });
console.log('结果页截图已出');
// 顺便验证结果 img 是可长按保存的元素
const info = await p.evaluate(() => {
  const img = document.querySelector('img.result-img');
  return { tag: img?.tagName, srcLen: img?.src.length, w: img?.naturalWidth, h: img?.naturalHeight,
           touchCallout: getComputedStyle(img).webkitTouchCallout, hasDownload: !!document.querySelector('a[download]') };
});
console.log('结果图元素:', JSON.stringify(info));
await b.close();
