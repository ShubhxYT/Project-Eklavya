import { defineConfig } from "vite";

// IIFE build of the avatar overlay injected into the stock prebuilt UI.
export default defineConfig({
  build: {
    outDir: "dist-overlay",
    emptyOutDir: true,
    lib: {
      entry: "src/overlay/main.ts",
      name: "AvatarOverlay",
      formats: ["iife"],
      fileName: () => "avatar-overlay.js",
    },
  },
});
