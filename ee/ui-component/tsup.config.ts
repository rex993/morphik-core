import { defineConfig } from "tsup";

export default defineConfig({
  entry: ["src/index.ts"],
  format: ["cjs", "esm"],
  dts: true,
  splitting: false,
  sourcemap: true,
  clean: true,
  tsconfig: "./tsconfig.lib.json",
  external: ["react", "react-dom", "next", "next/image", "next/link", "@radix-ui/*"],
  esbuildOptions(options) {
    options.jsx = "automatic";
    options.jsxImportSource = "react";
    return options;
  },
});
