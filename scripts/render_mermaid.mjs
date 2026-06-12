// 把 docs/diagrams/ 下所有 .mmd 文件渲染成同名 .svg
// 用法：node scripts/render_mermaid.mjs
// 依赖：beautiful-mermaid（本地或 npm 全局均可）

import { readFile, writeFile, readdir } from "node:fs/promises";
import { fileURLToPath, pathToFileURL } from "node:url";
import { dirname, resolve, basename } from "node:path";
import { execSync } from "node:child_process";

// 优先用本地 node_modules，找不到则 fallback 到 npm 全局位置
async function loadRenderer() {
  try {
    return await import("beautiful-mermaid");
  } catch {
    const root = execSync("npm root -g", { encoding: "utf-8" }).trim();
    const url = pathToFileURL(`${root}/beautiful-mermaid/dist/index.js`).href;
    return await import(url);
  }
}

const { renderMermaidSVG } = await loadRenderer();

const __dirname = dirname(fileURLToPath(import.meta.url));
const DIAGRAMS_DIR = resolve(__dirname, "../docs/diagrams");

const entries = await readdir(DIAGRAMS_DIR);
const sources = entries.filter((f) => f.endsWith(".mmd")).sort();

console.log(`找到 ${sources.length} 个 .mmd 源文件\n`);

let failed = 0;
for (const src of sources) {
  const name = basename(src, ".mmd");
  const srcPath = resolve(DIAGRAMS_DIR, src);
  const outPath = resolve(DIAGRAMS_DIR, `${name}.svg`);

  try {
    const code = await readFile(srcPath, "utf-8");
    const svg = renderMermaidSVG(code);
    await writeFile(outPath, svg, "utf-8");
    console.log(`✓ ${name}.svg（${svg.length} 字节）`);
  } catch (err) {
    failed++;
    console.error(`✗ ${name}: ${err.message}`);
  }
}

console.log(`\n汇总：成功 ${sources.length - failed} / ${sources.length}，失败 ${failed}`);
process.exit(failed > 0 ? 1 : 0);
