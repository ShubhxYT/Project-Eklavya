import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

export default defineConfig({
  plugins: [react()],
  base: "./",
  // ponytail: builds to frontend/dist — never to ../ui, which holds the
  // stock prebuilt Pipecat UI. To serve this app instead, point bot.py's
  // StaticFiles mount at frontend/dist.
  build: {
    outDir: "dist",
    emptyOutDir: true,
  },
  server: {
    proxy: {
      "/api": "http://localhost:7861",
    },
  },
});
