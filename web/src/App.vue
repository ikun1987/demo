<template>
  <div class="app">
    <!-- 顶栏 -->
    <div class="topbar">
      <div class="logo">玉</div>
      <div>
        <h1>玉用去水印</h1>
        <div class="sub">豆包水印清除 · 本地处理不上传</div>
      </div>
      <div class="right">
        <button class="iconbtn" v-if="hasImage" @click="reset" title="重新选择">↺</button>
        <button class="iconbtn" @click="showAbout = true" title="关于">？</button>
      </div>
    </div>

    <div class="main">
      <!-- 未选图：上传区 -->
      <template v-if="!hasImage">
        <div class="drop" :class="{ over: dragOver }"
             @click="pickFile" @dragover.prevent="dragOver = true"
             @dragleave="dragOver = false" @drop.prevent="onDrop">
          <div class="big">🖼️</div>
          <div class="t1">点这里选择图片</div>
          <div class="t2">也可以把图拖进来 · 支持多选</div>
          <div class="pills">
            <span class="pill">纯本地处理</span>
            <span class="pill">不上传服务器</span>
            <span class="pill">支持长按保存</span>
          </div>
        </div>
        <div class="card" style="margin-top:12px">
          <div class="hint">
            <b style="color:var(--accent)">怎么用：</b>选图 → 点「开始去水印」→ 长按结果图保存到相册。
            豆包默认把「豆包AI生成」放在右下角，本工具会自动识别并抹除，背景由 AI 修复。
          </div>
        </div>
      </template>

      <!-- 已选图 -->
      <template v-else>
        <!-- 预览 -->
        <div class="card" style="padding:8px">
          <div class="preview-wrap cmp" ref="wrapRef"
               @pointerdown="onPointerDown"
               @pointermove="onPointerMove"
               @pointerup="onPointerUp"
               @pointercancel="onPointerUp">
            <!-- 结果用真 <img>：只有 img 元素长按才会弹出系统「存储图像」，
                 canvas 长按在手机上不会出现保存菜单（实测） -->
            <img v-if="resultUrl" ref="resultImgRef" class="result-img"
                 :src="resultUrl" alt="去水印结果" />
            <canvas ref="viewRef" :class="{ overlay: !!resultUrl }"></canvas>
            <div class="divider" :style="{ left: splitPct + '%' }" v-if="resultUrl"></div>
            <div class="knob" :style="{ left: splitPct + '%' }" v-if="resultUrl">⇔</div>
            <div class="badge">{{ resultUrl ? (splitPct > 50 ? '拖动滑块看修复后' : '左半：原图') : '原图' }}</div>
            <div class="badge right" v-if="maskPx">{{ maskPx.toLocaleString() }} px 待修</div>
          </div>
          <div class="hint" style="text-align:center;margin-top:8px">
            {{ resultUrl ? '左右拖动滑块对比 · 长按图片保存到相册' : '点下方按钮开始处理' }}
          </div>
        </div>

        <!-- 参数 -->
        <div class="card" v-if="!resultUrl">
          <div class="row">
            <label>处理强度</label>
            <input type="range" min="1" max="5" step="1" v-model.number="strength" />
            <span class="val">{{ strengthName }}</span>
          </div>
          <div class="row">
            <label>手动涂抹</label>
            <div class="switch" :class="{ on: brushMode }" @click="toggleBrush"><i></i></div>
            <span class="hint">{{ brushMode ? '在图上涂抹要清除的区域' : '自动识别失败时用' }}</span>
          </div>
          <div class="row" v-if="brushMode">
            <label>笔刷大小</label>
            <input type="range" min="8" max="90" step="2" v-model.number="brushSize" />
            <span class="val">{{ brushSize }}</span>
          </div>
        </div>

        <!-- 结果 -->
        <div class="card" v-if="resultUrl">
          <div class="result-actions">
            <button class="btn primary" @click="download">⬇︎ 保存到相册</button>
            <button class="btn" @click="doProcess">↻ 再修一次</button>
          </div>

          <!-- AI 深度修复升级（可选，需要下载模型） -->
          <div v-if="engine === 'fast'" class="upgrade">
            <div class="upgrade-head">
              <span class="tag">快修版</span>
              <button class="btn ai" :disabled="busy" @click="refineWithAI">
                {{ busy ? 'AI 处理中…' : '✨ 用 AI 深度修复' }}
              </button>
            </div>
            <div class="hint" style="margin-top:8px">
              已经能用了。若背景纹理复杂、边缘有轻微模糊，点上面这个按钮，
              首次会下载约 60MB 的 AI 模型（建议 Wi-Fi），效果更干净。
            </div>
          </div>
          <div v-else-if="engine === 'lama'" class="tip" style="margin-top:10px">
            ✨ 已完成 <b>AI 深度修复</b>（LaMa 重建背景）
          </div>

          <div class="tip">
            📱 <b>手机上保存：</b>长按上方结果图 → 选「存储图像 / 保存图片」。
            若长按没反应，点「保存到相册」按钮；iPhone 上用 Safari 打开效果最好。
          </div>
          <div class="result-actions" style="margin-top:10px">
            <button class="btn" @click="reset">选另一张</button>
          </div>
        </div>

        <!-- 进度 -->
        <div class="card" v-if="busy">
          <div style="display:flex;align-items:center;gap:8px">
            <span class="spinner"></span>
            <span style="font-size:14px">{{ stageText }}</span>
          </div>
          <div class="progress"><i :style="{ width: (progress * 100).toFixed(1) + '%' }"></i></div>
          <div class="hint">{{ progressText }}</div>
        </div>
      </template>
    </div>

    <!-- 底部固定操作条 -->
    <div class="bottombar" v-if="hasImage">
      <button class="btn primary" :disabled="busy" @click="doProcess">
        {{ busy ? '处理中…' : (resultUrl ? '重新处理' : '开始去水印') }}
      </button>
      <button class="btn" style="flex:0 0 96px" @click="pickFile">换图</button>
    </div>

    <!-- 关于 -->
    <div class="mask" v-if="showAbout" @click.self="showAbout = false">
      <div class="modal">
        <h3>关于玉用去水印</h3>
        <p>专治豆包导出图上的「豆包AI生成」水印（白色填充 + 亮描边那种）。</p>
        <p><b style="color:var(--accent)">隐私：</b>所有处理都在你的手机/电脑浏览器里完成，
          图片不会上传到任何服务器，断网也能用（首次需联网下载一次 AI 模型，之后会缓存）。</p>
        <p><b style="color:var(--accent)">技术：</b>字模匹配定位水印 → 生成整块掩膜 →
          LaMa 深度修补网络重建被覆盖的背景。</p>
        <p style="font-size:12px">模型首次下载约 60MB，请尽量在 Wi-Fi 下使用。</p>
        <button class="btn primary" style="margin-top:12px" @click="showAbout = false">知道了</button>
      </div>
    </div>

    <div class="toast" v-if="toast">{{ toast }}</div>

    <!-- 错误面板：便于排查（正常时不显示） -->
    <div v-if="errText" class="errpanel" id="errpanel">
      <div style="display:flex;gap:8px;align-items:center">
        <b style="color:var(--danger)">出错了</b>
        <button class="iconbtn" style="margin-left:auto;width:26px;height:26px" @click="errText=''">✕</button>
      </div>
      <pre>{{ errText }}</pre>
    </div>

    <input ref="fileRef" type="file" accept="image/*" multiple
           style="display:none" @change="onFileChange" />
  </div>
