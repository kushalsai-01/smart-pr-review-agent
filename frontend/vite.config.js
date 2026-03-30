import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      "/health": "http://127.0.0.1:8000",
      "/review": "http://127.0.0.1:8000",
      "/approve": "http://127.0.0.1:8000",
      "/stream": {
        target: "http://127.0.0.1:8000",
        changeOrigin: true,
      },
    },
  },
});
