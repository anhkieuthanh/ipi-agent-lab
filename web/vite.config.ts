import { fileURLToPath, URL } from "node:url";

import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// Dev: Vite phục vụ giao diện ở 5180 và chuyển /api sang FastAPI (make console, cổng 8610).
// Build: dist/ được chính FastAPI phục vụ — một cổng duy nhất.
export default defineConfig({
  plugins: [react()],
  resolve: { alias: { "@": fileURLToPath(new URL("./src", import.meta.url)) } },
  server: {
    host: "127.0.0.1",
    port: 5180,
    strictPort: true,
    proxy: { "/api": "http://127.0.0.1:8610" },
  },
  build: { chunkSizeWarningLimit: 900 },
});