</template>

<script setup>
import { ref, computed, onMounted, onBeforeUnmount, nextTick } from 'vue';
import { buildMask } from './lib/detect.js';
import { loadModel, inpaint, mergeByMask } from './lib/lama.js';
import { fastInpaint } from './lib/fastinpaint.js';

const fileRef = ref(null);
const wrapRef = ref(null);
const viewRef = ref(null);
const resultImgRef = ref(null);

const fileName = ref('');
const srcImage = ref(null);       // HTMLImageElement
const srcData = ref(null);        // ImageData
const resultData = ref(null);     // ImageData
const resultUrl = ref('');
const resultBlobUrl = ref('');    // 结果图的 Blob URL（长按保存用）
const resultBlob = ref(null);
const engine = ref('');           // 'fast' | 'lama'
const usedMask = ref(null);       // 本次处理用的掩膜（供 AI 升级复用）
const maskPx = ref(0);
const strength = ref(4);
const brushMode = ref(false);
const brushSize = ref(26);
const busy = ref(false);
const progress = ref(0);
const stageText = ref('');
const dragOver = ref(false);
const showAbout = ref(false);
const toast = ref('');
const errText = ref('');
const splitPct = ref(50);
const isIOS = /iPad|iPhone|iPod/.test(navigator.userAgent);

