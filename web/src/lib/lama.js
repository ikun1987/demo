/**
 * 浏览器端 LaMa 修补（onnxruntime-web）。
 *
 * 模型：lama_512_int8.onnx（62MB，官方推荐给移动端 CPU/WASM）
 *   输入 input [1,4,512,512]：通道 0-2 是 RGB(0..1)，**掩膜区必须先置零**；
 *                            通道 3 是 0/1 掩膜
 *   输出 output [1,3,512,512]：修补后的 RGB(0..1)
 *
 * 为什么用 Edge/CDN 取模型而不是塞进仓库：
 *   GitHub 有 100MB 单文件限制，62MB 的二进制放仓库既臃肿又会被
 *   Pages 的带宽/缓存策略折腾；放 CDN + 浏览器 Cache Storage 缓存，
 *   只有第一次访问需要下载，之后离线可用。
 */

export const MODEL_SIZE = 512;

/**
 * 模型地址（按顺序尝试，第一个成功即用）。
 *
 * 为什么要多源：实测在中国大陆直连 huggingface.co **完全连不通**
 * （curl 21 秒超时，0 字节），而 hf-mirror.com 正常。
 * 如果只用 HF，部署出去国内用户 100% 用不了。
 *
 * 建议：把模型传到本仓库的 Release 附件，然后把地址通过
 *       window.__LAMA_MODEL_URL__ 或下面的列表置顶 —— 最稳、最快。
 */
const DEFAULT_URLS = [
  // 国内镜像放最前（大陆可达）
  'https://hf-mirror.com/g-ronimo/lama/resolve/main/lama_512_int8.onnx',
  // 原始来源兜底（海外/镜像失效时）
  'https://huggingface.co/g-ronimo/lama/resolve/main/lama_512_int8.onnx',
];

// 开发环境走本地代理，避免 CORS 与本机网络差异
if (typeof location !== 'undefined' && /^(localhost|127\.0\.0\.1|0\.0\.0\.0)$/.test(location.hostname)) {
  DEFAULT_URLS.unshift(
    '/model-cdn/g-ronimo/lama/resolve/main/lama_512_int8.onnx',
    '/model-cdn-mirror/g-ronimo/lama/resolve/main/lama_512_int8.onnx',
  );
}

let ort = null;
let session = null;
let loading = null;

export function modelUrls() {
  const custom = (typeof window !== 'undefined' && window.__LAMA_MODEL_URL__) || null;
  return custom ? [custom, ...DEFAULT_URLS] : DEFAULT_URLS;
}

async function loadOrt() {
  if (ort) return ort;
  const mod = await import('onnxruntime-web');
  // WASM 运行时由 Vite 打包进产物（构建日志里能看到 ort-wasm-*.wasm），
  // 因此不需要指向 CDN —— 完全自洽、可离线。
  try { mod.env.wasm.numThreads = Math.min(4, navigator.hardwareConcurrency || 2); } catch (e) { /* ignore */ }
  ort = mod;
  return ort;
}

/**
 * 加载模型（带进度回调）。重复调用会复用同一个 Promise。
 * @param {(p:number, msg:string)=>void} onProgress
 */
