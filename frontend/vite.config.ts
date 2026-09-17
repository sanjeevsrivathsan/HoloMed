import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import { fileURLToPath, URL } from 'node:url';

// https://vitejs.dev/config/
export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      '@': fileURLToPath(new URL('./src', import.meta.url)),
    },
  },
  optimizeDeps: {
    exclude: ['lucide-react'],
  },
  server: {
    port: 5173,
    strictPort: true,
    proxy: {
      // Forward /api/* to the FastAPI backend during development.
      // This keeps frontend and backend on the same effective origin so
      // the HttpOnly session cookie works without cross-origin complexity.
      '/api': {
        target: 'http://127.0.0.1:8001',
        changeOrigin: true,
      },
      // Forward /ohif/* so the embedded OHIF iframe also shares the same
      // cookie origin and the session is carried to DICOMweb requests.
      '/ohif': {
        target: 'http://127.0.0.1:8001',
        changeOrigin: true,
      },
    },
  },
});
