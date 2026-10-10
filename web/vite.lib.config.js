import { defineConfig } from 'vite';
import { resolve } from 'node:path';

// 只给自动化测试用：把 src/lib 打成 ESM，方便在真实浏览器页面里 import
export default defineConfig({
  build: {
    outDir: 'libdist',
    emptyOutDir: true,
    target: 'es2020',
    lib: {
      entry: {
        detect: resolve(import.meta.dirname, 'src/lib/detect.js'),
        lama: resolve(import.meta.dirname, 'src/lib/lama.js'),
        imageops: resolve(import.meta.dirname, 'src/lib/imageops.js'),
      },
      formats: ['es'],
    },
    rollupOptions: {
      external: [],
    },
  },
});
