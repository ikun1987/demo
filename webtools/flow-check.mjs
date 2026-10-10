import { chromium, devices } from 'playwright';
const b = await chromium.launch({ headless: true });
const ctx = await b.newContext(devices['iPhone 13']);
const p = await ctx.newPage();
p.on('console', m => { const t = m.text(); if (/lama|超时|失败|error/i.test(t)) console.log('  [console]', t.slice(0,200)); });
p.on('pageerror', e => console.log('  [pageerror]', String(e.message).slice(0,200)));
await p.goto('http://127.0.0.1:4180/demo/', { waitUntil: 'domcontentloaded' });
await p.setInputFiles('input[type=file]', 'C:/Users/26235/Desktop/probe_sub/yuwater/testimages/2_撸猫.jpg');
await p.waitForTimeout(1500);
const t0 = Date.now();
await p.click('.bottombar .btn.primary');
// 记录进度文字变化
const seen = new Set();
const iv = setInterval(async () => {
  try { const s = await p.textContent('.card .hint, .card span'); if (s) seen.add(s.trim().slice(0,40)); } catch {}
}, 1200);
try {
  await p.waitForSelector('img.result-img', { timeout: 240000 });
  console.log(`  ✅ 完成，用时 ${((Date.now()-t0)/1000).toFixed(1)}s`);
  console.log('  过程阶段:', [...seen].slice(0,8).join(' → '));
} catch (e) {
  const err = await p.textContent('#errpanel').catch(()=>'');
  console.log('  ❌ 失败:', String(e).slice(0,120));
  if (err) console.log('  页面错误面板:', err.replace(/\s+/g,' ').slice(0,300));
}
clearInterval(iv);
await b.close();