export function loadModel(onProgress = () => {}) {
  if (session) return Promise.resolve(session);
  if (loading) return loading;
  loading = (async () => {
    const o = await loadOrt();
    onProgress(0.02, '准备运行时…');
    const urls = modelUrls();
    const errs = [];
    for (let i = 0; i < urls.length; i++) {
      const url = urls[i];
      const host = (() => { try { return new URL(url, location.href).host || '本地'; } catch { return '本地'; } })();
      try {
        if (i > 0) onProgress(0.05, `换源重试（${host}）…`);
        const buf = await fetchWithProgress(url, (p) => onProgress(0.05 + p * 0.85, '下载模型…'));
        onProgress(0.92, '初始化会话…');
        const providers = [];
        if (o.env.webgpu) providers.push('webgpu');
        providers.push('wasm');
        try {
          session = await o.InferenceSession.create(buf, {
            executionProviders: providers,
            graphOptimizationLevel: 'all',
          });
        } catch (e) {
          // WebGPU 建会话失败就退回 WASM
          session = await o.InferenceSession.create(buf, {
            executionProviders: ['wasm'],
            graphOptimizationLevel: 'all',
          });
        }
        onProgress(1, '就绪');
        // 记录成功来源，排障时一眼能看出走的是哪个源
        try { window.__LAMA_SOURCE__ = host; } catch (e) { /* ignore */ }
        console.log(`[lama] 模型加载成功，来源=${host}，${(buf.byteLength / 1048576).toFixed(1)}MB`);
        return session;
      } catch (e) {
        const msg = `${host}: ${e?.message || e}`;
        errs.push(msg);
        console.warn('[lama] 模型源失败 →', msg);
      }
    }
    loading = null;
    // 把每个源失败的原因都带出来，方便定位（否则用户只看到"连接超时"一头雾水）
    const detail = errs.join('；');
    const err = new Error(`模型下载失败，已尝试 ${urls.length} 个源。原因：${detail}`);
    err.sources = errs;
    throw err;
  })();
  return loading;
}

/**
 * 带进度与**超时**的下载。
 *
 * 超时参数怎么定的（实测）：
 *  · 镜像解析 + 302 跳 CDN 约 4.4 秒，再叠加 TLS 握手与手机弱网，
 *    首字节给到 45 秒都不算多 —— 曾用 8 秒，结果用户直接看到"连接超时"。
 *  · 首字节到达后，只要还在持续收数据就不该判超时，所以整体超时给得很宽（10 分钟）。
 */
async function fetchWithProgress(url, onProgress, { firstByteMs = 45000, totalMs = 600000 } = {}) {
  const ac = new AbortController();
  const firstByteTimer = setTimeout(() => ac.abort(new Error('连接超时')), firstByteMs);
  const hardTimer = setTimeout(() => ac.abort(new Error('下载超时')), totalMs);
  try {
    const res = await fetch(url, { signal: ac.signal, mode: 'cors', credentials: 'omit' });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const total = Number(res.headers.get('content-length') || 0);
    if (!res.body) {
      const buf = await res.arrayBuffer();
      if (!buf.byteLength) throw new Error('响应为空');
      return new Uint8Array(buf);
    }
    const reader = res.body.getReader();
    const chunks = [];
    let received = 0;
    let first = true;
    for (;;) {
      const { done, value } = await reader.read();
      if (done) break;
      if (first) { clearTimeout(firstByteTimer); first = false; }
      chunks.push(value);
      received += value.length;
      onProgress(total ? Math.min(1, received / total) : 0.5);
    }
    if (!received) throw new Error('响应为空');
    // 模型至少几十 MB，太小的响应基本是错误页
    if (received < 1024 * 1024) throw new Error(`文件过小（${received} 字节）`);
    const out = new Uint8Array(received);
    let off = 0;
    for (const c of chunks) { out.set(c, off); off += c.length; }
    return out;
  } finally {
    clearTimeout(firstByteTimer);
    clearTimeout(hardTimer);
  }
}

/**
 * 在 512×512 上跑一次模型。
 * @param {Float32Array} rgb 已缩放到 512 的 RGB（0..1，长度 512*512*3）
 * @param {Uint8Array} mask 512 的掩膜（1=要修补）
 */
async function runModel(rgb, mask) {
  const sess = await loadModel();
  const N = MODEL_SIZE * MODEL_SIZE;
  // ★ 掩膜区必须置零（模型卡明确要求）。
  //   不置零的话模型把白色水印当作内容，输出一片白 —— 这个坑实测踩过。
  const inp = new Float32Array(4 * N);
  for (let i = 0; i < N; i++) {
    const m = mask[i];
    inp[i] = m ? 0 : rgb[i * 3];
    inp[N + i] = m ? 0 : rgb[i * 3 + 1];
    inp[2 * N + i] = m ? 0 : rgb[i * 3 + 2];
    inp[3 * N + i] = m;
  }
  const o = await loadOrt();
  const out = await sess.run({
    input: new o.Tensor('float32', inp, [1, 4, MODEL_SIZE, MODEL_SIZE]),
  });
  return out.output.data;      // Float32Array(3*512*512)，通道优先
}