const customMask = ref(null);     // 手动涂抹掩膜（Uint8Array）
let brushing = false;
let draggingSplit = false;

const hasImage = computed(() => !!srcImage.value);
const strengthName = computed(() => ['', '保守', '轻柔', '标准', '强力', '极致'][strength.value]);
const progressText = computed(() => `${(progress.value * 100).toFixed(0)}%`);

/* ---------------- 提示 ---------------- */
let toastTimer = null;
function tip(msg, ms = 2200) {
  toast.value = msg;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => { toast.value = ''; }, ms);
}

/* ---------------- 选图 ---------------- */
function pickFile() {
  const el = fileRef.value;
  if (!el) { tip('页面还没准备好，请稍后重试'); return; }
  try { el.click(); } catch (e) { tip('这个浏览器不允许唤起文件选择，请用下方按钮'); }
}

function onFileChange(e) {
  const files = Array.from(e.target.files || []);
  if (files.length) handleFiles(files);
  e.target.value = '';
}

function onDrop(e) {
  dragOver.value = false;
  const files = Array.from(e.dataTransfer?.files || []).filter((f) => f.type.startsWith('image/'));
  if (files.length) handleFiles(files);
}

async function handleFiles(files) {
  // 目前一次处理一张：取第一张
  const file = files[0];
  if (files.length > 1) tip(`一次处理一张，已选「${file.name}」`);
  fileName.value = file.name;
  const url = URL.createObjectURL(file);
  const img = new Image();
  img.onload = async () => {
    try {
      srcImage.value = img;
      // 超大图先缩到合理尺寸，避免手机内存爆掉
      const MAX = 2400;
      const w = img.naturalWidth, h = img.naturalHeight;
      const scale = Math.min(1, MAX / Math.max(w, h));
      const dw = Math.round(w * scale), dh = Math.round(h * scale);
      const cv = document.createElement('canvas');
      cv.width = dw; cv.height = dh;
      const ctx = cv.getContext('2d', { willReadFrequently: true });
      ctx.drawImage(img, 0, 0, dw, dh);
      srcData.value = ctx.getImageData(0, 0, dw, dh);
      resultData.value = null;
      resultUrl.value = '';
      customMask.value = null;
      maskPx.value = 0;
      brushMode.value = false;
      URL.revokeObjectURL(url);
      await nextTick();
      draw();
      // 先算一次掩膜，告诉用户识别到多少像素
      setTimeout(analyzeOnly, 30);
    } catch (e) {
      reportError(e, '读图');
    }
  };
  img.onerror = () => { tip('这张图读不出来，换一张试试'); URL.revokeObjectURL(url); };
  img.src = url;
}

/** 统一的错误上报：既提示用户，也留一条可被自动化读取的记录 */
function reportError(e, where) {
  const msg = `${where}出错：${e?.message || e}`;
  console.error('[yuyong]', msg, e);
  errText.value = `${msg}\n${String(e?.stack || '').split('\n').slice(0, 4).join('\n')}`;
  tip(msg, 4000);
}

function analyzeOnly() {
  if (!srcData.value) return;
  try {
    const r = buildMask(srcData.value, { strength: strength.value });
    if (r) {
      customMask.value = r.mask;
      maskPx.value = r.info.maskPx;
    } else {
      customMask.value = null;
      maskPx.value = 0;
      tip('没自动识别到水印，可打开「手动涂抹」自己圈一下');
    }
    draw();
  } catch (e) {
    console.warn(e);
  }
}

/* ---------------- 绘制 ---------------- */
/**
 * 两段式渲染：
 *  · 处理前：canvas 直接显示原图（+手动涂抹高亮）
 *  · 处理后：底层放真 <img> 显示结果（长按可保存），
 *           canvas 变为覆盖层，只把「分割线左侧」的原图画上去，形成对比效果。
 */
