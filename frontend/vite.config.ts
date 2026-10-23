// Vite builds and serves the dashboard; Vitest (configured below) runs its tests.
import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

// The dashboard calls the API with relative URLs (/api/...). In development, Vite forwards
// those to the FastAPI server, so the browser sees a single origin and the API needs no CORS
// headers. How the built files are served in production is decided in M8 (Docker).
const api = {
  "/api": { target: "http://127.0.0.1:8000", changeOrigin: false },
};

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: { host: "127.0.0.1", port: 5173, strictPort: true, proxy: api },
  preview: { host: "127.0.0.1", port: 4173, strictPort: true, proxy: api },
  test: {
    environment: "jsdom",
    setupFiles: ["src/test/setup.ts"],
    include: ["src/**/*.test.{ts,tsx}"],
  },
});
