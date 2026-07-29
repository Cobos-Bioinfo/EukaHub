import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// Pure API-backed SPA (Vite + React Router — see DECISIONS.md). In dev,
// requests to /api are proxied to the FastAPI service.
export default defineConfig({
  plugins: [react()],
  server: {
    host: true,
    port: 5173,
    proxy: {
      "/api": {
        target: process.env.VITE_API_URL ?? "http://localhost:8000",
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/api/, ""),
      },
    },
  },
});