function draw() {
  const cv = viewRef.value;
  if (!cv || !srcData.value) return;
  const src = srcData.value;
  const showCompare = !!resultData.value;

  const wrapW = wrapRef.value?.clientWidth || 320;
  const dpr = Math.min(2, window.devicePixelRatio || 1);
  const dispW = Math.max(80, wrapW - 16);
  const cssH = dispW * (src.height / src.width);
  cv.width = Math.round(dispW * dpr);
  cv.height = Math.round(cssH * dpr);
  cv.style.width = '100%';
  cv.style.height = cssH + 'px';

  const ctx = cv.getContext('2d');
  ctx.clearRect(0, 0, cv.width, cv.height);

  if (!showCompare) {
    const off = document.createElement('canvas');
    off.width = src.width; off.height = src.height;
    off.getContext('2d').putImageData(src, 0, 0);
    ctx.drawImage(off, 0, 0, cv.width, cv.height);
  } else {
    // 只画左侧原图部分
    const cut = Math.round(cv.width * (splitPct.value / 100));
    if (cut > 0) {
      const off = document.createElement('canvas');
      off.width = src.width; off.height = src.height;
      off.getContext('2d').putImageData(src, 0, 0);
      ctx.save();
      ctx.beginPath();
      ctx.rect(0, 0, cut, cv.height);
      ctx.clip();
      ctx.drawImage(off, 0, 0, cv.width, cv.height);
      ctx.restore();
      // 分割线（画在 canvas 里，随尺寸缩放）
      ctx.fillStyle = '#5eead4';
      ctx.fillRect(cut - dpr, 0, dpr * 2, cv.height);
    }
  }

  // 手动涂抹高亮（未处理时）
  if (brushMode.value && customMask.value && !showCompare) {
    const md = new ImageData(src.width, src.height);
    for (let i = 0, p = 0; i < customMask.value.length; i++, p += 4) {
      if (customMask.value[i]) { md.data[p] = 94; md.data[p + 1] = 234; md.data[p + 2] = 212; md.data[p + 3] = 95; }
    }
    const off2 = document.createElement('canvas');
    off2.width = src.width; off2.height = src.height;
    off2.getContext('2d').putImageData(md, 0, 0);
    ctx.drawImage(off2, 0, 0, cv.width, cv.height);
  }
}

/* ---------------- 交互：对比滑块 / 涂抹 ---------------- */
function canvasPos(ev) {
  // 用最外层容器换算坐标：触摸交互挂在容器上（这样 img 能保持可长按保存）
  const el = wrapRef.value || viewRef.value;
  const rect = el.getBoundingClientRect();
  const x = (ev.clientX - rect.left) / rect.width;
  const y = (ev.clientY - rect.top) / rect.height;
  return { nx: Math.min(1, Math.max(0, x)), ny: Math.min(1, Math.max(0, y)) };
}

function onPointerDown(ev) {
  if (!srcData.value) return;
  const { nx } = canvasPos(ev);
  if (brushMode.value && !resultData.value) {
    brushing = true;
    if (!customMask.value) customMask.value = new Uint8Array(srcData.value.width * srcData.value.height);
    paintAt(ev);
    return;
  }
  if (resultUrl.value) {
    draggingSplit = true;
    splitPct.value = Math.round(nx * 100);
    draw();
  }
}

function onPointerMove(ev) {
  if (brushing) { paintAt(ev); return; }
  if (!draggingSplit) return;
  const { nx } = canvasPos(ev);
  splitPct.value = Math.round(nx * 100);
  draw();
}

function onPointerUp() { brushing = false; draggingSplit = false; }

function paintAt(ev) {
  const src = srcData.value;
  const { nx, ny } = canvasPos(ev);
  const cx = nx * src.width, cy = ny * src.height;
  const r = brushSize.value / 2;
  const m = customMask.value;
  const x0 = Math.max(0, Math.floor(cx - r)), x1 = Math.min(src.width - 1, Math.ceil(cx + r));
  const y0 = Math.max(0, Math.floor(cy - r)), y1 = Math.min(src.height - 1, Math.ceil(cy + r));
  let n = 0;
  for (let y = y0; y <= y1; y++) {
    for (let x = x0; x <= x1; x++) {
      const dx = x - cx, dy = y - cy;
      if (dx * dx + dy * dy <= r * r) {
        if (!m[y * src.width + x]) n++;
        m[y * src.width + x] = 1;
      }
    }
  }
  maskPx.value += n;
  draw();
}