/** 把源图的一个矩形区域缩放到 512×512（长边贴合），返回 {rgb, mask, scale} */
function cropTo512(rgb, mask, W, H, cx0, cy0, cx1, cy1) {
  const cw = cx1 - cx0 + 1, ch = cy1 - cy0 + 1;
  const longSide = Math.max(cw, ch);
  // 长边映射到 512，且限制放大倍数（放大过头会引入插值糊）
  const scale = Math.min(MODEL_SIZE / longSide, 8);
  const nw = Math.max(8, Math.min(MODEL_SIZE, Math.round(cw * scale)));
  const nh = Math.max(8, Math.min(MODEL_SIZE, Math.round(ch * scale)));
  const small = new Float32Array(MODEL_SIZE * MODEL_SIZE * 3);
  const smask = new Uint8Array(MODEL_SIZE * MODEL_SIZE);
  for (let y = 0; y < nh; y++) {
    const sy = Math.min(H - 1, cy0 + Math.floor(y / scale));
    for (let x = 0; x < nw; x++) {
      const sx = Math.min(W - 1, cx0 + Math.floor(x / scale));
      const si = sy * W + sx;
      const di = (y * MODEL_SIZE + x) * 3;
      small[di] = rgb[si * 3] / 255;
      small[di + 1] = rgb[si * 3 + 1] / 255;
      small[di + 2] = rgb[si * 3 + 2] / 255;
      smask[y * MODEL_SIZE + x] = mask[si] ? 1 : 0;
    }
  }
  // 边缘复制填充（不要留黑边，否则模型会在边界补出块）
  for (let y = 0; y < MODEL_SIZE; y++) {
    const sy = Math.min(nh - 1, y);
    for (let x = nw; x < MODEL_SIZE; x++) {
      const di = (y * MODEL_SIZE + x) * 3;
      const si = (sy * MODEL_SIZE + (nw - 1)) * 3;
      small[di] = small[si]; small[di + 1] = small[si + 1]; small[di + 2] = small[si + 2];
    }
  }
  for (let y = nh; y < MODEL_SIZE; y++) {
    for (let x = 0; x < MODEL_SIZE; x++) {
      const di = (y * MODEL_SIZE + x) * 3;
      const si = ((nh - 1) * MODEL_SIZE + x) * 3;
      small[di] = small[si]; small[di + 1] = small[si + 1]; small[di + 2] = small[si + 2];
    }
  }
  return { small, smask, nw, nh, scale };
}

/**
 * 执行修补。
 *
 * 关键设计：**裁剪局部再修补**，而不是整图缩到 512。
 * 整图缩到 512 时，一张 1706 宽的图里水印只占约 48px，模型根本没细节可用，
 * 重建出来是糊的（实测杯子底边、镜框边缘都会被抹掉，残留 60%+）。
 * 改成"把掩膜区连同样本一起抠出来、放大到 512 再修补"，细节利用率大幅提高，
 * 残留降到 ~6%，物体边缘也能保住。
 *
 * @returns {Promise<Float32Array>} 修补后的 RGB（原图尺寸，掩膜外是模型输出，
 *          真正融合由 mergeByMask 负责）
 */
