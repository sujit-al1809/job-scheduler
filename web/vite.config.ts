import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// The dashboard talks to the API at :8000. In dev we proxy /api to avoid CORS,
// so the client uses relative URLs. Override with VITE_API_BASE if needed.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      "/api": {
        target: "http://localhost:8000",
        changeOrigin: true,
      },
    },
  },
});
