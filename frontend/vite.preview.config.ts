// Build config for the standalone landing-page export (see preview/main.tsx).
// Separate from vite.config.ts so the app build is untouched.
//
//   npx vite build --config vite.preview.config.ts
//
// Emits a normal multi-file bundle; scripts/inline-preview.mjs then folds the
// CSS and JS into a single self-contained .html that can be emailed.
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";

export default defineConfig({
  root: "preview",
  plugins: [react(), tailwindcss()],
  build: {
    outDir: "../.preview-dist",
    emptyOutDir: true,
    // One JS chunk and one CSS file, so inlining is a straight substitution.
    cssCodeSplit: false,
    modulePreload: { polyfill: false },
    rollupOptions: {
      output: { inlineDynamicImports: true, entryFileNames: "bundle.js", assetFileNames: "bundle[extname]" },
    },
  },
});
