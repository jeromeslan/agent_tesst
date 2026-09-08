import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// En dev : le serveur Vite pro proxie /api et /ws vers le backend FastAPI.
// En prod (docker) : nginx joue ce rôle (voir nginx.conf).
const BACKEND = process.env.BACKEND_URL || "http://localhost:8000";

export default defineConfig({
  plugins: [react()],
  server: {
    host: "0.0.0.0",
    port: 5173,
    allowedHosts: true, // prévisualisation distante (sandbox, reverse-proxy)
    proxy: {
      "/api": { target: BACKEND, changeOrigin: true },
      "/ws": { target: BACKEND.replace(/^http/, "ws"), ws: true, changeOrigin: true },
    },
  },
  preview: { host: "0.0.0.0", port: 4173 },
});
