import { chromium, devices } from 'playwright';
const URL = 'https://ikun1987.github.io/demo/';
const cases = [
  ['iPhone 13 (Safari)', devices['iPhone 13']],
  ['Pixel 7 (Chrome)',   devices['Pixel 7']],
  ['小屏 Android',       { viewport:{width:360,height:640}, deviceScaleFactor:3, isMobile:true, hasTouch:true, userAgent:'Mozilla/5.0 (Linux; Android 11) AppleWebKit/537.36 Chrome/120 Mobile Safari/537.36' }],
  ['iPad',               devices['iPad (gen 7)']],
];
const b = await chromium.launch({ headless: true });
for (const [name, dev] of cases) {
  const ctx = await b.newContext(dev);
  const p = await ctx.newPage();
  const errs = [];
  p.on('pageerror', e => errs.push(String(e.message).slice(0,120)));
  try {
    await p.goto(URL, { waitUntil: 'domcontentloaded', timeout: 60000 });
    await p.waitForSelector('text=玉用去水印', { timeout: 30000 });
    // 检查关键元素与布局是否溢出
    const info = await p.evaluate(() => {
      const de = document.documentElement;
      return {
        overflowX: de.scrollWidth > de.clientWidth ? (de.scrollWidth - de.clientWidth) : 0,
        dropVisible: !!document.querySelector('.drop'),
        canvas: !!document.querySelector('canvas'),
        btnText: document.querySelector('.bottombar .btn')?.textContent?.trim(),
        title: document.querySelector('.topbar h1')?.textContent,
      };
    });
    await p.screenshot({ path: `e2e-online/mobile_${name.replace(/[^A-Za-z0-9]/g,'_')}.png` });
    console.log(`  ${name.padEnd(20)} 标题=${info.title} 横向溢出=${info.overflowX}px 上传区=${info.dropVisible} 按钮=${info.btnText} 报错=${errs.length ? errs[0] : '无'}`);
  } catch (e) {
    console.log(`  ${name.padEnd(20)} 失败: ${String(e).slice(0,110)}`);
  }
  await ctx.close();
}
await b.close();