function toggleBrush() {
  brushMode.value = !brushMode.value;
  if (brushMode.value && !customMask.value && srcData.value) {
    customMask.value = new Uint8Array(srcData.value.width * srcData.value.height);
    maskPx.value = 0;
  }
  if (brushMode.value) tip('用手指在图上涂掉水印区域，然后点「开始去水印」');
  draw();
}

/* ---------------- 主流程 ---------------- */
/**
 * 两段式处理：
 *   ① 快修（fastinpaint）：纯本地，**无需下载任何东西**，1 秒内出结果。
 *      保证任何网络环境下都能拿到成品 —— 这是可用性底线。
 *   ② AI 深度修复（LaMa，需下 59MB 模型）：可选升级，复杂背景/硬边效果更好。
 * 这样"网络不好"再也不会变成"什么都拿不到"。
 */
async function doProcess() {
  if (!srcData.value || busy.value) return;
  busy.value = true;
  progress.value = 0;
  stageText.value = '准备中…';
  try {
    const src = srcData.value;
    const W = src.width, H = src.height;
    let mask = customMask.value;
    if (!mask) {
      stageText.value = '识别水印…';
      await new Promise((r) => setTimeout(r, 20));
      const r = buildMask(src, { strength: strength.value });
      if (!r) {
        busy.value = false;
        tip('没识别到水印：可打开「手动涂抹」自己圈出水印位置');
        return;
      }
      mask = r.mask;
      maskPx.value = r.info.maskPx;
    }

    // 提取 RGB
    const rgb = new Float32Array(W * H * 3);
    for (let i = 0, p = 0; i < W * H; i++, p += 4) {
      rgb[i * 3] = src.data[p];
      rgb[i * 3 + 1] = src.data[p + 1];
      rgb[i * 3 + 2] = src.data[p + 2];
    }

    stageText.value = '快速修复中…';
    progress.value = 0.3;
    await new Promise((r) => setTimeout(r, 20));
    const { rgb: fastOut, ms } = fastInpaint({ width: W, height: H }, rgb, mask);
    console.log(`[fast] 快修完成 ${ms.toFixed(0)}ms`);

    await commitResult(fastOut, W, H);
    engine.value = 'fast';
    usedMask.value = mask;
    progress.value = 1;
    stageText.value = '完成';
    tip('已修好！长按图片保存 · 觉得不够干净可点「AI 深度修复」');
  } catch (e) {
    reportError(e, '处理');
  } finally {
    busy.value = false;
  }
}

/** 用 AI（LaMa）再修一次，效果更好但需要下载模型 */
async function refineWithAI() {
  if (!srcData.value || busy.value) return;
  const src = srcData.value;
  const W = src.width, H = src.height;
  const mask = usedMask.value || customMask.value;
  if (!mask) { tip('请先处理一次或手动涂抹水印区域'); return; }
  busy.value = true;
  progress.value = 0;
  stageText.value = '准备 AI 模型…';
  try {
    await loadModel((p, msg) => { progress.value = p * 0.6; stageText.value = msg; });
    stageText.value = 'AI 修复中…';
    progress.value = 0.65;
    await new Promise((r) => setTimeout(r, 20));

    const rgb = new Float32Array(W * H * 3);
    for (let i = 0, p = 0; i < W * H; i++, p += 4) {
      rgb[i * 3] = src.data[p];
      rgb[i * 3 + 1] = src.data[p + 1];
      rgb[i * 3 + 2] = src.data[p + 2];
    }
    const patched = await inpaint({ width: W, height: H }, rgb, mask);
    progress.value = 0.92;
    const merged = mergeByMask({ width: W, height: H }, rgb, patched, mask, 1.0);
    await commitResult(merged, W, H);
    engine.value = 'lama';
    progress.value = 1;
    stageText.value = '完成';
    tip('AI 深度修复完成');
  } catch (e) {
    // AI 失败不影响已有结果：明确告诉用户快修版仍然可用
    console.error(e);
    tip(`AI 修复失败（${e?.message || e}）。上面这份是快修版，仍然可以保存`, 6000);
  } finally {
    busy.value = false;
  }
}

