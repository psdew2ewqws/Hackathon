import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

// During dev (`npm run dev`), Vite serves on :3000 and proxies /api/* to the
// Python viewer on :8000 so React fetch calls work without CORS.
//
// Production build output lands in dist/ — viewer.py serves it under the
// /signal-timing route plus /assets/* for Vite's emitted chunks. The base
// path must match the prefix viewer.py uses to expose assets.
//
// https://vitejs.dev/config/
export default defineConfig({
  plugins: [react()],
  base: '/',
  server: {
    port: 3000,
    strictPort: true,
    proxy: {
      '/api':   { target: 'http://127.0.0.1:8000', changeOrigin: false },
      '/video': { target: 'http://127.0.0.1:8000', changeOrigin: false },
    },
  },
  build: {
    outDir: 'dist',
    emptyOutDir: true,
    sourcemap: false,
    rollupOptions: {
      output: {
        manualChunks(id) {
          if (id.includes('node_modules')) {
            if (
              id.includes('/react-dom/') ||
              id.includes('/react/') ||
              id.includes('/react-router') ||
              id.includes('/scheduler/')
            ) {
              return 'react-vendor';
            }
          }
          return undefined;
        },
      },
    },
  },
});
