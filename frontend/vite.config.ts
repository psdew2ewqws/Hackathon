import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

// Dev proxy: /api, /mjpeg, /ws -> FastAPI on :8000. The backend also serves
// the built dist/ under /app, so production can be reached standalone or
// behind the FastAPI mount.
//
// https://vitejs.dev/config/
export default defineConfig({
  plugins: [react()],
  // Production build is served by FastAPI under /app/ (StaticFiles mount).
  // Dev server runs at http://localhost:3000 on its own root, proxying the
  // backend paths below — either mode works because every asset URL becomes
  // /app/assets/* and the dev server serves /app/ as a virtual root.
  base: '/app/',
  server: {
    port: 3000,
    strictPort: true,
    proxy: {
      '/api':   { target: 'http://127.0.0.1:8000', changeOrigin: false },
      '/mjpeg': { target: 'http://127.0.0.1:8000', changeOrigin: false },
      '/ws':    { target: 'http://127.0.0.1:8000', ws: true, changeOrigin: false },
    },
  },
  build: {
    outDir: 'dist',
    emptyOutDir: true,
    sourcemap: false,
  },
});
