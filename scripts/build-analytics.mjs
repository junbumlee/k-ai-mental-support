import { copyFile, mkdir } from "node:fs/promises";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const rootDir = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const sourcePath = resolve(
  rootDir,
  "node_modules",
  "@vercel",
  "analytics",
  "dist",
  "index.mjs"
);
const targetPath = resolve(rootDir, "static", "vendor", "vercel-analytics.mjs");

await mkdir(dirname(targetPath), { recursive: true });
await copyFile(sourcePath, targetPath);

console.log(`Copied ${sourcePath} -> ${targetPath}`);
