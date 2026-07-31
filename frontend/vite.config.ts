import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// The app always calls a relative `/api`, so nothing in the code needs to know
// where the backend lives. In dev this proxy points at it; in the container
// nginx does the same job.
const apiTarget = process.env.VITE_API_PROXY ?? "http://127.0.0.1:8000";

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      "/api": { target: apiTarget, changeOrigin: true },
    },
  },
});
