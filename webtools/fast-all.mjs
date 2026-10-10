import fs from 'node:fs';
import path from 'node:path';
import { chromium, devices } from 'playwright';
const OUT = 'C:/Users/26235/Desktop/probe_sub/yuwater/web/fast-out';
fs.mkdirSync(OUT, { recursive: true });
const b = await chromium.launch({ headless: true });
const ctx = await b.newContext(devices['iPhone 13']);
const p = await ctx.newPage();
await p.goto('http://127.0.0.1:4180/demo/', { waitUntil: 'domcontentloaded' });
const files = fs.readdirSync('C:/Users/26235/Desktop/probe_sub/yuwater/testimages').filter(f=>/\.jpg$/i.test(f)).sort();
for (const f of files) {
  try {
    await p.setInputFiles('input[type=file]', 'C:/Users/26235/Desktop/probe_sub/yuwater/testimages/' + f);
    await p.waitForTimeout(1300);
    const t0 = Date.now();
    await p.click('.bottombar .btn.primary');
    await p.waitForSelector('img.result-img', { timeout: 40000 });
    const dt = Date.now() - t0;
    const url = await p.getAttribute('img.result-img', 'src');
    // blob URL 不能直接读，改用 canvas 导出
    const dataUrl = await p.evaluate(async () => {
      const img = document.querySelector('img.result-img');
      const c = document.createElement('canvas');
      c.width = img.naturalWidth; c.height = img.naturalHeight;
      c.getContext('2d').drawImage(img, 0, 0);
      return c.toDataURL('image/png');
    });
    fs.writeFileSync(path.join(OUT, f.replace(/\.jpg$/i,'_fast.png')), Buffer.from(dataUrl.split(',')[1],'base64'));
    console.log(`  ✓ ${f}  快修 ${dt}ms`);
    await p.click('text=选另一张').catch(()=>{});
    await p.waitForTimeout(400);
  } catch (e) { console.log(`  ✗ ${f}  ${String(e).slice(0,90)}`); }
}
await b.close();