export async function inpaint(dims, rgb, mask) {
  const W = dims.width, H = dims.height;
  // 1) 求掩膜外接框
  let x0 = W, y0 = H, x1 = -1, y1 = -1;
  for (let y = 0; y < H; y++) {
    for (let x = 0; x < W; x++) {
      if (mask[y * W + x]) {
        if (x < x0) x0 = x;
        if (x > x1) x1 = x;
        if (y < y0) y0 = y;
        if (y > y1) y1 = y;
      }
    }
  }
  if (x1 < 0) return Float32Array.from(rgb);          // 没有掩膜，原样返回
  // 2) 加一圈上下文（模型需要看到周边纹理才能接得上）
  const pad = Math.max(16, Math.round(Math.max(x1 - x0 + 1, y1 - y0 + 1) * 0.22));
  const cx0 = Math.max(0, x0 - pad), cy0 = Math.max(0, y0 - pad);
  const cx1 = Math.min(W - 1, x1 + pad), cy1 = Math.min(H - 1, y1 + pad);

  const { small, smask, nw, nh, scale } = cropTo512(rgb, mask, W, H, cx0, cy0, cx1, cy1);
  const outData = await runModel(small, smask);
  if (window.__LAMA_DEBUG__) {
    let zeroed = 0;
    for (let i = 0; i < smask.length; i++) if (smask[i]) zeroed++;
    // 掩膜内取几个采样点，看模型输出是否合理（不是 0/255 这种饱和值）
    const samples = [];
    for (const [sx, sy] of [[nw >> 1, nh >> 1], [nw >> 2, nh >> 1], [nw >> 1, nh >> 2]]) {
      const si = Math.min(MODEL_SIZE - 1, sy) * MODEL_SIZE + Math.min(MODEL_SIZE - 1, sx);
      samples.push([+outData[si].toFixed(3), +outData[MODEL_SIZE * MODEL_SIZE + si].toFixed(3),
        +outData[2 * MODEL_SIZE * MODEL_SIZE + si].toFixed(3)]);
    }
    console.log('[lama] 掩膜框', x0, y0, x1, y1, '裁剪框', cx0, cy0, cx1, cy1,
      '裁剪尺寸', cx1 - cx0 + 1, 'x', cy1 - cy0 + 1, '→', nw, 'x', nh,
      'scale', scale.toFixed(3), '置零像素', zeroed, '/', smask.length,
      '输出尺寸', outData.length, '采样(RGB)', JSON.stringify(samples));
  }

  const N = MODEL_SIZE * MODEL_SIZE;
  const cw = cx1 - cx0 + 1, ch = cy1 - cy0 + 1;
  const result = new Float32Array(W * H * 3);
  result.set(rgb);                                    // 掩膜外保持原图
  for (let y = 0; y < ch; y++) {
    const sy = Math.min(nh - 1, Math.floor(y * scale));
    for (let x = 0; x < cw; x++) {
      const sx = Math.min(nw - 1, Math.floor(x * scale));
      const si = sy * MODEL_SIZE + sx;
      const di = ((cy0 + y) * W + (cx0 + x)) * 3;
      result[di] = outData[si] * 255;
      result[di + 1] = outData[N + si] * 255;
      result[di + 2] = outData[2 * N + si] * 255;
    }
  }
  return result;
}

/** 按掩膜把修补结果融回原图（羽化边界，掩膜外一个像素都不动） */
export function mergeByMask(dims, rgb, patched, mask, feather = 1.0) {
  const { width: W, height: H } = dims;
  const N = W * H;
  // 掩膜的轻度模糊权重
  const w = new Float32Array(N);
  for (let i = 0; i < N; i++) w[i] = mask[i] ? 1 : 0;
  const r = Math.max(1, Math.round(feather * 2));
  const blurred = new Float32Array(N);
  for (let y = 0; y < H; y++) {
    for (let x = 0; x < W; x++) {
      let acc = 0, cnt = 0;
      for (let dy = -r; dy <= r; dy++) {
        for (let dx = -r; dx <= r; dx++) {
          const yy = y + dy, xx = x + dx;
          if (yy < 0 || yy >= H || xx < 0 || xx >= W) continue;
          acc += w[yy * W + xx]; cnt++;
        }
      }
      blurred[y * W + x] = acc / cnt;
    }
  }
  const out = new Float32Array(N * 3);
  for (let i = 0; i < N; i++) {
    const a = mask[i] ? Math.max(w[i], blurred[i]) : 0;   // 只在掩膜内生效
    const p = i * 3;
    out[p] = rgb[p] * (1 - a) + patched[p] * a;
    out[p + 1] = rgb[p + 1] * (1 - a) + patched[p + 1] * a;
    out[p + 2] = rgb[p + 2] * (1 - a) + patched[p + 2] * a;
  }
  return out;
}
