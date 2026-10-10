import { chromium, devices } from 'playwright';
const b = await chromium.launch({ headless: true });
const ctx = await b.newContext(devices['iPhone 13']);
const p = await ctx.newPage();
p.on('pageerror', e => console.log('  [pageerror]', String(e.message).slice(0,160)));
await p.goto('http://127.0.0.1:4180/demo/', { waitUntil: 'domcontentloaded' });
await p.setInputFiles('input[type=file]', 'C:/Users/26235/Desktop/probe_sub/yuwater/testimages/1_点赞.jpg');
await p.waitForTimeout(1500);
const t0 = Date.now();
await p.click('.bottombar .btn.primary');
// 只等快修结果（不点 AI）
await p.waitForSelector('img.result-img', { timeout: 60000 });
console.log(`  ✅ 快修出结果用时 ${((Date.now()-t0)/1000).toFixed(2)}s（无需下载任何东西）`);
const info = await p.evaluate(() => ({
  src: document.querySelector('img.result-img').src.slice(0,10),
  hasAiBtn: !!document.querySelector('.btn.ai'),
  aiBtnText: document.querySelector('.btn.ai')?.textContent?.trim(),
  tag: document.querySelector('.tag')?.textContent?.trim(),
}));
console.log('  界面状态:', JSON.stringify(info));
await p.screenshot({ path: 'e2e-online/_快修结果.png' });
await b.close();
