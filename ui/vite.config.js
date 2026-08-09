import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Flask backend (server.py) runs on 5055 by default.
const BACKEND = process.env.ORCH_BACKEND || "http://127.0.0.1:5055";

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      "/run":         { target: BACKEND, changeOrigin: true },
      "/stream":      { target: BACKEND, changeOrigin: true },
      "/approve":     { target: BACKEND, changeOrigin: true },
      "/runs":        { target: BACKEND, changeOrigin: true },
      "/ledger":      { target: BACKEND, changeOrigin: true },
      "/comprehension": { target: BACKEND, changeOrigin: true },
      "/cancel":      { target: BACKEND, changeOrigin: true },
      "/stop":        { target: BACKEND, changeOrigin: true },
      "/app-status":  { target: BACKEND, changeOrigin: true },
    },
  },
  build: {
    outDir: "dist",
  },
});
