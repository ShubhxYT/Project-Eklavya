import { fileURLToPath } from "node:url";
import { resolve } from "node:path";
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

const here = fileURLToPath(new URL(".", import.meta.url));
const backend = process.env.LEARNER_BACKEND_URL ?? "http://127.0.0.1:7861";

export default defineConfig({
  root: resolve(here, "learner"),
  publicDir: resolve(here, "public"),
  base: "/learn/",
  plugins: [react()],
  server: {
    host: "127.0.0.1",
    proxy: Object.fromEntries(
      ["/api", "/session", "/healthz"].map((path) => [path, { target: backend }]),
    ),
  },
  build: {
    outDir: resolve(here, "../end-user-client"),
    emptyOutDir: true,
    sourcemap: false,
  },
});
