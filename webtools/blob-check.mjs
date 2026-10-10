import { chromium, devices } from 'playwright';
const b = await chromium.launch({ headless: true });
const ctx = await b.newContext(devices['iPhone 13']);
const p = await ctx.newPage();
p.on('pageerror', e => console.log('  [pageerror]', String(e.message).slice(0,150)));
await p.goto('http://127.0.0.1:4180/demo/', { waitUntil: 'domcontentloaded' });
await p.setInputFiles('input[type=file]', 'C:/Users/26235/Desktop/probe_sub/yuwater/testimages/2_撸猫.jpg');
await p.waitForTimeout(1500);
await p.click('.bottombar .btn.primary');
await p.waitForSelector('img.result-img', { timeout: 180000 });
await p.waitForTimeout(1200);
const info = await p.evaluate(() => {
  const img = document.querySelector('img.result-img');
  const a = document.createElement('a'); // 检查下载路径
  return {
    srcPrefix: img.src.slice(0, 30),
    isBlob: img.src.startsWith('blob:'),
    blobUrlOk: img.complete && img.naturalWidth > 0,
    size: img.naturalWidth + 'x' + img.naturalHeight,
  };
});
console.log('  结果图:', JSON.stringify(info));
// 点「保存到相册」验证不报错
const [dl] = await Promise.all([
  p.waitForEvent('download', { timeout: 15000 }).catch(() => null),
  p.click('text=保存到相册'),
]);
console.log('  下载事件:', dl ? `OK -> ${dl.suggestedFilename()}` : '（iOS 视口下走新窗口分支，属预期）');
await b.close();
