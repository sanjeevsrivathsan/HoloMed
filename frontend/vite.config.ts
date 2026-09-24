import { defineConfig, type Plugin } from "vite";
import react from "@vitejs/plugin-react";
import { copyFileSync } from "node:fs";
import { resolve } from "node:path";
import { fileURLToPath, URL } from "node:url";

// GitHub Pages has no SPA rewrites: a direct visit or refresh of /HoloMed/imaging would be a
// GitHub 404 page. Pages serves 404.html for unknown paths, so it is a copy of index.html and the
// app routes client-side (all asset URLs are absolute under the base path, so they still resolve).
function githubPagesSpaFallback(): Plugin {
  let outDir = "dist";
  return {
    name: "holomed-github-pages-spa-fallback",
    apply: "build",
    configResolved(config) {
      outDir = resolve(config.root, config.build.outDir);
    },
    closeBundle() {
      copyFileSync(resolve(outDir, "index.html"), resolve(outDir, "404.html"));
    },
  };
}

// https://vitejs.dev/config/
export default defineConfig(({ command }) => ({
  // Production build: the GitHub Pages project site https://<user>.github.io/HoloMed/.
  // The dev server stays at "/" (http://localhost:5173/, as the local OAuth defaults expect).
  base: command === "build" ? "/HoloMed/" : "/",

  plugins: [react(), githubPagesSpaFallback()],

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
}));
