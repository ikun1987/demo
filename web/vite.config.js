import { defineConfig } from 'vite';
import vue from '@vitejs/plugin-vue';

// GitHub Pages 部署在 https://<user>.github.io/<repo>/ ，所以 base 要带仓库名。
// 通过环境变量覆盖：BASE=/ npm run build（部署到用户主页仓库时）
const base = process.env.BASE || '/';

// 开发/测试时把模型请求代理出去，避免 CORS 与本机网络问题。
// 两个源都要代理：实测大陆直连 huggingface.co 不通，hf-mirror.com 正常。
const modelProxy = Object.fromEntries(
  [
    ['/model-cdn', 'https://huggingface.co'],
    ['/model-cdn-mirror', 'https://hf-mirror.com'],
  ].map(([path, target]) => [path, { target, changeOrigin: true, timeout: 900000 }]),
);

export default defineConfig({
  base,
  plugins: [vue()],
  build: {
    target: 'es2020',
    outDir: 'dist',
    assetsDir: 'assets',
    chunkSizeWarningLimit: 4096,
    // 便于排查线上问题（产物带 .map，体积可接受）
    sourcemap: true,
  },
  server: { host: true, port: 5178, proxy: modelProxy },
  preview: { host: true, port: 4173, proxy: modelProxy },
  optimizeDeps: {
    // onnxruntime-web 自带 wasm/worker，别让 vite 预打包它
    exclude: ['onnxruntime-web'],
  },
});
