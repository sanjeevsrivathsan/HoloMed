import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import { fileURLToPath, URL } from "node:url";

// https://vitejs.dev/config/
export default defineConfig({
  base: "/HoloMed/",

  plugins: [react()],

  resolve: {
    alias: {
      "@": fileURLToPath(new URL("./src", import.meta.url)),
    },
  },

  optimizeDeps: {
    exclude: ["lucide-react"],
  },

  server: {
    port: 5173,
    strictPort: true,

    proxy: {
      // Forward /api/* to the FastAPI backend during development.
      // This keeps frontend and backend on the same effective origin.
      "/api": {
        target: "http://127.0.0.1:8001",
        changeOrigin: true,
      },

      // Forward /ohif/* so the embedded OHIF iframe also shares
      // the same cookie origin and can access DICOMweb requests.
      "/ohif": {
        target: "http://127.0.0.1:8001",
        changeOrigin: true,
      },
    },
  },
});
