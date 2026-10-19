import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// Pure API-backed SPA (Vite + React Router — see docs/decisions.md). In dev,
// requests to /api/v1 are proxied to the FastAPI service, as nginx does in prod.
export default defineConfig({
  plugins: [react()],
  server: {
    host: true,
    port: 5173,
    proxy: {
      "/api/v1": {
        target: process.env.VITE_API_URL ?? "http://localhost:8000",
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/api\/v1/, ""),
      },
    },
  },
});