/** 把结果写进界面：转 ImageData → Blob URL → 触发重绘 */
async function commitResult(floatRgb, W, H) {
  const out = new ImageData(W, H);
  for (let i = 0, p = 0; i < W * H; i++, p += 4) {
    out.data[p] = Math.max(0, Math.min(255, floatRgb[i * 3]));
    out.data[p + 1] = Math.max(0, Math.min(255, floatRgb[i * 3 + 1]));
    out.data[p + 2] = Math.max(0, Math.min(255, floatRgb[i * 3 + 2]));
    out.data[p + 3] = 255;
  }
  resultData.value = out;
  // 用 Blob URL 而不是 dataURL：iOS Safari 对 dataURL 有长度限制
  // （大图 base64 动辄 2~4MB 会被拒绝），Blob URL 没这个问题，
  // 而且长按保存、下载、新窗口打开三种路径都更稳。
  const cv = document.createElement('canvas');
  cv.width = W; cv.height = H;
  cv.getContext('2d').putImageData(out, 0, 0);
  const blob = await new Promise((res) => cv.toBlob(res, 'image/png'));
  if (resultBlobUrl.value) URL.revokeObjectURL(resultBlobUrl.value);
  resultBlobUrl.value = blob ? URL.createObjectURL(blob) : cv.toDataURL('image/png');
  resultBlob.value = blob;
  resultUrl.value = resultBlobUrl.value;
  splitPct.value = 50;
  await nextTick();
  draw();
  bindLongPressGuide();
}

function download() {
  if (!resultUrl.value) return;
  const base = (fileName.value || 'image').replace(/\.[^.]+$/, '');
  const name = `${base}_已去水印.png`;
  const a = document.createElement('a');
  a.href = resultBlobUrl.value || resultUrl.value;
  a.download = name;
  // iOS 上 download 属性支持不好，改为新窗口打开让用户长按保存
  if (isIOS) {
    const w = window.open('', '_blank');
    if (w) {
      w.document.write(
        `<title>${name}</title>`
        + '<meta name="viewport" content="width=device-width,initial-scale=1">'
        + '<body style="margin:0;background:#0f1218;display:grid;place-items:center;min-height:100vh">'
        + `<img src="${a.href}" style="max-width:100%;height:auto">`
        + '<p style="color:#93a1b8;font:13px/1.6 -apple-system,sans-serif;text-align:center;padding:12px">'
        + '长按这张图 → 选「存储图像」即可保存到相册</p></body>',
      );
      w.document.close();
      tip('已在新页打开，长按图片保存到相册');
      return;
    }
  }
  document.body.appendChild(a);
  a.click();
  a.remove();
  tip('已开始下载；若没反应请长按上方结果图保存');
}

function reset() {
  if (resultBlobUrl.value) URL.revokeObjectURL(resultBlobUrl.value);
  srcImage.value = null; srcData.value = null; resultData.value = null;
  resultUrl.value = ''; resultBlobUrl.value = ''; resultBlob.value = null;
  customMask.value = null; maskPx.value = 0;
  fileName.value = ''; brushMode.value = false; splitPct.value = 50;
  engine.value = ''; usedMask.value = null;
  errText.value = '';
}

/* ---------------- 长按保存（移动端） ---------------- */
// 结果用真 <img> 呈现，长按即可弹出系统「存储图像」；
// 这里只做一次引导提示，不拦截事件（拦截反而会挡住系统菜单）。
let longPressTimer = null;
function bindLongPressGuide() {
  const el = resultImgRef.value;
  if (!el) return;
  const start = () => {
    longPressTimer = setTimeout(() => tip('松手后可选「存储图像」保存到相册', 2500), 500);
  };
  const cancel = () => clearTimeout(longPressTimer);
  el.addEventListener('touchstart', start, { passive: true });
  el.addEventListener('touchend', cancel, { passive: true });
  el.addEventListener('touchcancel', cancel, { passive: true });
  el.addEventListener('contextmenu', cancel);
}

onMounted(() => {
  window.addEventListener('resize', draw);
  // 阻止在画布上长按弹出菜单（画布是我们的交互层，不是图片）
  document.addEventListener('contextmenu', (e) => {
    if (e.target && e.target.tagName === 'CANVAS') e.preventDefault();
  });
});
onBeforeUnmount(() => {
  window.removeEventListener('resize', draw);
  clearTimeout(toastTimer); clearTimeout(longPressTimer);
});
</script>
