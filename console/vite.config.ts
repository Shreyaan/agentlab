import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

export default defineConfig({
  plugins: [react(), tailwindcss()],
  build: { outDir: "../src/agentlab/console_dist", emptyOutDir: true },
  server: { proxy: { "/v1": "http://127.0.0.1:8800" } },
});
