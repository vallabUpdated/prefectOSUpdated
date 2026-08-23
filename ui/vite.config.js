import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Flask backend (server.py) runs on 5055 by default.
const BACKEND = process.env.ORCH_BACKEND || "http://127.0.0.1:5055";

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    // Every backend route the UI calls must be listed here, or it is served by
    // Vite (HTML 404) instead of Flask and the feature silently dies in dev.
    proxy: {
      "/run":         { target: BACKEND, changeOrigin: true },
      "/stream":      { target: BACKEND, changeOrigin: true },
      "/approve":     { target: BACKEND, changeOrigin: true },
      "/runs":        { target: BACKEND, changeOrigin: true },
      "/cancel":      { target: BACKEND, changeOrigin: true },
      "/pause":       { target: BACKEND, changeOrigin: true },
      "/resume":      { target: BACKEND, changeOrigin: true },
      "/stop":        { target: BACKEND, changeOrigin: true },
      "/app-status":  { target: BACKEND, changeOrigin: true },
      "/loan":        { target: BACKEND, changeOrigin: true },
      "/clients":     { target: BACKEND, changeOrigin: true },
      "/skills":      { target: BACKEND, changeOrigin: true },
      "/rag":         { target: BACKEND, changeOrigin: true },
      "/docx":        { target: BACKEND, changeOrigin: true },
    },
  },
  build: {
    outDir: "dist",
  },
});
