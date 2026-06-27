import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    port: 5173,
    proxy: {
      // Convenience for `npm run dev`: forward API calls to the backend.
      "/api": { target: "http://localhost:8000", changeOrigin: true },
    },
  },
});
